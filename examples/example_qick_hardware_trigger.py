"""Hardware-triggered QICK pulse, timed by a real PrawnBlaster trigger pulse.

Demonstrates the full timing chain:
  1. PrawnBlaster (COM7) compiles a real 1us HIGH pulse on its clockline[0]
     physical output pin (Pico GPIO 9, the default out_pins[0]) at t=1.0s.
  2. That pin must be physically wired to the RFSoC 4x2's PMOD1 pin 0 --
     confirmed (via the board's own reported config) to be the tProc's
     external-start input, rising-edge triggered.
  3. The tProc program (HardwareTriggeredPulseProgram) is armed with
     start_src='external' during transition_to_buffered -- it does nothing
     until it sees that rising edge, then immediately plays a 1us, 110MHz
     constant pulse on DAC channel 0.

REQUIRES PHYSICAL WIRING: Pico GPIO 9 -> RFSoC 4x2 PMOD1 pin 0 (+ a shared
ground reference between the two boards). Without that wire, this shot still
compiles and runs (BLACS doesn't wait for the tProc to actually fire), but
the RFSoC will just sit armed and never see a trigger.

Verify with a scope: probe Pico GPIO 9 for the 1us trigger pulse at t=1.0s,
and the RFSoC's DAC 0 output (or PMOD1 pin 0 itself) for the resulting
110MHz pulse shortly after. Exact trigger-to-pulse latency has not been
measured -- see the project README's "Current limitations" for what's
verified vs. not.
"""
from labscript import start, stop
from labscript_devices.PrawnBlaster.labscript_devices import PrawnBlaster
from labscript_devices.DummyIntermediateDevice import DummyIntermediateDevice
from user_devices.QICKBoard.labscript_devices import QICKBoard

# Master pseudoclock -- real PrawnBlaster hardware on COM7. Re-verify the COM
# port with `python -m serial.tools.list_ports -v` if this has changed.
# clockline[0]'s physical output is Pico GPIO 9 (out_pins defaults to
# [9, 11, 13, 15]) -- this is the real wire to run to the RFSoC's PMOD1 pin 0.
prawnblaster_0 = PrawnBlaster(name='prawnblaster_0', com_port='COM7')
qick_trigger_intermediate = DummyIntermediateDevice(
    name='qick_trigger_intermediate', parent_device=prawnblaster_0.clocklines[0]
)

qick_board = QICKBoard(
    name='qick_board',
    ns_host='192.168.137.208',
    ns_port=8000,
    proxy_name='rfsoc',
    board_model='rfsoc4x2',
    trigger_mode='hardware',
    parent_device=qick_trigger_intermediate,
    connection='port0/line0',
    tproc_program_module='labscriptlib.RFSoCLabscript.qick_programs',
    tproc_program_class='HardwareTriggeredPulseProgram',
    tproc_program_kwargs={
        "res_ch": 0, "pulse_freq": 110, "pulse_gain": 3000,
        "pulse_length_us": 1.0, "res_phase": 0, "reps": 1,
    },
)

start()
# duration=5us for the trigger pulse itself -- DummyIntermediateDevice's
# clock_limit caps minimum instruction spacing at 1us, so 1us exactly was
# right at that boundary and failed to compile. The trigger pulse's width is
# independent of the RFSoC's own 1us/110MHz output pulse (played after being
# triggered) -- a few microseconds here is just "long enough to be a clean
# rising edge," not tied to the actual experiment timing.
qick_board.start_tproc(t=1.0, duration=5e-6)
stop(2.0)
