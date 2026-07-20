"""BLACS worker for QICKBoard -- software-trigger MVP.

Connects to a QickSoc proxy over Pyro4 (via amo_qick's qick.pyro.make_proxy) and
fires a fixed tProc program during transition_to_buffered. See qick_asm.py's
QickProgram.run() docstring: there is no blocking "done" RPC, so this worker does
not wait for the program to finish -- it fires and returns.

If auto_setup=True on the QICKBoard device, init() also ensures the board's own
Pyro4 server is actually running before connecting, launching it over SSH if
not -- see _ensure_board_server_running(). This replicates
board_setup/setup_qick_board.sh's launch step (not its one-time qick-package
install step) automatically, so getting the board's server running doesn't
need to be a separate manual step before BLACS starts.
"""
import os
import sys
import time

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
        global Pyro4_module
        Pyro4_module = Pyro4

        if self.auto_setup:
            self._ensure_board_server_running()

        from qick.pyro import make_proxy
        self.soc, self.soccfg = make_proxy(
            ns_host=self.ns_host, ns_port=self.ns_port, proxy_name=self.proxy_name,
            remote_traceback=False,
        )

    def _server_reachable(self, timeout=3):
        """Quick check: is the board's Pyro4 nameserver already up and serving
        our proxy_name? Short timeout -- this is a health check, not the real
        connection attempt."""
        try:
            Pyro4_module.config.COMMTIMEOUT = timeout
            ns = Pyro4_module.locateNS(host=self.ns_host, port=self.ns_port)
            return self.proxy_name in ns.list()
        except Exception:
            return False

    def _ensure_board_server_running(self):
        """SSH into the board and launch pyro_service.py if it's not already
        reachable. Mirrors board_setup/setup_qick_board.sh's launch step
        (sourcing the XRT environment, explicitly setting BOARD, launching
        detached) -- not its one-time qick-package-install step, which isn't
        safe or necessary to redo on every BLACS startup.

        Password comes from the QICK_BOARD_SSH_PASSWORD environment variable,
        deliberately NOT a connection-table property -- that would write it
        into every compiled shot's HDF5 file.
        """
        if self._server_reachable():
            return

        password = os.environ.get("QICK_BOARD_SSH_PASSWORD")
        if not password:
            raise RuntimeError(
                f"QICKBoard {self.device_name}: auto_setup=True but the board's Pyro4 "
                f"server at {self.ns_host}:{self.ns_port} is not reachable, and the "
                "QICK_BOARD_SSH_PASSWORD environment variable is not set (needed to "
                "SSH in and launch it). Set that environment variable before starting "
                "BLACS, or launch the server manually first "
                "(board_setup/setup_qick_board.sh)."
            )

        import paramiko

        remote_cmd = (
            "source /etc/profile.d/xrt_setup.sh 2>/dev/null; "
            f"export BOARD={self.board_env_name}; "
            f"cd {self.remote_qick_repo_path}/pyro4 && "
            f"nohup {self.pynq_venv_path}/bin/python3 pyro_service.py "
            "> pyro_service.log 2>&1 & disown"
        )

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                self.ssh_host, username=self.ssh_user, password=password, timeout=10,
            )
            # sudo -S reads the password from stdin -- write it directly over the
            # channel rather than `echo password | sudo -S ...`, which would
            # briefly expose the password as a process argument on the board.
            stdin, stdout, stderr = ssh.exec_command(
                f"sudo -S bash -c '{remote_cmd}'"
            )
            stdin.write(password + "\n")
            stdin.flush()
            stdout.channel.recv_exit_status()  # wait for the launcher command itself to return
        finally:
            ssh.close()

        # The server takes several seconds to load the FPGA overlay and register
        # itself -- poll rather than assuming it's instantly ready.
        deadline = time.time() + 40
        while time.time() < deadline:
            if self._server_reachable(timeout=2):
                return
            time.sleep(2)

        raise RuntimeError(
            f"QICKBoard {self.device_name}: launched pyro_service.py on "
            f"{self.ssh_host} via SSH, but {self.ns_host}:{self.ns_port} still isn't "
            "reachable after 40s. Check pyro_service.log on the board for the actual "
            "error (SSH in and inspect it directly -- see the root README's list of "
            "gotchas that can cause this: stale process on the port, wrong BOARD "
            "value, qick package/bitstream mismatch, XRT not sourced)."
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
