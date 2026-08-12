"""Stage E1 -- TDM frequency-comb hypothesis probe. Rapidly cycles GEN_CH=0
between two fixed tones (f_A, f_B) to test whether the pulse-boundary
"residual" (the same DDS transient characterized in boundary_capture.py)
synthesizes genuine simultaneous multi-tone spectral content at fast enough
switching, or whether the result is just textbook TDM (instantaneous carrier +
switching-frequency sidebands).

Dwell time = exactly one period of f_A (the lower of the two tones), used as
the dwell for BOTH pulses (same wall-clock duration each hop, not the same
cycle count -- f_B completes a non-integer number of its own cycles per hop,
which is fine/intentional). This is the fastest dwell that still completes at
least one full cycle of the slower tone, and ties the switching rate directly
to the tones themselves rather than an arbitrary fabric-cycle count.

Stays on plain "const"-style DDS pulses throughout (not a custom arb/envelope
waveform) -- frequency has to remain a live, register-cascadable parameter for
the eventual sweep (Stage C's mechanism), which a baked-in envelope waveform
would preclude. oneshot pulses (not "periodic" mode): periodic mode only
repeats a single waveform indefinitely until interrupted, it doesn't reduce
below one instruction per A<->B switch, so it has no benefit at a
fixed one-hop-per-instruction dwell like this.

RESULT (see FreqSweep_Analysis.ipynb "Stage E" section): NO-GO. The captured
spectrum is a real multi-line comb, but line spacing exactly matches the hop
repetition rate f_sw=1/cycle_us -- textbook TDM/amplitude-keying sidebands,
not a novel DDS-residual effect. Kept as the final result (tag
"period_noflush"); a flush=1 comparison and a slower dwell-bracket sweep were
also explored but not kept (flush actively erases the inter-segment
continuity the hypothesis depends on, so it isn't the right condition to test
it in). Fell back to stageD_multitone_acquire.py for the actual multitone
sweep.

Pure RF characterization -- no register cascade, no sweep, tones are fixed for
this stage.

HARDWARE SIDE ONLY -- acquire and save raw data; analysis happens off-board.

Run on the ZCU216 (needs root for QickSoc()):
    sudo BOARD=ZCU216 XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 stageE_comb_probe.py flush tag
"""
import os
os.environ.setdefault("BOARD", "ZCU216")
os.environ.setdefault("XILINX_XRT", "/usr")

import json
import sys
import numpy as np

from qick import QickSoc
from qick.asm_v2 import AveragerProgramV2

BITFILE = "/home/xilinx/jupyter_notebooks/amo_qick/tests/rf_board_firmware/d_1.bit"
GEN_CH = 0
RO_CH = 10
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
DECIMATED_FS_MHZ = 307.2
FABRIC_MHZ = 599.04             # GEN_CH=0 fabric clock
DUMMY_LEN_US = 3 / FABRIC_MHZ    # dummypulse is a fixed 3-fabric-cycle pulse

# widely-separated test tones -- checked no low-order intermod product
# (f_A+f_B=180, |f_A-f_B|=40, 2f_A-f_B=30, 2f_B-f_A=150) lands near f_A/f_B.
# NOTE: an initial 100/140MHz pair was tried and rejected -- 140MHz is 91% of
# the decimated readout's Nyquist (307.2/2=153.6MHz) and got hit with severe
# decimation-filter rolloff (~25x attenuated vs 100MHz in a calibration-bracket
# check), unrelated to the comb hypothesis. 70/110MHz sits comfortably in the
# flat passband (same ballpark as the well-characterized ~110MHz Stage A/C
# tones) while keeping a wide 40MHz separation.
F_A_MHZ = 70.0
F_B_MHZ = 110.0

N_WARMUP = 8         # uncaptured hops before the trigger, to let cold-start settle
MAX_DECIMATED_SAMPLES = 3800   # safety margin under acquire_decimated's confirmed
                                # 4096-sample buffer cap (hit this directly on hardware:
                                # "requested readout length x trigs x reps exceeds
                                # buffer size (4096)")


class CombProbeProgram(AveragerProgramV2):
    """No hardware loop -- fully Python-unrolled (matches boundary_capture.py's
    proven single-trigger-after-multiple-pulses pattern). A hardware add_loop
    was tried first with one trigger() issued before it, but acquire_decimated's
    buffer-size check multiplies the declared readout length by the loop's
    repeat count regardless of how many explicit trigger() calls exist in the
    program, so that didn't work. Unrolling is cheap here anyway: each
    pre-declared pulse compiles to a single WPORT_WR instruction (confirmed via
    ASM dump), so even hundreds of hops use a small fraction of the 4096-word
    program memory -- the real constraint is the decimated sample cap, not
    instruction count.
    """
    def _initialize(self, cfg):
        gen_ch = cfg['gen_ch']
        ro_ch = cfg['ro_ch']
        dwell_us = cfg['dwell_us']

        self.declare_gen(ch=gen_ch, nqz=1, mixer_freq=cfg['mixer_freq'], ro_ch=ro_ch)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])
        self.add_pulse(ch=gen_ch, name="pulseA", ro_ch=ro_ch, style="const",
                       freq=cfg['f_a'], length=dwell_us, phase=0, gain=cfg['gain'])
        self.add_pulse(ch=gen_ch, name="pulseB", ro_ch=ro_ch, style="const",
                       freq=cfg['f_b'], length=dwell_us, phase=0, gain=cfg['gain'])
        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['ro_freq'], gen_ch=gen_ch, phase=0)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)

    def _body(self, cfg):
        gen_ch = cfg['gen_ch']
        ro_ch = cfg['ro_ch']
        dwell_us = cfg['dwell_us']

        # uncaptured warm-up hops (separates cold-start settling from steady-state)
        t = 0.0
        for _ in range(cfg['n_warmup']):
            self.pulse(ch=gen_ch, name="pulseA", t=t)
            t += dwell_us
            if cfg['flush']:
                self.pulse(ch=gen_ch, name="dummypulse", t=t)
                t += DUMMY_LEN_US
            self.pulse(ch=gen_ch, name="pulseB", t=t)
            t += dwell_us
            if cfg['flush']:
                self.pulse(ch=gen_ch, name="dummypulse", t=t)
                t += DUMMY_LEN_US

        # single continuous trigger spanning every captured hop below
        self.trigger(ros=[ro_ch], pins=[0], t=t)

        for _ in range(cfg['n_repeats']):
            self.pulse(ch=gen_ch, name="pulseA", t=t)
            t += dwell_us
            if cfg['flush']:
                self.pulse(ch=gen_ch, name="dummypulse", t=t)
                t += DUMMY_LEN_US
            self.pulse(ch=gen_ch, name="pulseB", t=t)
            t += dwell_us
            if cfg['flush']:
                self.pulse(ch=gen_ch, name="dummypulse", t=t)
                t += DUMMY_LEN_US


def main():
    flush = bool(int(sys.argv[1])) if len(sys.argv) > 1 else False
    tag = sys.argv[2] if len(sys.argv) > 2 else f"period_f{int(flush)}"
    print(f"flush={flush}, tag={tag!r}")

    dwell_us = 1.0 / F_A_MHZ   # exactly one period of f_A (the lower tone)
    dwell_cycles = dwell_us * FABRIC_MHZ
    cycle_us = 2 * dwell_us + (2 * DUMMY_LEN_US if flush else 0)
    # as many repeats as fit under the confirmed 4096-decimated-sample buffer
    # cap (empirically hit directly on hardware -- see class docstring)
    n_repeats = max(4, int(MAX_DECIMATED_SAMPLES / (cycle_us * DECIMATED_FS_MHZ)))
    ro_len_us = n_repeats * cycle_us
    print(f"dwell_us={dwell_us:.6f}, cycle_us={cycle_us:.6f}, n_repeats={n_repeats}, "
          f"ro_len_us={ro_len_us:.4f} (~{ro_len_us*DECIMATED_FS_MHZ:.0f} decimated samples)")

    print("Instantiating QickSoc() with d_1.bit...")
    soc = QickSoc(bitfile=BITFILE)
    soccfg = soc

    config = {
        'gen_ch': GEN_CH, 'ro_ch': RO_CH, 'mixer_freq': 100,
        'f_a': F_A_MHZ, 'f_b': F_B_MHZ, 'dwell_us': dwell_us,
        'flush': flush, 'n_warmup': N_WARMUP, 'n_repeats': n_repeats,
        'ro_freq': 0, 'ro_len': ro_len_us, 'gain': 1.0,
    }

    prog = CombProbeProgram(soccfg, reps=1, final_delay=0.0, cfg=config)
    print(prog)

    iq_list = prog.acquire_decimated(soc, progress=True)
    iq = np.asarray(iq_list[0])
    if iq.ndim == 3:
        iq = iq[0]
    print("acquire_decimated returned shape:", iq.shape)   # (n_samples, 2)

    I_arr = iq[:, 0].astype(float)
    Q_arr = iq[:, 1].astype(float)
    n_samples = len(I_arr)

    suffix = f"_{tag}" if tag else ""
    sample_idx = np.arange(n_samples)
    out_csv = os.path.join(OUT_DIR, f"comb_raw_iq{suffix}.csv")
    np.savetxt(out_csv, np.column_stack([sample_idx, I_arr, Q_arr]),
               delimiter=",", header="sample_idx,I,Q", comments="")
    print(f"[OK] Saved raw I/Q to {out_csv} ({n_samples} samples)")

    meta = {
        "decimated_fs_mhz": DECIMATED_FS_MHZ, "n_samples": n_samples,
        "f_a_mhz": F_A_MHZ, "f_b_mhz": F_B_MHZ, "dwell_cycles": dwell_cycles,
        "dwell_us": dwell_us, "cycle_us": cycle_us, "flush": flush,
        "n_warmup": N_WARMUP, "n_repeats": n_repeats, "ro_len_us": ro_len_us,
        "fabric_mhz": FABRIC_MHZ, "gen_ch": GEN_CH, "ro_ch": RO_CH, "bitfile": BITFILE,
    }
    meta_path = os.path.join(OUT_DIR, f"comb_meta{suffix}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Saved metadata to {meta_path}")
    print("[OK] Done -- analyze comb_raw_iq.csv + comb_meta.json off-board.")


if __name__ == "__main__":
    main()
