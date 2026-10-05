"""Copy-paste reference for adding QICKBoard to a labscript connection table.

Two complete, independent patterns below -- pick the one that matches your
setup, copy just that block into your own connection table, and replace every
placeholder (IP, COM port, paths, program names/kwargs) with your real values.
Both patterns use the device name 'qick_board' in this file only so each can
be verified importable on its own (`python -c "import connection_table_example"`).
Both patterns use the device name 'qick_board' -- EXAMPLE_PATTERN below picks
which one actually runs (only one device set can be "live" at a time, same as
in a real connection table), so importing this file whole is always safe;
rename to whatever you like when you copy a pattern out.

See this folder's README.md for the full option reference (auto_setup,
trigger_mode, the manual-control BLACS panel, etc.) and
RFSoC_Labscript/examples/example_qick_hardware_trigger.py for a complete,
runnable experiment script built on Pattern 2 below.
"""

EXAMPLE_PATTERN = 1  # 1 or 2 -- selects which pattern below actually runs

# =============================================================================
# Pattern 1: minimal -- software trigger, program fixed in the connection table
# =============================================================================
# No physical wiring required. BLACS fires the program over a Pyro4 RPC call
# during transition_to_buffered -- fine for initial bring-up/debugging, but
# the RPC's timing isn't hardware-deterministic (ms-scale jitter).
if EXAMPLE_PATTERN == 1:
    from labscript_devices.QICKBoard.labscript_devices import QICKBoard

    qick_board = QICKBoard(
        name='qick_board',
        ns_host='192.168.1.100',       # the board's static IP -- confirm with `ping`
        ns_port=8000,                   # Pyro4 nameserver port (matches board_setup script)
        proxy_name='rfsoc',             # matches the proxy_name used on the board
        board_model='rfsoc4x2',         # informational only, e.g. 'rfsoc4x2' or 'ZCU216'
        trigger_mode='software',        # no wiring needed -- see Pattern 2 for 'hardware'
        tproc_program_module='labscriptlib.MyApparatus.qick_programs',
        tproc_program_class='MyTProcProgram',
        tproc_program_kwargs={"res_ch": 0, "pulse_freq": 110, "pulse_gain": 3000},
    )

    # In your experiment script:
    #   qick_board.start_tproc(t=0.5)  # metadata only in software mode


# =============================================================================
# Pattern 2: hardware trigger + auto_setup + a production/test board toggle +
# choosing the tProc program from runmanager globals instead of hardcoding it
# =============================================================================
# This is the pattern actually used in the real experiment's connection table
# (see burgers_connection_table_lib.py's QICK_TEST_ON_RFSOC4X2 toggle and
# _make_qick_board() helper for the deployed version of this exact shape).
# Requires physically wiring parent_device's real output pin to the board's
# PMOD1 pin 0 (tProc external-start input) -- see the README's "Moving to a
# different board" checklist before pointing this at new hardware.
if EXAMPLE_PATTERN == 2:
    from labscript_devices.DummyIntermediateDevice import DummyIntermediateDevice
    from labscript_devices.PrawnBlaster.labscript_devices import PrawnBlaster
    from labscript_devices.QICKBoard.labscript_devices import QICKBoard

    # Set True to point qick_board at a sandbox/test board instead of the real
    # one -- one flag to flip, instead of maintaining two connection tables.
    QICK_TEST_MODE = False

    _QICK_BOARD_PARAMS = {
        False: dict(ns_host='192.168.1.19', board_model='ZCU216', board_env_name='ZCU216'),
        True: dict(ns_host='192.168.1.208', board_model='rfsoc4x2', board_env_name='RFSoC4x2'),
    }
    _qick_p = _QICK_BOARD_PARAMS[QICK_TEST_MODE]

    prawnblaster_0 = PrawnBlaster(name='prawnblaster_0', com_port='COM7')
    qick_trigger_intermediate = DummyIntermediateDevice(
        name='qick_trigger_intermediate', parent_device=prawnblaster_0.clocklines[0]
    )

    qick_board = QICKBoard(
        name='qick_board',
        ns_host=_qick_p['ns_host'],
        ns_port=8000,
        proxy_name='rfsoc',
        board_model=_qick_p['board_model'],
        trigger_mode='hardware',              # real trigger pulse, not a Pyro4 RPC
        parent_device=qick_trigger_intermediate,  # wired to the board's PMOD1 pin 0
        connection='port0/line0',
        auto_setup=True,                       # BLACS SSHes in and launches the board's
                                                # server if it's ever down -- no manual step
        ssh_user='xilinx',
        board_env_name=_qick_p['board_env_name'],
        remote_qick_repo_path='/home/xilinx/jupyter_notebooks/amo_qick',
        # No tproc_program_module/class/kwargs here -- set per-shot instead, in
        # your experiment script, so which script runs is chosen from
        # runmanager globals rather than fixed in the connection table:
        #
        #   qick_board.set_tproc_program(
        #       MyTProcProgram,  # the actual class (or a factory callable), not a string
        #       {"res_ch": res_ch, "pulse_freq": pulse_freq, "pulse_gain": pulse_gain,
        #        "pulse_length_us": pulse_length_us, "res_phase": res_phase, "reps": reps},
        #   )
        #   qick_board.start_tproc(t=1.0, duration=5e-6)
    )
