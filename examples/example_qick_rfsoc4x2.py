"""Example labscript experiment: trigger a QICK program on the RFSoC 4x2.

Loadable directly in runmanager to validate the QICKBoard integration
end-to-end. Uses the real PrawnBlaster (COM7) as the shot's master
pseudoclock -- required even though QICKBoard itself doesn't need one
(software-trigger mode, parentless): a shot with no real PseudoclockDevice at
all compiles fine, but hangs BLACS's queue manager indefinitely when run,
since there's no master clock to signal shot completion. See MinimalPulseProgram
in qick_programs.py for the actual tProc program that runs on the board.
"""
from labscript import start, stop, DigitalOut
from labscript_devices.PrawnBlaster.labscript_devices import PrawnBlaster
from labscript_devices.DummyIntermediateDevice import DummyIntermediateDevice
from user_devices.QICKBoard.labscript_devices import QICKBoard

# Master pseudoclock -- real PrawnBlaster hardware on COM7. Re-verify the COM
# port with `python -m serial.tools.list_ports -v` if this has changed since.
prawnblaster_0 = PrawnBlaster(name='prawnblaster_0', com_port='COM7')
intermediate_device = DummyIntermediateDevice(
    name='intermediate_device', parent_device=prawnblaster_0.clocklines[0]
)
my_digital_out = DigitalOut(
    name='my_digital_out', parent_device=intermediate_device, connection='port0/line0'
)

# Real RFSoC 4x2 running QICK, controlled over Pyro4 (software-trigger MVP).
# Confirm these against your board's actual running server if this changes --
# see board_setup/setup_qick_board.sh in the repo root.
qick_board = QICKBoard(
    name='qick_board',
    ns_host='192.168.137.208',
    ns_port=8000,
    proxy_name='rfsoc',
    board_model='rfsoc4x2',
    tproc_program_module='labscriptlib.RFSoCLabscript.qick_programs',
    tproc_program_class='MinimalPulseProgram',
    tproc_program_kwargs={
        "res_ch": 0, "ro_chs": [0], "reps": 1, "relax_delay": 1.0, "res_phase": 0,
        "length": 20, "readout_length": 100, "pulse_gain": 3000, "pulse_freq": 250,
        "adc_trig_offset": 100, "soft_avgs": 1,
    },
)

start()
my_digital_out.go_low(t=0)
my_digital_out.go_high(t=1)
qick_board.start_tproc(t=0.5)  # metadata only in this MVP -- see root README
stop(2.0)
