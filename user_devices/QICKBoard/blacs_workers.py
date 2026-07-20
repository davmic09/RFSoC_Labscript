"""BLACS worker for QICKBoard -- software-trigger MVP.

Connects to a QickSoc proxy over Pyro4 (via amo_qick's qick.pyro.make_proxy) and
fires a fixed tProc program during transition_to_buffered. See qick_asm.py's
QickProgram.run() docstring: there is no blocking "done" RPC, so this worker does
not wait for the program to finish -- it fires and returns.
"""
import os
import sys

# If qick isn't pip-installed in this environment, point the QICK_LIB_PATH
# environment variable at a qick_lib checkout (e.g. an amo_qick fork's
# qick_lib/ directory) and it'll be added to sys.path here. If qick IS
# pip-installed (e.g. `pip install -e /path/to/amo_qick`), this is a no-op.
_qick_lib_path = os.environ.get("QICK_LIB_PATH")
if _qick_lib_path and _qick_lib_path not in sys.path:
    sys.path.insert(0, _qick_lib_path)

from blacs.tab_base_classes import Worker


class QICKBoardWorker(Worker):
    def init(self):
        global h5py
        import labscript_utils.h5_lock
        import h5py
        global properties
        import labscript_utils.properties as properties
        global import_class_by_fullname
        from labscript_utils.device_registry import import_class_by_fullname

        import warnings
        warnings.filterwarnings("ignore", category=SyntaxWarning)

        import Pyro4
        Pyro4.config.SERIALIZER = "pickle"
        Pyro4.config.PICKLE_PROTOCOL_VERSION = 4

        from qick.pyro import make_proxy
        self.soc, self.soccfg = make_proxy(
            ns_host=self.ns_host, ns_port=self.ns_port, proxy_name=self.proxy_name,
            remote_traceback=False,
        )

    def transition_to_buffered(self, device_name, h5file, initial_values, fresh):
        with h5py.File(h5file, "r") as f:
            props = properties.get(f, device_name, "device_properties")

        cls = import_class_by_fullname(
            f"{props['tproc_program_module']}.{props['tproc_program_class']}"
        )
        prog = cls(self.soccfg, props["tproc_program_kwargs"])
        # In hardware mode this arms the tProc and returns immediately -- it does
        # NOT block waiting for the trigger (see QickProgram.run()'s docstring).
        # BLACS starts the master pseudoclock (which fires the real trigger pulse)
        # only after every device finishes transitioning to buffered, so the board
        # is guaranteed to already be armed by the time the pulse arrives.
        start_src = "external" if self.trigger_mode == "hardware" else "internal"
        prog.run(self.soc, load_prog=True, load_envelopes=True, start_src=start_src)
        return {}

    def transition_to_manual(self):
        return True

    def abort_buffered(self):
        if self.trigger_mode == "hardware":
            # Defensive: don't leave the board waiting for a trigger that a
            # subsequent shot/manual operation may never send.
            self.soc.start_src("internal")
        return True

    def abort_transition_to_buffered(self):
        return True

    def program_manual(self, values):
        return values

    def shutdown(self):
        pass
