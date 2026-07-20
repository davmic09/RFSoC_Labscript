"""tProc v2 programs, for a ZCU216 (or any tProc-v2-firmware) QICK board.

UNTESTED AGAINST REAL HARDWARE -- there is no ZCU216 available to validate
this against (unlike qick_programs.py's tProc v1 programs, which are verified
on a real RFSoC4x2). Written directly from amo_qick's own tProc v2 demo
(firmware/testbench/testbench_notebooks/test01_basic_multipulse.ipynb) and
qick_lib/qick/asm_v2.py's actual class signatures -- not guessed -- but the
whole point of "untested" is real hardware can still surprise you. Validate
standalone (make_proxy + prog.run(soc, start_src='internal')) against your
ZCU216 before wiring into labscript, exactly as was done for the v1 programs.

tProc v2's API is meaningfully different from v1 (qick_programs.py):
  - initialize()/body() are _initialize(cfg)/_body(cfg) (leading underscore).
  - add_pulse() takes physical units directly (MHz, us, degrees) -- no manual
    freq2reg()/us2cycles() conversion needed, unlike v1.
  - Pulses are named in _initialize(), then scheduled with self.pulse(ch=...,
    name=..., t=...) in _body() -- a two-step define-then-schedule model,
    rather than v1's single set_pulse_registers() + self.pulse() pair.
  - AveragerProgramV2.__init__() takes reps/final_delay as explicit
    constructor arguments, not packed inside cfg like v1's AveragerProgram.
    HardwareTriggeredPulseProgramV2 below wraps this so the outer
    (soccfg, cfg) signature matches what QICKBoardWorker already calls
    (cls(self.soccfg, props["tproc_program_kwargs"])) -- no worker changes
    needed to support v2 programs.
"""
from qick.asm_v2 import AveragerProgramV2


class HardwareTriggeredPulseProgramV2(AveragerProgramV2):
    """v2 analogue of qick_programs.HardwareTriggeredPulseProgram.

    Same physical intent: play one constant pulse immediately on start.
    Gating on the external hardware trigger (start_src='external', PMOD1 pin
    0 -- same pin on ZCU216 as on RFSoC4x2/ZCU111, per the .hwh hardware
    handoff files) happens at the tProc level via QICKBoard(trigger_mode=
    'hardware'), same as the v1 example -- nothing v2-specific about the
    trigger mechanism itself, only the pulse-programming API differs.
    """

    def __init__(self, soccfg, cfg):
        super().__init__(
            soccfg,
            reps=cfg.get("reps", 1),
            final_delay=cfg.get("final_delay", 1.0),
            cfg=cfg,
        )

    def _initialize(self, cfg):
        gen_ch = cfg["res_ch"]
        self.declare_gen(ch=gen_ch, nqz=1)
        self.add_pulse(
            ch=gen_ch, name="pulse", style="const",
            freq=cfg["pulse_freq"],           # MHz, direct -- no freq2reg()
            length=cfg["pulse_length_us"],     # us, direct -- no us2cycles()
            phase=cfg.get("res_phase", 0),     # degrees, direct
            gain=cfg["pulse_gain"],
        )

    def _body(self, cfg):
        self.pulse(ch=cfg["res_ch"], name="pulse", t=0)


HARDWARE_TRIGGER_CONFIG_V2 = {
    "res_ch": 0,
    "pulse_freq": 110,        # MHz
    "pulse_gain": 1.0,         # v2 gain is normalized float (0-1), not v1's raw DAC int
    "pulse_length_us": 1.0,    # microseconds
    "res_phase": 0,
    "reps": 1,
    "final_delay": 1.0,        # microseconds, wait after last rep before next
}
