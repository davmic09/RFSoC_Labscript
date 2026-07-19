# QICKBoard

A labscript device that triggers a [QICK](https://github.com/openquantumhardware/qick) tProc
program on an RFSoC board over Pyro4, as part of a labscript shot. Software-trigger MVP: BLACS
calls `QickProgram.run(soc, start_src="internal")` during `transition_to_buffered` -- no hardware
trigger pulse yet (see "Limitations" below).

## Install into a labscript-suite environment

1. Copy this `QICKBoard/` folder into your labscript profile's `user_devices` directory (the path
   your labconfig's `user_devices` setting points at, typically
   `<labscript-suite>/userlib/user_devices/QICKBoard/`).
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
3. On the RFSoC board itself, a Pyro4 nameserver + QICK proxy server must already be running and
   reachable over the network -- see `../board_setup/setup_qick_board.sh` in this repo to set
   that up on a new board.

## Connection table usage

```python
from user_devices.QICKBoard.labscript_devices import QICKBoard

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
qick_board.start_tproc(t=0.5)  # metadata only in this MVP -- see Limitations
```

`tproc_program_module`/`tproc_program_class` must name an importable `QickProgram`/
`AveragerProgram` subclass, resolved inside the BLACS worker process via
`labscript_utils.device_registry.import_class_by_fullname`.

## Limitations (by design, this pass)

- **Software trigger only.** The Pyro4 RPC fires whenever BLACS's queue manager reaches that
  step during `transition_to_buffered` -- not deterministically at the shot-relative time passed
  to `start_tproc(t)`. Real hardware-timed triggering (via the board's PMOD external-start pin)
  is a planned follow-up, not yet implemented.
- **No completion detection / data retrieval.** `transition_to_manual` doesn't wait for the tProc
  program to finish or pull back acquired data -- QICK/Pyro4 has no blocking "done" RPC. Both are
  planned follow-ups (a WaitMonitor-based hardware loopback, and a `transition_to_manual`
  extension modeled on `IMAQdxCamera`'s image-saving pattern, respectively).
- **One fixed program per connection table entry.** No per-shot program/parameter selection via
  runmanager globals yet.
