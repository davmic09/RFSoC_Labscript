"""Stage A2 -- HARDWARE SIDE ONLY: run the sweep once, save raw I/Q + metadata to CSV.
All analysis (windowing, sub-bin interpolation, linear fit, plotting) happens separately,
off-board, on the dev machine -- see FreqSweep_Analysis.ipynb. Keeps hardware runs and
analysis iteration fully decoupled: run this once, then analyze locally as many times as
needed without touching the RFSoC again.

Run on the ZCU216 (needs root for QickSoc()):
    sudo BOARD=ZCU216 XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 stageA2_acquire_only.py
"""
import os
os.environ.setdefault("BOARD", "ZCU216")
os.environ.setdefault("XILINX_XRT", "/usr")

import json
import sys
import numpy as np

from qick import QickSoc
from qick.asm_v2 import AveragerProgramV2, QickSweep1D

BITFILE = "/home/xilinx/jupyter_notebooks/amo_qick/tests/rf_board_firmware/d_1.bit"
GEN_CH = 0
RO_CH = 10
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
DECIMATED_FS_MHZ = 307.2


class SweepProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        frequency = QickSweep1D("loopedy_loop", cfg["f_start"], cfg["f_stop"])
        ro_ch = cfg['ro_ch']
        gen_ch = cfg['gen_ch']
        self.declare_gen(ch=gen_ch, nqz=cfg['nqz'], mixer_freq=cfg['mixer_freq'], ro_ch=ro_ch)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])
        self.add_pulse(ch=gen_ch, name="mypulse", ro_ch=ro_ch,
                       style="const",
                       freq=frequency,
                       length=cfg['flat_len'],
                       phase=cfg['phase'],
                       gain=cfg['gain'],
                      )
        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['ro_freq'], gen_ch=gen_ch, phase=0)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)
        self.add_loop("loopedy_loop", cfg['n_loop'], exec_before=None, exec_after=None)

    def _body(self, cfg):
        self.pulse(ch=cfg['gen_ch'], name="mypulse", t=0)
        self.trigger(ros=[cfg['ro_ch']], pins=[0], t=cfg['trig_time'])
        # Zero-gain "dummypulse" (documented QICK pattern, asm_v2.py: auto-inserted
        # 3-fabric-cycle, gain=0 pulse) right after mypulse ends -- drives the
        # generator cleanly to zero before the next iteration's frequency change,
        # instead of jumping directly from one live frequency to the next. This is
        # the fix for the ~0.4-0.65us post-boundary transient diagnosed via
        # boundary_capture.py (confirmed via a dummypulse-inserted variant of that
        # same diagnostic -- see boundary_capture.py's module docstring).
        self.pulse(ch=cfg['gen_ch'], name="dummypulse", t="auto")


def main():
    # Usage: stageA2_acquire_only.py [f_start] [f_stop] [tag]
    # tag="linear" (default 109->111) or tag="constant" (e.g. 110->110) -- see
    # FreqSweep_Analysis.ipynb for the two kept final validations.
    f_start = float(sys.argv[1]) if len(sys.argv) > 1 else 109
    f_stop = float(sys.argv[2]) if len(sys.argv) > 2 else 111
    tag = sys.argv[3] if len(sys.argv) > 3 else "linear"
    print(f"f_start={f_start}, f_stop={f_stop}, tag={tag}")

    print("Instantiating QickSoc() with d_1.bit...")
    soc = QickSoc(bitfile=BITFILE)
    soccfg = soc

    n_loop = 20
    ro_len_us = 0.65   # -> round(0.65*307.2) = 200 samples/segment

    config = {'gen_ch': GEN_CH,
              'ro_ch': RO_CH,
              'mixer_freq': 100,
              'f_start': f_start,
              'f_stop': f_stop,
              'ro_freq': 0,
              'nqz': 1,
              'ro_len': ro_len_us,
              # Diagnosed via pulse_gap_diag.py: each pulse has a fixed ~0.4-0.65us
              # startup transient before clean oscillation begins (confirmed by
              # sweeping trig_time on a 2-pulse test until the transition dip moved
              # from deep inside the readout window to right at its edge). Delaying
              # the trigger by that much, and lengthening flat_len to cover
              # trig_time+ro_len, keeps the whole capture window inside the clean
              # region instead of straddling the transient.
              'flat_len': 0.65 + ro_len_us + 0.1,
              'trig_time': 0.65,
              'phase': 0,
              'gain': 1.0,
              'n_loop': n_loop,
             }

    prog = SweepProgram(soccfg, reps=1, final_delay=0.0, cfg=config)
    print(prog)

    iq_list = prog.acquire_decimated(soc, progress=True)
    iq = np.asarray(iq_list[0])
    print("acquire_decimated returned shape:", iq.shape)   # (n_loop, n_samples, 2)

    I_seg = iq[:, :, 0].astype(float)
    Q_seg = iq[:, :, 1].astype(float)
    n_loop_actual, n_samples = I_seg.shape

    # Long/tidy format: one row per (loop_iter, sample_idx) -- easy to load and
    # reshape anywhere, self-describing, no separate metadata file needed for
    # the array shape itself.
    loop_idx = np.repeat(np.arange(n_loop_actual), n_samples)
    sample_idx = np.tile(np.arange(n_samples), n_loop_actual)
    out_csv = os.path.join(OUT_DIR, f"sweep_{tag}_raw_iq.csv")
    np.savetxt(out_csv,
               np.column_stack([loop_idx, sample_idx, I_seg.ravel(), Q_seg.ravel()]),
               delimiter=",", header="loop_iter,sample_idx,I,Q", comments="")
    print(f"[OK] Saved raw I/Q to {out_csv} ({n_loop_actual} loops x {n_samples} samples/loop)")

    meta = {
        "decimated_fs_mhz": DECIMATED_FS_MHZ,
        "n_loop": n_loop_actual,
        "n_samples_per_seg": n_samples,
        "f_start_mhz": config["f_start"],
        "f_stop_mhz": config["f_stop"],
        "ro_freq_mhz": config["ro_freq"],
        "ro_len_us": config["ro_len"],
        "flat_len_us": config["flat_len"],
        "trig_time_us": config["trig_time"],
        "gain": config["gain"],
        "gen_ch": GEN_CH,
        "ro_ch": RO_CH,
        "bitfile": BITFILE,
        "dummypulse_flush": True,
    }
    meta_path = os.path.join(OUT_DIR, f"sweep_{tag}_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Saved metadata to {meta_path}")
    print(f"[OK] Done -- analyze sweep_{tag}_raw_iq.csv + sweep_{tag}_meta.json off-board.")


if __name__ == "__main__":
    main()
