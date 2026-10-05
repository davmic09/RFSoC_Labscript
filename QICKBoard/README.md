# QICKBoard

A labscript device that triggers a [QICK](https://github.com/openquantumhardware/qick) tProc
program on an RFSoC board over Pyro4, as part of a labscript shot. Supports two trigger modes:
`trigger_mode='software'` (default -- a Pyro4 RPC call fires the program, no wiring needed) and
`trigger_mode='hardware'` (a real compiled trigger pulse gates the tProc's own external-start
input). See the root repo README for full details, including hardware-trigger wiring.

## Moving to a different board (or a new/reflashed one) -- checklist

This device has previously been pointed at the wrong board's settings without any obvious error
until the shot actually ran (or, worse, until the board's FPGA manager wedged itself). Everything
below must agree with the *actual physical board* you're talking to -- check all of it after
swapping boards, re-imaging one, or copying a connection table between setups.

1. **`ns_host` / `ssh_host` (the board's static IP)** -- set in the `QICKBoard(...)` connection
   table entry. Verify with `ping <ip>` and, if `auto_setup` is used, that SSH actually logs in
   (`ssh xilinx@<ip>`).
2. **The bitstream in `pyro4/pyro_service.py` on the board itself must match the board model.**
   `amo_qick/qick_lib/qick/` ships one `.bit`/`.hwh` pair per board (e.g. `qick_4x2.bit` for an
   RFSoC4x2, `qick_216.bit` for a ZCU216) -- `pyro_service.py`'s `bitfile` variable is a hardcoded
   relative path and does **not** auto-detect which board it's running on. Loading the wrong one
   doesn't fail cleanly: it can throw `OSError: [Errno 12] Cannot allocate memory` out of PYNQ's
   `Overlay.download()`, and leave `/sys/class/fpga_manager/fpga0/state` stuck in `write error`
   (check with `cat` over SSH) until the next successful download self-heals it or the board is
   rebooted. Confirm the real board model first with `cat /proc/device-tree/model` over SSH, then
   match the bitfile to it.
3. **`ns_host` inside that same `pyro_service.py` must be `'0.0.0.0'`, not the default
   `'localhost'`.** With `'localhost'`, the process starts and *looks* fine locally (`ps`/`ss` show
   it listening on `8000`) but is only reachable from the board itself -- the BLACS PC's
   `Pyro4.locateNS()` will just time out. The file's own comment calls this out; it's easy to miss.
4. **`proxy_name`** in the connection table must match the `proxy_name` set in that same
   `pyro_service.py` on the board (both default to values like `'rfsoc'`/`'myqick'`, but they're
   independent strings that must be typed identically on both sides).
5. **`board_model`** (informational) and, if using `auto_setup`, **`board_env_name`** (the `BOARD`
   environment variable auto_setup exports before launching, e.g. `'ZCU216'`) should both reflect
   the real board.
6. **`remote_qick_repo_path`** (if using `auto_setup`) must be the actual path to a qick/amo_qick
   checkout *on that board's filesystem* -- boards may have more than one checkout present (e.g.
   both `~/jupyter_notebooks/qick` and `~/jupyter_notebooks/amo_qick`); point at the one you
   actually want running, and remember `pyro_service.py`'s fixes in point 2/3 above need making in
   whichever one you pick.
7. **QICK library version** on the board vs. the version pip-installed in the BLACS venv. A
   mismatch doesn't block the connection but logs a `QICK library version mismatch` warning from
   `qick.pyro.make_proxy()` and can cause a `KeyError` during `QickConfig` initialization later --
   if you see that, this is the first thing to check (`pip show qick` locally vs. the board's
   installed version).
8. **SSH credentials** for `auto_setup` -- `ssh_user` (connection table) and the
   `QICK_BOARD_SSH_PASSWORD` environment variable (set in BLACS's own environment, not the
   connection table) must be correct for the new board; PYNQ images default to `xilinx`/`xilinx`
   but this isn't guaranteed across boards.

## Install into a labscript-suite environment

1. Make sure the BLACS venv's `labscript_devices` package is this repo (or a fork of it) containing
   this `QICKBoard/` folder -- e.g. `pip install -e /path/to/this/labscript-devices` checkout. This
   device's own `register_classes.py`/`blacs_tabs.py` reference `labscript_devices.QICKBoard...`
   (not a separate `user_devices` copy), so it must actually be part of the installed
   `labscript_devices` package, not copied elsewhere on `sys.path` under a different top-level name.
2. Make sure `qick` is importable in that Python environment: `pip install -e /path/to/your/qick`
   (a clone of `openquantumhardware/qick` or a fork -- must contain a `qick_lib/` directory and a
   `setup.py`) into the same venv BLACS runs in. This is the reliable option.

   `blacs_workers.py` also checks a `QICK_LIB_PATH` environment variable and adds it to `sys.path`
   as a fallback if set, for cases where you don't want to `pip install`. **Caveat**: this only
   works if BLACS's worker subprocess actually inherits that variable -- in testing, setting
   `QICK_LIB_PATH` on the parent `blacs.exe` process's environment did *not* reliably propagate to
   its worker subprocesses (BLACS spawns workers via its own process-launching mechanism, not
   simple inheritance). If you rely on this fallback, verify it actually reaches the worker (check
   for `ModuleNotFoundError: No module named 'qick'` in BLACS's log) rather than assuming it works.
3. On the RFSoC board itself, a Pyro4 nameserver + QICK proxy server must be running and reachable
   over the network -- see `../board_setup/setup_qick_board.sh` in this repo to set that up on a
   new board (one time). After that, pass `auto_setup=True` (see below) and BLACS will bring the
   server back up itself on every startup if it's ever down, instead of needing that as a repeated
   manual step. `auto_setup=True` needs `pip install paramiko` in the BLACS environment.

## Connection table usage

See `connection_table_example.py` in this folder for two complete, copy-pasteable patterns
(minimal software-trigger, and full hardware-trigger + auto_setup + a production/test board
toggle) -- both verified importable as-is, just replace the placeholder IP/COM-port/paths with
your own values.

```python
from labscript_devices.QICKBoard.labscript_devices import QICKBoard

qick_board = QICKBoard(
    name='qick_board',
    ns_host='192.168.1.100',     # the board's IP
    ns_port=8000,                 # Pyro4 nameserver port (matches board_setup script)
    proxy_name='rfsoc',           # matches the proxy_name used on the board
    board_model='rfsoc4x2',       # informational only
    tproc_program_module='labscriptlib.MyApparatus.qick_programs',
    tproc_program_class='MyTProcProgram',
    tproc_program_kwargs={...},   # forwarded to your QickProgram subclass's cfg dict
)
```

In your experiment script:

```python
qick_board.start_tproc(t=0.5)  # metadata only in software mode -- see root README
```

`tproc_program_module`/`tproc_program_class` must name an importable `QickProgram`/
`AveragerProgram` subclass, resolved inside the BLACS worker process via
`labscript_utils.device_registry.import_class_by_fullname`. Works for tProc v1 and v2 program
classes alike, since `run()` (which the worker calls) is defined once on a shared base class.

**Both are optional** -- omit them from the constructor entirely and the connection table doesn't
need to hardcode a specific script at all. Call `qick_board.set_tproc_program(tproc_program, {...})`
from your experiment script instead, passing the actual class or a *factory callable* -- a function
taking a single cfg dict and returning a QickProgram subclass with that cfg baked in (e.g.
qick_programs.py's `InterleavedDrive`) -- so *which* program runs is chosen per-shot rather than
fixed in the connection table. `set_tproc_program` derives the dotted module/class name from the
passed object's `__module__`/`__qualname__` for storage in the shot's HDF5 file; the worker
re-imports it by that name and, via `inspect.isclass()`, either instantiates it directly or calls
it first (with `tproc_program_kwargs`) if it's a factory. To track only the kwargs while keeping
the module/class fixed, call `qick_board.set_tproc_program_kwargs({...})` instead. See the root
README's "Tracking pulse parameters as runmanager globals" section -- there's a real gotcha around
*where* you do this if the same file is also BLACS's own connection table.

## Auto-setup (no manual SSH step before starting BLACS)

```python
qick_board = QICKBoard(
    name='qick_board', ns_host=..., ns_port=..., proxy_name=..., board_model=...,
    auto_setup=True, ssh_user='xilinx', board_env_name='RFSoC4x2',
    remote_qick_repo_path='/home/xilinx/jupyter_notebooks/amo_qick',
    ...
)
```

The worker's `init()` checks whether the board's server is reachable and, if not, SSHes in (via
`paramiko`) and launches it automatically. Set `QICK_BOARD_SSH_PASSWORD` in BLACS's environment
before starting it -- deliberately not a connection-table property, since that would land in
every compiled shot's HDF5 file. Verified end-to-end through a real BLACS startup with the board's
server intentionally killed beforehand: ~20s to detect, launch, and connect, with zero other
manual steps. See the root README for the fuller writeup.

## Limitations (by design, this pass)

- **`trigger_mode`, `auto_setup`, `board_env_name`, `remote_qick_repo_path`, etc. are still fixed
  per connection table entry, not per shot** -- read once at BLACS tab-init time. These are
  `connection_table_properties`, part of the connection table's own structural comparison: a shot
  whose values differ from BLACS's currently loaded connection table is rejected as "not a subset
  of the experimental control apparatus." Only `tproc_program_module`/`tproc_program_class`/
  `tproc_program_kwargs` (`device_properties`) can vary per shot, via `set_tproc_program()`/
  `set_tproc_program_kwargs()`.
- **Hardware-trigger mode's actual trigger detection is unverified over a real wire** -- confirmed
  the worker arms correctly and the shot compiles/runs, but not confirmed with a scope that the
  physical rising edge is actually detected and the resulting latency. See root README.
- **No completion detection / data retrieval.** `transition_to_manual` doesn't wait for the tProc
  program to finish or pull back acquired data -- QICK/Pyro4 has no blocking "done" RPC. Both are
  planned follow-ups (a WaitMonitor-based hardware loopback, and a `transition_to_manual`
  extension modeled on `IMAQdxCamera`'s image-saving pattern, respectively).
