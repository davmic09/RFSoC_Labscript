"""Stage D -- low-jitter multitone sweep, time-multiplexed on the single-tone
generator (GEN_CH=0). 8 tones (106,107,...,113 MHz) each sweep up by 1MHz
(smoothstep, same technique as Stage C) over the same N_STEPS iterations, one
tone played at a time per iteration in round-robin.

Why time-multiplexed instead of the real 8-tone mux generator (GEN_CH=4,
axis_sg_mixmux8_v1): confirmed from the actual hardware register maps that the
mux generator's per-tone frequency registers (pinc0-7_reg) are AXI4-Lite
MMIO registers, host (PYNQ/PS) writable only -- structurally separate from the
s_axis stream tProc uses to drive pulses (which, for the mux generator, only
ever carries a tone-selection mask + length, never frequency -- confirmed via
MultiplexedGenManager.params2wave() in asm_v2.py always sending freq=0). There
is no tProc instruction path to update those registers mid-program, so no way
to get FPGA-cycle low jitter out of the real mux generator. GEN_CH=0's
frequency, by contrast, genuinely is part of the tProc-streamed waveform data
(that's why Stage C's read_wmem/inc_reg/write_wmem cascade worked at all).

Also considered: rapidly cycling GEN_CH=0 between the 8 target frequencies to
synthesize a simultaneous comb via the pulse-boundary "residual" (Stage E).
Tested and ruled out -- the resulting spectrum was textbook TDM/switching
sidebands (spacing = hop rate), not a novel effect, so it doesn't give a
clean "sweep one shared register, comb rides along" handle. This
sequential/time-multiplexed approach is the one that actually works.

Register budget: tProc has dreg_qty=16 data registers total. All 8 tones
share the identical 1MHz-span smoothstep, so their finite-difference deltas
are identical to well beyond measurement precision (freq2reg quantization
noise is sub-Hz-scale) -- one shared cascade (d1,d2,d3 -- cascade_order=3,
exact for this cubic, per Stage C's finding) applied to 8 independent
per-tone current-frequency registers: 8 + 3 = 11 registers, plus reps/loop
counters -- comfortably under 16.

This design was drafted (register budget worked out, math validated) before
Stage E's TDM-comb detour, and caught two issues on review before ever running
on hardware: (1) each tone's pulse()/trigger() calls originally used a fixed
t=0/t=trig_time repeated per tone, which would schedule all 8 tones'
pulses to start simultaneously on the same physical generator -- fixed with
explicit cumulative time tracking, offsetting each tone by the previous
ones' flat_len (Stage A/C only ever issue one pulse per _body call, so this
never came up there). (2) added the zero-gain dummypulse flush between tones
(same fix validated for Stage A/C's boundary transient).

HARDWARE SIDE ONLY -- acquire and save raw data; analysis happens off-board.

Run on the ZCU216 (needs root for QickSoc()):
    sudo BOARD=ZCU216 XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 stageD_multitone_acquire.py [tag]
"""
import os
os.environ.setdefault("BOARD", "ZCU216")
os.environ.setdefault("XILINX_XRT", "/usr")

import json
import sys
import numpy as np

from qick import QickSoc
from qick.asm_v2 import AveragerProgramV2, QickParam

BITFILE = "/home/xilinx/jupyter_notebooks/amo_qick/tests/rf_board_firmware/d_1.bit"
GEN_CH = 0
RO_CH = 10
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
DECIMATED_FS_MHZ = 307.2
FABRIC_MHZ = 599.04
DUMMY_LEN_US = 3 / FABRIC_MHZ    # dummypulse flush -- see stageA2/stageC's fix

TONE_STARTS_MHZ = [106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0, 113.0]
SPAN_MHZ = 1.0          # each tone sweeps up by this much
N_TONES = len(TONE_STARTS_MHZ)
N_STEPS = 20             # segments -> 20 * (8*0.85us) = 136us total
SEG_LEN_US = 0.85        # per-tone-segment flat_len
RO_LEN_US = 0.08         # -> ~25 samples/tone-segment; 8*20*25=4000 < 4096 decimated cap
TRIG_TIME_US = 0.65      # same pipeline-transient fix as Stages A/C


def smoothstep_shared_deltas(soc, gen_ch, span_mhz, n):
    """Shared cascade deltas (cascade_order=3, exact for this cubic per Stage
    C) computed once from a representative trajectory -- valid for every tone
    since only the SPAN and N_STEPS determine the finite-difference shape;
    the absolute starting frequency only shifts freq2reg's quantization noise
    by a sub-Hz amount, negligible next to the ~90kHz systematic offset
    already characterized in Stage A/C."""
    t = np.linspace(0, 1, n)
    S = 3 * t**2 - 2 * t**3
    f_mhz = span_mhz * S   # 0 -> span_mhz, representative shape
    codes = np.array([soc.freq2reg(f, gen_ch=gen_ch) for f in f_mhz], dtype=np.int64)
    diffs = [codes]
    for _ in range(3):
        diffs.append(np.diff(diffs[-1]))
    deltas0 = [int(d[0]) for d in diffs]  # [0-code, d1[0], d2[0], d3[0]]
    print(f"[traj] shared deltas0={deltas0}")
    return f_mhz, deltas0


class MultitoneProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        gen_ch = cfg['gen_ch']
        ro_ch = cfg['ro_ch']
        tone_codes0 = cfg['tone_codes0']
        deltas0 = cfg['deltas0']   # [_, d1, d2, d3]

        self.declare_gen(ch=gen_ch, nqz=1, mixer_freq=cfg['mixer_freq'], ro_ch=ro_ch)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])
        self.add_pulse(ch=gen_ch, name="mypulse", ro_ch=ro_ch, style="const",
                       freq=cfg['f0_mhz_tone0'], length=cfg['flat_len'], phase=0, gain=cfg['gain'])
        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['ro_freq'], gen_ch=gen_ch, phase=0)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)

        for k in range(cfg['n_tones']):
            self.add_reg(name=f'tf{k}', init=QickParam(tone_codes0[k]))
        self.add_reg(name='d1', init=QickParam(deltas0[1]))
        self.add_reg(name='d2', init=QickParam(deltas0[2]))
        self.add_reg(name='d3', init=QickParam(deltas0[3]))

        self.add_loop("step_loop", cfg['n_steps'], exec_before=None, exec_after=None)

    def _body(self, cfg):
        n_tones = cfg['n_tones']
        # explicit cumulative time, not repeated t=0/t=trig_time per tone --
        # each tone's pulse+trigger+flush must be offset from the previous
        # tone's, since it's all one physical generator playing back to back
        # within a single _body call (unlike Stage A/C, which only ever issue
        # one pulse per _body call and can just use t=0 relative to the loop
        # iteration's own start).
        t = 0.0
        for k in range(n_tones):
            self.read_wmem("mypulse_w0")
            self.write_reg('w_freq', f'tf{k}')
            self.write_wmem("mypulse_w0")
            self.pulse(ch=cfg['gen_ch'], name="mypulse", t=t)
            self.trigger(ros=[cfg['ro_ch']], pins=[0], t=t + cfg['trig_time'])
            # zero-gain flush -- same boundary-cleanup fix as Stage A/C
            self.pulse(ch=cfg['gen_ch'], name="dummypulse", t=t + cfg['flat_len'])
            t += cfg['flat_len'] + DUMMY_LEN_US
        # advance all 8 tones by the (still-old) shared d1, then cascade the
        # shared deltas once -- ascending order, same recurrence as Stage C
        for k in range(n_tones):
            self.inc_reg(f'tf{k}', 'd1')
        self.inc_reg('d1', 'd2')
        self.inc_reg('d2', 'd3')


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    print(f"tag={tag!r}")

    print("Instantiating QickSoc() with d_1.bit...")
    soc = QickSoc(bitfile=BITFILE)
    soccfg = soc

    _, deltas0 = smoothstep_shared_deltas(soc, GEN_CH, SPAN_MHZ, N_STEPS)
    tone_codes0 = [int(soc.freq2reg(f, gen_ch=GEN_CH)) for f in TONE_STARTS_MHZ]
    print(f"[traj] tone_codes0={tone_codes0}")

    # intended per-tone, per-step frequency trajectory (for later comparison)
    t = np.linspace(0, 1, N_STEPS)
    S = 3 * t**2 - 2 * t**3
    intended_f_mhz = np.array([[f0 + SPAN_MHZ * s for s in S] for f0 in TONE_STARTS_MHZ])  # (n_tones, n_steps)

    config = {
        'gen_ch': GEN_CH, 'ro_ch': RO_CH, 'mixer_freq': 100,
        'f0_mhz_tone0': TONE_STARTS_MHZ[0], 'tone_codes0': tone_codes0, 'deltas0': deltas0,
        'n_tones': N_TONES, 'n_steps': N_STEPS,
        'ro_freq': 0, 'ro_len': RO_LEN_US, 'flat_len': SEG_LEN_US,
        'trig_time': TRIG_TIME_US, 'gain': 1.0,
    }

    prog = MultitoneProgram(soccfg, reps=1, final_delay=0.0, cfg=config)
    print(prog)

    iq_list = prog.acquire_decimated(soc, progress=True)
    iq = np.asarray(iq_list[0])
    print("acquire_decimated returned shape:", iq.shape)   # (n_steps, n_tones, n_samples, 2) --
    # acquire_decimated already groups by (loop iterations, trigs per iteration), so no
    # manual reshape needed: 8 self.trigger() calls per step_loop iteration -> the "8" (tones)
    # dimension comes out automatically, not from a flat (n_steps*n_tones, ...) shape.

    n_samples = iq.shape[2]
    I_arr = iq[:, :, :, 0].astype(float)   # (n_steps, n_tones, n_samples)
    Q_arr = iq[:, :, :, 1].astype(float)

    step_idx = np.repeat(np.arange(N_STEPS), N_TONES * n_samples)
    tone_idx = np.tile(np.repeat(np.arange(N_TONES), n_samples), N_STEPS)
    sample_idx = np.tile(np.arange(n_samples), N_STEPS * N_TONES)
    suffix = f"_{tag}" if tag else ""
    out_csv = os.path.join(OUT_DIR, f"multitone_raw_iq{suffix}.csv")
    np.savetxt(out_csv,
               np.column_stack([step_idx, tone_idx, sample_idx, I_arr.ravel(), Q_arr.ravel()]),
               delimiter=",", header="step_idx,tone_idx,sample_idx,I,Q", comments="")
    print(f"[OK] Saved raw I/Q to {out_csv} ({N_STEPS} steps x {N_TONES} tones x {n_samples} samples)")

    meta = {
        "decimated_fs_mhz": DECIMATED_FS_MHZ, "n_steps": N_STEPS, "n_tones": N_TONES,
        "n_samples_per_seg": n_samples, "tone_starts_mhz": TONE_STARTS_MHZ, "span_mhz": SPAN_MHZ,
        "seg_len_us": SEG_LEN_US, "ro_len_us": RO_LEN_US, "trig_time_us": TRIG_TIME_US,
        "gen_ch": GEN_CH, "ro_ch": RO_CH, "bitfile": BITFILE,
        "intended_f_mhz": intended_f_mhz.tolist(),   # (n_tones, n_steps)
        "dummypulse_flush": True,
    }
    meta_path = os.path.join(OUT_DIR, f"multitone_meta{suffix}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Saved metadata to {meta_path}")
    print("[OK] Done -- analyze multitone_raw_iq.csv + multitone_meta.json off-board.")


if __name__ == "__main__":
    main()
