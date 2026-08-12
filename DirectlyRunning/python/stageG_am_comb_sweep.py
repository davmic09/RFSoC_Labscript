"""Stage G -- UNTESTED, NEVER RUN ON HARDWARE. Low-jitter 8-tone SIMULTANEOUS
comb via engineered amplitude modulation, swept as a whole by cascading a
single carrier-frequency register -- Stage C's exact register-cascade
mechanism, applied to a custom "arb" envelope instead of a plain "const"
pulse.

THE IDEA (validated by pure-math simulation, not hardware, before writing any
of this -- see DirectlyRunning/images/engineered_am_comb_check.png):
Stage D produces the 8 tones by rapidly time-multiplexing one carrier --
genuinely sequential, not simultaneous, and the switching itself creates
sideband artifacts (Stage E). This does something different: keep the DDS
carrier at a FIXED center frequency, and multiply it by a custom GAIN
ENVELOPE built from exactly 4 cosines (at 0.5, 1.5, 2.5, 3.5 MHz). Real
amplitude modulation of a real carrier produces both upper AND lower
sidebands for each modulation frequency, so a carrier at 109.5MHz modulated
this way produces sidebands at 109.5 +/- {0.5,1.5,2.5,3.5} = exactly
106,107,108,109,110,111,112,113 MHz -- all 8 target tones, genuinely
SIMULTANEOUS (one instant of the waveform contains all 8), by direct
construction rather than as a byproduct of switching. Simulated spectrum:
target lines ~8000x above anything else in the band (~78dB) -- dramatically
cleaner than any switching-based scheme tried this session.

Sweeping the whole comb by 1MHz is then just sweeping the CENTER frequency
register by 1MHz -- the exact same read_wmem/inc_reg('w_freq',...)/write_wmem
cascade as Stage C, since the envelope (which encodes the fixed relative
spacing) never needs to change, only the carrier. Register budget is trivial
(d1,d2,d3 -- the same 3 registers as Stage C, nowhere near Stage D's 11).

WHAT THIS SCRIPT HAS NOT VERIFIED -- check all of these before trusting it:

1. add_envelope() exact signature/units. This script assumes:
   `prog.add_envelope(ch=gen_ch, name=..., idata=<int16 array>, qdata=<int16
   array>)`, with idata/qdata scaled to the generator's MAXV (32766 for
   gen0), and envelope length required to be a multiple of gen0's
   samps_per_clk (16, confirmed from the printed board config this session --
   "envelope memory: 65536 complex samples" / "samps_per_clk=16" for
   axis_signal_gen_v6). This is standard QICK v2 API from general knowledge,
   NOT re-confirmed against this specific board's qick_asm.py source this
   session (no hardware access) -- read qick_asm.py's add_envelope docstring
   first if this errors.
2. Whether the read_wmem/inc_reg/write_wmem register-cascade mechanism
   (proven for "const"-style pulses in Stage C) works identically for
   "arb"-style pulses. The Waveform structure (freq/phase/env/gain/length/
   conf) should be style-agnostic based on every ASM dump seen this session,
   so this is a reasonable bet, but genuinely unverified -- inspect
   `print(prog)`'s ASM dump before trusting acquire_decimated, same habit
   that caught real bugs in Stage D before it ever ran.
3. trig_time / pipeline transient behavior for arb-style pulses. The
   ~0.4-0.65us transient characterized in boundary_capture.py was measured
   for "const"-style pulses only -- an amplitude-modulated envelope might
   settle differently. This script guesses trig_time=0.7us as a starting
   point; re-derive properly (e.g. a boundary_capture.py-style diagnostic
   adapted to this pulse type) before trusting results close to the edges.
4. Whether qdata=0 (real-only envelope) is the right call for gen0's
   complex_env=True architecture, or whether some other I/Q convention is
   actually expected. The simulation validates the MATH (real AM modulation
   of a real carrier gives symmetric real sidebands) but not how this maps
   onto the specific complex-envelope hardware pipeline.

HARDWARE SIDE ONLY (once actually run) -- acquire and save raw data; analysis
happens off-board, same pattern as every other stage.

Run on the ZCU216 (needs root for QickSoc()):
    sudo BOARD=ZCU216 XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 stageG_am_comb_sweep.py [tag]
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
DAC_FS_MHZ = 9584.64      # gen0's real DAC sample rate -- the envelope table rate
SAMPS_PER_CLK = 16          # gen0's envelope-length granularity (UNVERIFIED, see docstring)

F_CENTER_MHZ = 109.5        # carrier center -- sweeps to 110.5 over the run (comb: 107-114)
MOD_OFFSETS_MHZ = [0.5, 1.5, 2.5, 3.5]   # -> 8 sidebands at center +/- these
SPAN_MHZ = 1.0               # total sweep span of the CENTER (whole comb shifts together)
N_STEPS = 50                  # -> 50 * ~2us = 100us total, matching the original goal
TRIG_TIME_US = 0.7            # UNVERIFIED GUESS -- see docstring point 3
GAIN = 1.0


def build_envelope(dac_fs_mhz, mod_offsets_mhz, samps_per_clk, maxv):
    """Exactly the 4 needed cosines, nothing else -- validated by pure-math
    simulation (see module docstring) to give ~78dB-clean sidebands. Rounds
    the envelope length to a multiple of samps_per_clk, then RE-DERIVES the
    modulation frequencies as exact harmonics of the resulting discretized
    period (odd harmonics 1x,3x,5x,7x of the fundamental) so the table is
    perfectly periodic with no wraparound discontinuity -- avoids the tiny
    frequency error from naively rounding sample count at fixed frequencies.
    """
    t_mod_us_nominal = 1.0 / mod_offsets_mhz[0]   # 1/0.5MHz = 2us
    n_env = int(round(t_mod_us_nominal * dac_fs_mhz / samps_per_clk) * samps_per_clk)
    fundamental_mhz = dac_fs_mhz / n_env
    harmonics = [fundamental_mhz * (2 * k + 1) for k in range(len(mod_offsets_mhz))]  # 1x,3x,5x,7x
    t_env = np.arange(n_env) / dac_fs_mhz
    m = sum(np.cos(2 * np.pi * f * t_env) for f in harmonics)
    m = m / np.max(np.abs(m))
    idata = np.round(m * maxv).astype(np.int16)
    qdata = np.zeros(n_env, dtype=np.int16)
    t_mod_us_actual = n_env / dac_fs_mhz
    print(f"[env] n_env={n_env}, t_mod_us={t_mod_us_actual:.6f} (nominal {t_mod_us_nominal}), "
          f"harmonics={harmonics}")
    return idata, qdata, t_mod_us_actual


class AmCombProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        gen_ch = cfg['gen_ch']
        ro_ch = cfg['ro_ch']
        deltas0 = cfg['deltas0']

        self.declare_gen(ch=gen_ch, nqz=1, mixer_freq=cfg['mixer_freq'], ro_ch=ro_ch)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])

        # UNVERIFIED API -- see module docstring point 1
        self.add_envelope(ch=gen_ch, name="combenv", idata=cfg['idata'], qdata=cfg['qdata'])
        self.add_pulse(ch=gen_ch, name="combpulse", ro_ch=ro_ch, style="arb",
                       envelope="combenv", freq=cfg['f0_mhz'], length=cfg['t_mod_us'],
                       phase=0, gain=cfg['gain'])

        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['ro_freq'], gen_ch=gen_ch, phase=0)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)

        for k in range(1, 4):
            self.add_reg(name=f'd{k}', init=QickParam(deltas0[k]))

        self.add_loop("comb_loop", cfg['n_steps'], exec_before=None, exec_after=None)

    def _body(self, cfg):
        self.pulse(ch=cfg['gen_ch'], name="combpulse", t=0)
        self.trigger(ros=[cfg['ro_ch']], pins=[0], t=cfg['trig_time'])
        # zero-gain flush -- same fix as every other stage, positioned after
        # the full modulation-period pulse ends
        self.pulse(ch=cfg['gen_ch'], name="dummypulse", t="auto")
        # same cascade recurrence as Stage C, applied to the CENTER frequency
        # only -- the envelope (hence relative tone spacing) never changes
        self.read_wmem("combpulse_w0")
        order = cfg.get('cascade_order', 3)
        self.inc_reg('w_freq', 'd1')
        if order >= 2:
            self.inc_reg('d1', 'd2')
        if order >= 3:
            self.inc_reg('d2', 'd3')
        self.write_wmem("combpulse_w0")


def smoothstep_deltas(soc, gen_ch, f0, f1, n):
    """Same cascade math as Stage C -- cascade_order=3 is exact for this
    cubic trajectory (see FreqSweep_Analysis.ipynb's derivation)."""
    t = np.linspace(0, 1, n)
    S = 3 * t**2 - 2 * t**3
    f_mhz = f0 + (f1 - f0) * S
    codes = np.array([soc.freq2reg(f, gen_ch=gen_ch) for f in f_mhz], dtype=np.int64)
    diffs = [codes]
    for _ in range(3):
        diffs.append(np.diff(diffs[-1]))
    deltas0 = [int(d[0]) for d in diffs]
    print(f"[traj] f_mhz[0]={f_mhz[0]:.6f} f_mhz[-1]={f_mhz[-1]:.6f} deltas0={deltas0}")
    return f_mhz, deltas0


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    print(f"tag={tag!r}")

    print("Instantiating QickSoc() with d_1.bit...")
    soc = QickSoc(bitfile=BITFILE)
    soccfg = soc

    maxv = 32766   # gen0's MAXV, confirmed from earlier ASM dumps this session
    idata, qdata, t_mod_us = build_envelope(DAC_FS_MHZ, MOD_OFFSETS_MHZ, SAMPS_PER_CLK, maxv)

    f_mhz_traj, deltas0 = smoothstep_deltas(soc, GEN_CH, F_CENTER_MHZ, F_CENTER_MHZ + SPAN_MHZ, N_STEPS)

    config = {
        'gen_ch': GEN_CH, 'ro_ch': RO_CH, 'mixer_freq': 100,
        'f0_mhz': F_CENTER_MHZ, 'deltas0': deltas0, 'cascade_order': 3,
        'idata': idata, 'qdata': qdata, 't_mod_us': t_mod_us,
        'ro_freq': 0, 'ro_len': min(t_mod_us - 0.1, 1.9), 'trig_time': TRIG_TIME_US,
        'gain': GAIN, 'n_steps': N_STEPS,
    }

    prog = AmCombProgram(soccfg, reps=1, final_delay=0.0, cfg=config)
    print(prog)   # inspect ASM before trusting acquire_decimated -- confirm the
                   # w_freq cascade actually targets the arb pulse's freq register
                   # the same way it did for Stage C's const pulse

    iq_list = prog.acquire_decimated(soc, progress=True)
    iq = np.asarray(iq_list[0])
    print("acquire_decimated returned shape:", iq.shape)   # expect (n_steps, n_samples, 2)

    I_seg = iq[:, :, 0].astype(float)
    Q_seg = iq[:, :, 1].astype(float)
    n_loop_actual, n_samples = I_seg.shape

    loop_idx = np.repeat(np.arange(n_loop_actual), n_samples)
    sample_idx = np.tile(np.arange(n_samples), n_loop_actual)
    suffix = f"_{tag}" if tag else ""
    out_csv = os.path.join(OUT_DIR, f"amcomb_raw_iq{suffix}.csv")
    np.savetxt(out_csv, np.column_stack([loop_idx, sample_idx, I_seg.ravel(), Q_seg.ravel()]),
               delimiter=",", header="loop_iter,sample_idx,I,Q", comments="")
    print(f"[OK] Saved raw I/Q to {out_csv} ({n_loop_actual} loops x {n_samples} samples/loop)")

    target_tones_mhz = [F_CENTER_MHZ + s for s in MOD_OFFSETS_MHZ] + [F_CENTER_MHZ - s for s in MOD_OFFSETS_MHZ]
    meta = {
        "decimated_fs_mhz": DECIMATED_FS_MHZ, "n_loop": n_loop_actual, "n_samples_per_seg": n_samples,
        "f_center_mhz": F_CENTER_MHZ, "mod_offsets_mhz": MOD_OFFSETS_MHZ,
        "target_tones_mhz": sorted(target_tones_mhz), "span_mhz": SPAN_MHZ, "t_mod_us": t_mod_us,
        "trig_time_us": TRIG_TIME_US, "gen_ch": GEN_CH, "ro_ch": RO_CH, "bitfile": BITFILE,
        "intended_center_f_mhz": f_mhz_traj.tolist(), "UNTESTED": True,
    }
    meta_path = os.path.join(OUT_DIR, f"amcomb_meta{suffix}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Saved metadata to {meta_path}")
    print("[OK] Done -- analyze amcomb_raw_iq.csv + amcomb_meta.json off-board.")


if __name__ == "__main__":
    main()
