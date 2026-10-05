"""Labscript device for triggering a QICK tProc program on an RFSoC board.

Two trigger modes:
  - trigger_mode='software' (default, the original MVP): BLACS calls
    QickProgram.run(soc, start_src="internal") over Pyro4 during
    transition_to_buffered. No compiled hardware pulse -- start_tproc(t)'s `t`
    is recorded as metadata only. ms-scale jitter, no new wiring required.
  - trigger_mode='hardware': start_tproc(t) compiles a real digital trigger
    pulse (via TriggerableDevice.trigger()) on parent_device/connection, and
    the worker sets start_src="external" -- the tProc program only starts once
    it sees a real rising edge on the board's PMOD1 pin 0 (confirmed present
    on RFSoC4x2/ZCU111/ZCU216 alike). Requires physically wiring
    parent_device's real output pin to that PMOD1 pin 0.
"""
from labscript import Device, TriggerableDevice, LabscriptError, set_passed_properties


class QICKBoard(TriggerableDevice):
    description = "QICK-controlled RFSoC board (tProc)"
    trigger_edge_type = "rising"  # matches PMOD1 pin 0's external-start behavior
    # Placeholder -- not empirically measured against real hardware. Only matters
    # if start_tproc() is called multiple times close together in the same shot.
    minimum_recovery_time = 1e-6

    @set_passed_properties(
        property_names={
            "connection_table_properties": [
                "ns_host", "ns_port", "proxy_name", "board_model", "trigger_mode",
                "auto_setup", "ssh_host", "ssh_user", "board_env_name",
                "remote_qick_repo_path", "pynq_venv_path",
                # NOTE: tproc_program_module/class/kwargs deliberately do NOT
                # also live here. labscript/labscript.py's
                # generate_connection_table() builds the connection table's
                # comparison "properties" column exclusively from
                # connection_table_properties -- if these were listed here
                # too, two shots with different set_tproc_program() values
                # would get different connection-table snapshots and BLACS
                # would reject the second as "not a subset of the
                # experimental control apparatus" (confirmed the hard way).
                # device_properties below is the only correct location for
                # values meant to vary per shot.
            ],
            "device_properties": [
                "tproc_program_module", "tproc_program_class", "tproc_program_kwargs",
            ],
        }
    )
    def __init__(
        self, name,
        ns_host, ns_port=8888, proxy_name="myqick", board_model="ZCU216",
        trigger_mode="software", parent_device=None, connection=None,
        tproc_program_module=None, tproc_program_class=None, tproc_program_kwargs=None,
        auto_setup=False, ssh_host=None, ssh_user="xilinx", board_env_name=None,
        remote_qick_repo_path=None, pynq_venv_path="/usr/local/share/pynq-venv",
        **kwargs,
    ):
        """QICK-controlled RFSoC board.

        Args:
            name (str): python variable name to assign
            ns_host (str): Pyro4 nameserver host/IP
            ns_port (int): Pyro4 nameserver port
            proxy_name (str): registered name of the QickSoc proxy on the nameserver
            board_model (str): informational board identity string (e.g. 'rfsoc4x2')
            trigger_mode (str): 'software' (default) or 'hardware'
            parent_device (IntermediateDevice, optional): required if trigger_mode is
                'hardware' -- the device whose real output pin is physically wired to
                the board's PMOD1 pin 0 (external tProc start input).
            connection (str, optional): required if trigger_mode is 'hardware' -- the
                connection string (e.g. 'port0/line1') on parent_device to use.
            tproc_program_module (str, optional): dotted module path containing the
                QickProgram subclass to run (importable from the BLACS worker
                process). May be left unset here and provided per-shot instead via
                set_tproc_program() -- see that method's docstring. If still unset
                by the time a shot actually runs, transition_to_buffered() raises
                a clear RuntimeError.
            tproc_program_class (str, optional): name of the QickProgram subclass
                within that module. Same optionality as tproc_program_module above.
            tproc_program_kwargs (dict, optional): kwargs passed to the program's cfg dict
            auto_setup (bool): if True, the BLACS worker checks whether the board's
                Pyro4 server is reachable during init(), and if not, SSHes in and
                launches it automatically (replicating board_setup/setup_qick_board.sh),
                instead of requiring that as a manual prior step. Default False --
                opt in explicitly, since this means BLACS's own initialization now
                depends on SSH reaching the board. Requires ssh_host/ssh_user/
                board_env_name/remote_qick_repo_path below, and the
                QICK_BOARD_SSH_PASSWORD environment variable (deliberately NOT a
                connection-table property -- that would write the password into every
                compiled shot's HDF5 file).
            ssh_host (str, optional): SSH host for auto_setup. Defaults to ns_host.
            ssh_user (str): SSH username for auto_setup. Default 'xilinx' (PYNQ default).
            board_env_name (str, optional): BOARD environment variable value for
                auto_setup (e.g. 'RFSoC4x2', 'ZCU216') -- required if auto_setup=True.
            remote_qick_repo_path (str, optional): path to the qick checkout on the
                board (containing qick_lib/ and pyro4/pyro_service.py) -- required if
                auto_setup=True.
            pynq_venv_path (str): path to the PYNQ venv on the board. Default
                '/usr/local/share/pynq-venv' (standard PYNQ image location).
        """
        if trigger_mode not in ("software", "hardware"):
            raise LabscriptError(
                f"QICKBoard {name}: trigger_mode must be 'software' or 'hardware', "
                f"not {trigger_mode!r}"
            )
        if trigger_mode == "hardware" and (parent_device is None or connection is None):
            raise LabscriptError(
                f"QICKBoard {name}: trigger_mode='hardware' requires parent_device and "
                "connection (the real output pin wired to the board's PMOD1 pin 0)."
            )
        if trigger_mode == "software" and parent_device is not None:
            raise LabscriptError(
                f"QICKBoard {name}: trigger_mode='software' takes no parent_device "
                "(there is no compiled pulse -- the Pyro4 RPC call is the trigger)."
            )
        if auto_setup and (board_env_name is None or remote_qick_repo_path is None):
            raise LabscriptError(
                f"QICKBoard {name}: auto_setup=True requires board_env_name and "
                "remote_qick_repo_path."
            )

        self.BLACS_connection = f"{ns_host}:{ns_port}/{proxy_name}"
        self.trigger_mode = trigger_mode
        self.tproc_program_kwargs = tproc_program_kwargs or {}
        self._software_trigger_time = None
        self.auto_setup = auto_setup
        self.ssh_host = ssh_host or ns_host
        self.ssh_user = ssh_user
        self.board_env_name = board_env_name
        self.remote_qick_repo_path = remote_qick_repo_path
        self.pynq_venv_path = pynq_venv_path

        if trigger_mode == "software":
            TriggerableDevice.__init__(self, name, None, None, parentless=True, **kwargs)
        else:
            TriggerableDevice.__init__(self, name, parent_device, connection, **kwargs)

    def set_tproc_program(self, tproc_program, tproc_program_kwargs=None):
        """Override this shot's tProc program -- which class/factory runs, and
        optionally its full cfg -- instead of fixing a specific script in the
        connection table.

        tproc_program: the actual QickProgram/AveragerProgram subclass to run,
        OR a factory callable that takes a single cfg dict and returns such a
        subclass (e.g. qick_programs.py's InterleavedDrive, which closes over
        its cfg inside a dynamically-defined class rather than reading
        self.cfg). Only __module__/__qualname__ get written into the shot's
        HDF5 device_properties (tproc_program_module/tproc_program_class,
        unchanged keys) -- the BLACS worker process only ever reads the
        compiled HDF5 file, so it re-imports by that dotted name and, via
        inspect.isclass(), either instantiates directly or calls the factory
        first with tproc_program_kwargs. See blacs_workers.py's
        _resolve_tproc_program_class() for the worker-side half of this
        contract.

        Call this from your experiment script's __main__ block (guarded, not
        the connection table's own smoke test -- see set_tproc_program_kwargs()'s
        docstring for why). Must be called *after* construction but *before*
        stop(), for the same frozen-snapshot reason documented there.
        """
        tproc_program_module = tproc_program.__module__
        tproc_program_class = tproc_program.__qualname__
        self.tproc_program_module = tproc_program_module
        self.tproc_program_class = tproc_program_class
        self.set_property(
            "tproc_program_module", tproc_program_module,
            location="device_properties", overwrite=True,
        )
        self.set_property(
            "tproc_program_class", tproc_program_class,
            location="device_properties", overwrite=True,
        )
        if tproc_program_kwargs is not None:
            self.set_tproc_program_kwargs(tproc_program_kwargs)

    def set_tproc_program_kwargs(self, tproc_program_kwargs):
        """Override this shot's tProc program cfg dict.

        Call this from your experiment script's __main__ block, with values
        sourced from runmanager globals (bare names runmanager resolves and
        records into the shot's own /globals group), so parameters are
        tracked per-shot instead of fixed once at connection-table-definition
        time. Must be called *after* construction but *before* stop() --
        the __init__-time value set via @set_passed_properties is a frozen
        snapshot (Device._properties), so a plain attribute reassignment
        alone would not reach the compiled shot; this also re-sets the
        device_properties entry with overwrite=True so it does.
        """
        self.tproc_program_kwargs = tproc_program_kwargs
        self.set_property(
            "tproc_program_kwargs", tproc_program_kwargs,
            location="device_properties", overwrite=True,
        )

    def start_tproc(self, t, duration=1e-6):
        """Start the tProc program at shot-relative time t.

        software mode: `t` is recorded as metadata only (an HDF5 attribute) --
        the real Pyro4 call happens whenever BLACS's queue manager reaches this
        device during transition_to_buffered, not deterministically at `t`.

        hardware mode: compiles a real digital trigger pulse of length
        `duration` at time `t`, via the wired parent_device/connection. The
        tProc program starts precisely when it sees that pulse's rising edge.
        """
        if self.trigger_mode == "hardware":
            self.trigger(t, duration)
        else:
            if self._software_trigger_time is not None:
                raise LabscriptError(
                    f"{self.name}: start_tproc() may only be called once per shot"
                )
            self._software_trigger_time = round(t, 10)

    def generate_code(self, hdf5_file):
        if self.trigger_mode == "hardware":
            # Safe here -- self.trigger_device is set for a real parent_device.
            TriggerableDevice.generate_code(self, hdf5_file)
        else:
            # NOTE: TriggerableDevice.generate_code() calls do_checks(), which
            # unconditionally dereferences self.trigger_device -- not set for a
            # parentless device (software-trigger mode). Skip straight to
            # Device's implementation instead; there's no shared trigger here.
            Device.generate_code(self, hdf5_file)
        group = self.init_device_group(hdf5_file)
        if self._software_trigger_time is not None:
            group.attrs["software_trigger_time"] = self._software_trigger_time
