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
            ],
            "device_properties": [
                "tproc_program_module", "tproc_program_class", "tproc_program_kwargs",
            ],
        }
    )
    def __init__(
        self, name,
        ns_host, ns_port=8888, proxy_name="myqick", board_model="rfsoc4x2",
        trigger_mode="software", parent_device=None, connection=None,
        tproc_program_module=None, tproc_program_class=None, tproc_program_kwargs=None,
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
            tproc_program_module (str): dotted module path containing the QickProgram
                subclass to run (importable from the BLACS worker process)
            tproc_program_class (str): name of the QickProgram subclass within that module
            tproc_program_kwargs (dict, optional): kwargs passed to the program's cfg dict
        """
        if tproc_program_module is None or tproc_program_class is None:
            raise LabscriptError(
                f"QICKBoard {name}: tproc_program_module and tproc_program_class are required"
            )
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

        self.BLACS_connection = f"{ns_host}:{ns_port}/{proxy_name}"
        self.trigger_mode = trigger_mode
        self.tproc_program_kwargs = tproc_program_kwargs or {}
        self._software_trigger_time = None

        if trigger_mode == "software":
            TriggerableDevice.__init__(self, name, None, None, parentless=True, **kwargs)
        else:
            TriggerableDevice.__init__(self, name, parent_device, connection, **kwargs)

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
