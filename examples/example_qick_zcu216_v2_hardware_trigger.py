"""ZCU216 / tProc v2 analogue of example_qick_hardware_trigger.py.

UNTESTED AGAINST REAL HARDWARE -- there is no ZCU216 in this setup to
validate against. This mirrors the RFSoC4x2 hardware-trigger example exactly
(same PrawnBlaster trigger mechanism, same PMOD1 pin 0 external-start pin,
confirmed via the .hwh hardware-handoff files to be wired identically across
RFSoC4x2/ZCU111/ZCU216), swapping only:
  - board_model/ns_host/proxy_name for the ZCU216
  - the tProc program for its v2 equivalent (qick_programs_v2.py) -- v2's
    add_pulse() API takes physical units directly, so the config values below
    are NOT the same numbers as the v1 example despite meaning the same thing
    (e.g. gain is a normalized float here, not a raw DAC integer).

Before using this for real:
  1. Set BOARD=ZCU216 (not RFSoC4x2) when running board_setup/setup_qick_board.sh
     on the ZCU216 -- this is what makes QickSoc auto-select qick_216.bit.
  2. Fill in ns_host below with the ZCU216's actual IP, and confirm ns_port/
     proxy_name against however pyro_service.py was actually launched there
     (see board_setup/README-equivalent notes in the root repo README).
  3. Validate qick_programs_v2.HardwareTriggeredPulseProgramV2 standalone
     against the real board first (make_proxy() + prog.run(soc,
     start_src='internal')), exactly as was done for the v1 program on the
     RFSoC4x2, before trusting this connection table end-to-end.
  4. Physically wire whatever trigger pin you use (PrawnBlaster clockline
     GPIO, same as the RFSoC4x2 example) to the ZCU216's PMOD1 pin 0.

REQUIRES PHYSICAL WIRING -- see example_qick_hardware_trigger.py's docstring;
identical requirement here, just against a different board.
"""
from labscript import start, stop
from labscript_devices.PrawnBlaster.labscript_devices import PrawnBlaster
from labscript_devices.DummyIntermediateDevice import DummyIntermediateDevice
from user_devices.QICKBoard.labscript_devices import QICKBoard

# Master pseudoclock -- reuses the same real PrawnBlaster hardware (COM7) as
# the RFSoC4x2 example. clockline[0]'s physical output pin (Pico GPIO 9) is
# the real wire to run to the ZCU216's PMOD1 pin 0.
prawnblaster_0 = PrawnBlaster(name='prawnblaster_0', com_port='COM7')
qick_trigger_intermediate = DummyIntermediateDevice(
    name='qick_trigger_intermediate', parent_device=prawnblaster_0.clocklines[0]
)

qick_board_zcu216 = QICKBoard(
    name='qick_board_zcu216',
    ns_host='192.168.1.XXX',  # PLACEHOLDER -- fill in the real ZCU216 IP
    ns_port=8000,              # confirm against how pyro_service.py was launched there
    proxy_name='rfsoc',        # confirm against how pyro_service.py was launched there
    board_model='zcu216',
    trigger_mode='hardware',
    parent_device=qick_trigger_intermediate,
    connection='port0/line0',
    tproc_program_module='labscriptlib.RFSoCLabscript.qick_programs_v2',
    tproc_program_class='HardwareTriggeredPulseProgramV2',
    tproc_program_kwargs={
        "res_ch": 0, "pulse_freq": 110, "pulse_gain": 1.0,
        "pulse_length_us": 1.0, "res_phase": 0, "reps": 1, "final_delay": 1.0,
    },
)

start()
# Same 5us trigger-pulse-width reasoning as the RFSoC4x2 example -- see that
# file's comment. Independent of the ZCU216's own 1us/110MHz output pulse.
qick_board_zcu216.start_tproc(t=1.0, duration=5e-6)
stop(2.0)
