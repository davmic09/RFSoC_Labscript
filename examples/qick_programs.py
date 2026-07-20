"""tProc programs for the RFSoC 4x2 QICK board (192.168.137.208).

These are plain QickProgram/AveragerProgram subclasses, independent of labscript --
they're loaded and run by the QICKBoard BLACS worker via
qick.pyro.make_proxy()-obtained soc/soccfg objects. See qick_lib/qick/qick_asm.py's
QickProgram.run() for how a program is loaded and started.
"""
from qick import AveragerProgram


class MinimalPulseProgram(AveragerProgram):
    """Fires a single constant pulse on one DAC channel.

    Minimal validation program: proves the RPC round-trip and hardware program
    execution work, before any labscript wiring is involved.
    """

    def initialize(self):
        cfg = self.cfg
        res_ch = cfg["res_ch"]

        self.declare_gen(ch=res_ch, nqz=1)
        for ch in cfg["ro_chs"]:
            self.declare_readout(
                ch=ch, length=cfg["readout_length"],
                freq=cfg["pulse_freq"], gen_ch=res_ch,
            )

        freq = self.freq2reg(cfg["pulse_freq"], gen_ch=res_ch, ro_ch=cfg["ro_chs"][0])
        phase = self.deg2reg(cfg["res_phase"], gen_ch=res_ch)
        gain = cfg["pulse_gain"]
        self.default_pulse_registers(ch=res_ch, freq=freq, phase=phase, gain=gain)
        self.set_pulse_registers(ch=res_ch, style="const", length=cfg["length"])

        self.synci(200)

    def body(self):
        self.measure(
            pulse_ch=self.cfg["res_ch"],
            adcs=self.ro_chs,
            pins=[0],
            adc_trig_offset=self.cfg["adc_trig_offset"],
            wait=True,
            syncdelay=self.us2cycles(self.cfg["relax_delay"]),
        )


DEFAULT_CONFIG = {
    "res_ch": 0,
    "ro_chs": [0],
    "reps": 1,
    "relax_delay": 1.0,
    "res_phase": 0,
    "length": 20,
    "readout_length": 100,
    "pulse_gain": 3000,
    "pulse_freq": 250,
    "adc_trig_offset": 100,
    "soft_avgs": 1,
}


class HardwareTriggeredPulseProgram(AveragerProgram):
    """Plays one constant pulse immediately on start.

    Meant to be run with QICKBoard(trigger_mode='hardware') -- the tProc's
    external-start gating (start_src='external', PMOD1 pin 0) is what makes
    this "triggered": the whole program, including this pulse, only begins
    once a real rising edge arrives on that pin. By the time body() executes,
    the trigger has already happened -- there is no separate in-program wait
    instruction, since tProc v1's external start is a whole-program gate, not
    a body-level branch.
    """

    def initialize(self):
        cfg = self.cfg
        res_ch = cfg["res_ch"]

        self.declare_gen(ch=res_ch, nqz=1)
        freq = self.freq2reg(cfg["pulse_freq"], gen_ch=res_ch)
        phase = self.deg2reg(cfg.get("res_phase", 0), gen_ch=res_ch)
        length = self.us2cycles(cfg["pulse_length_us"], gen_ch=res_ch)
        self.set_pulse_registers(
            ch=res_ch, style="const", freq=freq, phase=phase,
            gain=cfg["pulse_gain"], length=length,
        )

        self.synci(200)

    def body(self):
        self.pulse(ch=self.cfg["res_ch"])
        self.wait_all()


HARDWARE_TRIGGER_CONFIG = {
    "res_ch": 0,
    "pulse_freq": 110,        # MHz
    "pulse_gain": 3000,
    "pulse_length_us": 1.0,   # microseconds
    "res_phase": 0,
    "reps": 1,
}
