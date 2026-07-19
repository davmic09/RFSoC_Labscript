# RFSoC_Labscript

Tools and a custom [labscript-suite](http://labscriptsuite.org/) device (`QICKBoard`) for
triggering a [QICK](https://github.com/openquantumhardware/qick)-controlled RFSoC board from a
labscript experiment shot.

## What's in this repo

- **`user_devices/QICKBoard/`** -- the labscript device itself (connection-table class, BLACS
  worker/tab, registration). Drop this into any labscript profile's `user_devices` folder.
- **`board_setup/`** -- scripts to set up the Pyro4 control server on a PYNQ-based RFSoC board
  (RFSoC4x2, ZCU216, ZCU111, ...) so a labscript `QICKBoard` can reach it over the network.
- **`patch_labscript_numpy2.py`** -- one-time fix for labscript 3.4.2 on NumPy 2 / Python 3.13
  (see "Prerequisites" below). Not RFSoC/QICK-specific -- needed for labscript itself to run here.
- **`compile_shot.py`** -- headless labscript compiler, for validating a connection table /
  experiment script without opening the runmanager GUI.
- **`simple_example.py`** -- a minimal PulseBlaster smoke-test script, unrelated to the RFSoC/QICK
  work; kept as a basic "does labscript compile at all" sanity check.

## Prerequisites

If you're on Python 3.13 with NumPy 2 (as this environment is), labscript 3.4.2 crashes on shot
compilation with `TypeError: data type 'a256' not understood` -- a legacy dtype spelling removed
in NumPy 2.0. Run `python patch_labscript_numpy2.py` once after installing/reinstalling the
labscript suite to fix this (idempotent, safe to re-run; `--check` reports without writing).

You'll also need `Pyro4` and `psutil` installed in whatever Python environment runs BLACS
(`pip install Pyro4 psutil`) -- these aren't labscript dependencies, they're what `QICKBoard`'s
worker uses to talk to the board.

## Integrating QICKBoard into an already-working labscript-suite install

Assumes you already have labscript-suite (labscript, BLACS, runmanager) installed and a
labscript profile with an apparatus set up (a working connection table, even without QICKBoard).

1. **Copy the device into your profile.** Copy `user_devices/QICKBoard/` into your labscript
   profile's `user_devices` directory -- the path your labconfig's `user_devices` setting points
   at, typically `<labscript-suite>/userlib/user_devices/QICKBoard/`.

2. **Make `qick` importable in your BLACS environment.** `pip install -e /path/to/your/qick`
   (a clone of `openquantumhardware/qick` or a fork -- needs a `qick_lib/` directory and a
   `setup.py`) into the same venv BLACS runs in. This is the reliable option; see
   `user_devices/QICKBoard/README.md` for a documented (less reliable) environment-variable
   fallback.

3. **Set up the Pyro4 server on the RFSoC board itself.** The board needs a Pyro4 nameserver +
   QICK proxy server running and reachable over the network *before* BLACS can talk to it. On the
   board (via SSH or a JupyterLab terminal):
   ```
   sudo ./board_setup/setup_qick_board.sh /path/to/qick/checkout/on/the/board
   ```
   This handles the environment-sourcing gotchas (the `BOARD` variable, XRT setup, matching the
   installed `qick` version to the loaded bitstream, clearing stale processes) documented in the
   script's own header comment. Verify it worked from your control PC:
   ```python
   import Pyro4
   Pyro4.config.SERIALIZER = "pickle"
   Pyro4.config.PICKLE_PROTOCOL_VERSION = 4
   ns = Pyro4.locateNS(host="<board IP>", port=8000)
   print(ns.list())  # should show your proxy_name registered
   ```

4. **Write a tProc program.** `QICKBoard` runs a plain `QickProgram`/`AveragerProgram` subclass
   you provide -- it has no built-in pulse sequence. Put it somewhere importable from your BLACS
   worker process (e.g. a module in your `labscriptlib` apparatus folder). A minimal example:
   ```python
   from qick import AveragerProgram

   class MyTProcProgram(AveragerProgram):
       def initialize(self):
           cfg = self.cfg
           self.declare_gen(ch=cfg["res_ch"], nqz=1)
           freq = self.freq2reg(cfg["pulse_freq"], gen_ch=cfg["res_ch"])
           self.set_pulse_registers(ch=cfg["res_ch"], style="const",
                                     freq=freq, phase=0, gain=cfg["pulse_gain"],
                                     length=cfg["length"])
           self.synci(200)

       def body(self):
           self.pulse(ch=self.cfg["res_ch"])
   ```

5. **Add `QICKBoard` to your connection table.**
   ```python
   from user_devices.QICKBoard.labscript_devices import QICKBoard

   qick_board = QICKBoard(
       name='qick_board',
       ns_host='192.168.1.100',      # the board's IP
       ns_port=8000,                  # matches board_setup script
       proxy_name='rfsoc',            # matches board_setup script
       board_model='rfsoc4x2',        # informational only
       tproc_program_module='labscriptlib.MyApparatus.qick_programs',
       tproc_program_class='MyTProcProgram',
       tproc_program_kwargs={
           "res_ch": 0, "pulse_freq": 250, "pulse_gain": 3000, "length": 20,
       },
   )
   ```

6. **Recompile your connection table and restart BLACS.** Same as adding any new device: BLACS
   reads the connection table via labconfig's `connection_table_py`/`connection_table_h5` paths
   (its own "recompile connection table" menu option does this, or you can do it headlessly --
   see `compile_shot.py` in this repo for the pattern). Confirm the `qick_board` tab appears in
   BLACS with no errors before proceeding.

## Operating the RFSoC from a labscript experiment

In your experiment script (alongside your other device calls, inside the same `start()`/`stop()`
timeline):

```python
start()
# ... your other device timing ...
qick_board.start_tproc(t=0.5)   # see "Current limitations" below
stop(2.0)
```

Compile and run the shot exactly as you would for any other apparatus -- through runmanager, or
headlessly with `compile_shot.py`. When BLACS processes the shot, `qick_board`'s worker connects
to the board over Pyro4 and calls `QickProgram.run(soc, start_src="internal")`, which loads and
starts your tProc program on the real hardware.

### Current limitations (this is a software-trigger MVP)

- **Timing is not hardware-deterministic.** `start_tproc(t)`'s `t` argument is recorded as
  metadata only -- the actual Pyro4 call fires whenever BLACS's queue manager reaches that step in
  `transition_to_buffered`, not precisely at `t` seconds into the shot. Real hardware-timed
  triggering would use the board's PMOD external-start input (confirmed present on RFSoC4x2,
  ZCU111, and ZCU216 alike) driven by a real digital pulse from another labscript device (e.g. a
  PrawnBlaster output) -- not yet implemented.
- **No completion detection.** `transition_to_manual` doesn't wait for the tProc program to
  finish -- QICK/Pyro4 has no blocking "done" RPC. If your program's runtime matters relative to
  the rest of the shot, budget for that with the shot's own compiled duration (`stop(t)`), since
  labscript itself won't know when the tProc program actually completes.
- **No data retrieval.** Acquired ADC/readout data isn't pulled back into the shot's HDF5 file.
  You'd need to extend the worker's `transition_to_manual` (e.g. via `soc.poll_data()`) to add
  this -- not implemented here.
- **One fixed program per connection table entry.** No per-shot program/parameter selection via
  runmanager globals.
- **Multiple RFSoC boards** (e.g. porting from an RFSoC4x2 to a ZCU216) should only need a new
  `ns_host`/`board_model` and a fresh `board_setup/setup_qick_board.sh` run on that board -- the
  underlying trigger mechanism and Pyro4 control plane are the same across boards.
