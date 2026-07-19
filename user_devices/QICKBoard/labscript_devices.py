"""Labscript device for triggering a QICK tProc program on an RFSoC board.

Software-trigger MVP: BLACS calls QickProgram.run(soc, start_src="internal") over
Pyro4 during transition_to_buffered. No compiled hardware pulse -- the `t` argument
to start_tproc() is recorded as metadata only. See the project plan/memory for the
staged hardware-trigger follow-up.
"""
from labscript import Device, TriggerableDevice, LabscriptError, set_passed_properties


class QICKBoard(TriggerableDevice):
    description = "QICK-controlled RFSoC board (tProc)"

    @set_passed_properties(
        property_names={
            "connection_table_properties": ["ns_host", "ns_port", "proxy_name", "board_model"],
            "device_properties": [
                "tproc_program_module", "tproc_program_class", "tproc_program_kwargs",
            ],
        }
    )
    def __init__(
        self, name,
        ns_host, ns_port=8888, proxy_name="myqick", board_model="rfsoc4x2",
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
            tproc_program_module (str): dotted module path containing the QickProgram
                subclass to run (importable from the BLACS worker process)
            tproc_program_class (str): name of the QickProgram subclass within that module
            tproc_program_kwargs (dict, optional): kwargs passed to the program's cfg dict
        """
        if tproc_program_module is None or tproc_program_class is None:
            raise LabscriptError(
                f"QICKBoard {name}: tproc_program_module and tproc_program_class are required"
            )
        self.BLACS_connection = f"{ns_host}:{ns_port}/{proxy_name}"
        self.tproc_program_kwargs = tproc_program_kwargs or {}
        self._software_trigger_time = None

        TriggerableDevice.__init__(self, name, None, None, parentless=True, **kwargs)

    def start_tproc(self, t):
        """Record the shot-relative time the tProc program should start.

        Software-trigger mode only compiles this as metadata (an HDF5 attribute) --
        the real Pyro4 call happens during BLACS's transition_to_buffered, not at
        this exact compiled time. See the hardware-trigger follow-up stage for a
        version where this compiles a real pulse instead.
        """
        if self._software_trigger_time is not None:
            raise LabscriptError(f"{self.name}: start_tproc() may only be called once per shot")
        self._software_trigger_time = round(t, 10)

    def generate_code(self, hdf5_file):
        # NOTE: TriggerableDevice.generate_code() calls do_checks(), which
        # unconditionally dereferences self.trigger_device -- not set for a
        # parentless device (software-trigger mode). Skip straight to Device's
        # implementation instead; there's no shared trigger to validate here.
        Device.generate_code(self, hdf5_file)
        group = self.init_device_group(hdf5_file)
        if self._software_trigger_time is not None:
            group.attrs["software_trigger_time"] = self._software_trigger_time
