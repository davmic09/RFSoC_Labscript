"""Stage C -- the actual "low jitter" continuous chirp: a cascading Newton
forward-difference register update (the same DDA technique as the original v1
attempt) issued via v2's raw register API (add_reg/inc_reg on 'w_freq', the
same underlying mechanism QickSweep1D itself uses -- just generalized from a
constant per-step increment to a cascading, smoothly-varying one).

HARDWARE SIDE ONLY -- acquire and save raw data; analysis happens off-board.

Run on the ZCU216 (needs root for QickSoc()):
    sudo BOARD=ZCU216 XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 stageC_chirp_acquire.py [cascade_order] [tag]
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

F0_MHZ = 109.0
F1_MHZ = 111.0
N_LOOP = 100          # segments -> 100 * 1.0us = 100us total, matching the original goal
SEG_LEN_US = 1.0       # flat_len per segment
RO_LEN_US = 0.13       # -> ~40 samples/segment; small capture window per segment
TRIG_TIME_US = 0.65    # proven fix from Stage A: avoids the ~0.4-0.65us pipeline
                       # startup transient landing inside the capture window


def smoothstep_trajectory(soc, gen_ch, f0, f1, n):
    """Classic cubic smoothstep S(t)=3t^2-2t^3 (S(0)=0,S(1)=1,S'(0)=S'(1)=0).
    NOT the higher-order (quartic-leading) version from the original v1
    attempt -- that one's finite differences underflowed to exactly zero once
    the segment grid got fine enough (confirmed there), permanently freezing
    the sweep. This quadratic-leading version keeps d1[0] safely nonzero at
    any practical n."""
    t = np.linspace(0, 1, n)
    S = 3 * t**2 - 2 * t**3
    f_mhz = f0 + (f1 - f0) * S
    codes = np.array([soc.freq2reg(f, gen_ch=gen_ch) for f in f_mhz], dtype=np.int64)
    diffs = [codes]
    for _ in range(6):
        diffs.append(np.diff(diffs[-1]))
    deltas0 = [int(d[0]) for d in diffs]  # [f0_code, d1[0], d2[0], ..., d6[0]]
    print(f"[traj] f_mhz[0]={f_mhz[0]:.6f} f_mhz[-1]={f_mhz[-1]:.6f} "
          f"code[0]={codes[0]} code[-1]={codes[-1]}")
    print(f"[traj] deltas0={deltas0}")
    return f_mhz, deltas0


class ChirpProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        gen_ch = cfg['gen_ch']
        ro_ch = cfg['ro_ch']
        deltas0 = cfg['deltas0']

        self.declare_gen(ch=gen_ch, nqz=1, mixer_freq=cfg['mixer_freq'], ro_ch=ro_ch)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])
        self.add_pulse(ch=gen_ch, name="mypulse", ro_ch=ro_ch,
                       style="const",
                       freq=cfg['f0_mhz'],   # plain starting frequency, not a QickSweep1D
                       length=cfg['flat_len'],
                       phase=0,
                       gain=cfg['gain'],
                      )
        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['ro_freq'], gen_ch=gen_ch, phase=0)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)

        # 6 delta registers, raw register-code units (add_reg's init QickParam
        # is written verbatim, no unit conversion, for a generic register --
        # confirmed by reading asm_v2.py: WriteReg(dst=k, src=v.init.start)).
        for k in range(1, 7):
            self.add_reg(name=f'd{k}', init=QickParam(deltas0[k]))

        self.add_loop("chirp_loop", cfg['n_loop'], exec_before=None, exec_after=None)

    def _body(self, cfg):
        self.pulse(ch=cfg['gen_ch'], name="mypulse", t=0)
        self.trigger(ros=[cfg['ro_ch']], pins=[0], t=cfg['trig_time'])
        # Zero-gain "dummypulse" right after mypulse ends -- same boundary-cleanup
        # fix as Stage A's stageA2_acquire_only.py (see that file's _body for the
        # full rationale). Doesn't touch mypulse's own waveform memory (it plays
        # from a separate "dummy" slot), so it's independent of the register
        # cascade below.
        self.pulse(ch=cfg['gen_ch'], name="dummypulse", t="auto")
        # Cascading Newton forward-difference update, ascending order (freq
        # first using the OLD d1, then d1 using the OLD d2, ...) -- each step
        # reads a register that hasn't been touched yet this iteration, so old
        # values are used throughout, matching the correct recurrence.
        # NOTE: pulse() replays from the waveform's stored *memory* config, not
        # directly from the live w0-w5 registers -- confirmed by the Stage A
        # ASM dump, which follows its own w0 update with a WMEM_WR instruction.
        # Without write_wmem, every pulse() call kept replaying the original
        # unmodified waveform (first hardware run: chirp stuck at one
        # frequency for all 100 segments). Without read_wmem FIRST, the w0-w5
        # scratch registers aren't guaranteed to hold this waveform's current
        # phase/gain/etc, so writing them back clobbered the whole waveform
        # with stale/uninitialized values (second run: signal amplitude
        # collapsed to near-noise, frequencies came out essentially random).
        self.read_wmem("mypulse_w0")
        order = cfg.get('cascade_order', 3)
        self.inc_reg('w_freq', 'd1')
        if order >= 2:
            self.inc_reg('d1', 'd2')
        if order >= 3:
            self.inc_reg('d2', 'd3')
        if order >= 4:
            self.inc_reg('d3', 'd4')
        if order >= 5:
            self.inc_reg('d4', 'd5')
        if order >= 6:
            self.inc_reg('d5', 'd6')
        self.write_wmem("mypulse_w0")


def main():
    # cascade_order=3 is the mathematically exact order for this trajectory:
    # the smoothstep S(t)=3t^2-2t^3 is an exact cubic, so its true 4th+ finite
    # differences are zero. The small nonzero d4/d5/d6 measured in practice are
    # pure integer-rounding noise from freq2reg's DDS-code quantization --
    # cascading that noise through further registers doesn't add fidelity, it
    # integrates it into a spurious high-degree runaway polynomial (confirmed:
    # order=4 froze d4 at its noise value, making w_freq quartic in iteration
    # count with a negative leading term -- rises then falls; order=6 did the
    # same with a 6th-degree runaway that diverged/wrapped around).
    cascade_order = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tag = sys.argv[2] if len(sys.argv) > 2 else ""
    print(f"cascade_order={cascade_order}, tag={tag!r}")

    print("Instantiating QickSoc() with d_1.bit...")
    soc = QickSoc(bitfile=BITFILE)
    soccfg = soc

    f_mhz_traj, deltas0 = smoothstep_trajectory(soc, GEN_CH, F0_MHZ, F1_MHZ, N_LOOP)

    config = {
        'gen_ch': GEN_CH, 'ro_ch': RO_CH, 'mixer_freq': 100,
        'f0_mhz': F0_MHZ, 'deltas0': deltas0, 'cascade_order': cascade_order,
        'ro_freq': 0, 'ro_len': RO_LEN_US, 'flat_len': SEG_LEN_US,
        'trig_time': TRIG_TIME_US, 'gain': 1.0, 'n_loop': N_LOOP,
    }

    prog = ChirpProgram(soccfg, reps=1, final_delay=0.0, cfg=config)
    print(prog)

    iq_list = prog.acquire_decimated(soc, progress=True)
    iq = np.asarray(iq_list[0])
    print("acquire_decimated returned shape:", iq.shape)

    I_seg = iq[:, :, 0].astype(float)
    Q_seg = iq[:, :, 1].astype(float)
    n_loop_actual, n_samples = I_seg.shape

    loop_idx = np.repeat(np.arange(n_loop_actual), n_samples)
    sample_idx = np.tile(np.arange(n_samples), n_loop_actual)
    suffix = f"_{tag}" if tag else ""
    out_csv = os.path.join(OUT_DIR, f"chirp_raw_iq{suffix}.csv")
    np.savetxt(out_csv, np.column_stack([loop_idx, sample_idx, I_seg.ravel(), Q_seg.ravel()]),
               delimiter=",", header="loop_iter,sample_idx,I,Q", comments="")
    print(f"[OK] Saved raw I/Q to {out_csv} ({n_loop_actual} loops x {n_samples} samples/loop)")

    meta = {
        "decimated_fs_mhz": DECIMATED_FS_MHZ, "n_loop": n_loop_actual,
        "n_samples_per_seg": n_samples, "f0_mhz": F0_MHZ, "f1_mhz": F1_MHZ,
        "seg_len_us": SEG_LEN_US, "ro_len_us": RO_LEN_US, "trig_time_us": TRIG_TIME_US,
        "gen_ch": GEN_CH, "ro_ch": RO_CH, "bitfile": BITFILE,
        "intended_f_mhz": f_mhz_traj.tolist(), "dummypulse_flush": True,
    }
    meta_path = os.path.join(OUT_DIR, f"chirp_meta{suffix}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Saved metadata to {meta_path}")
    print("[OK] Done -- analyze chirp_raw_iq.csv + chirp_meta.json off-board.")


if __name__ == "__main__":
    main()
