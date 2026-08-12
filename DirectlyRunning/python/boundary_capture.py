"""Pulse-to-pulse boundary diagnostic -- captures ONE continuous ADC readout
straddling the transition between two back-to-back pulses at frequencies f1
then f2, at full decimated-sample resolution, so the raw oscillation is
visible on both sides of the boundary (a couple of periods each side) plus
whatever startup transient sits right at the transition itself.

This is deliberately NOT what the per-segment analysis captures elsewhere --
those readouts are timed (trig_time=0.65us) to skip past the transient and
land in the clean region. This script captures across the transient on
purpose, to see the transition itself.

Optional `flush` arg (0/1, default 0): inserts a zero-gain "dummypulse"
(documented QICK pattern -- a 3-fabric-cycle, gain=0 pulse) between pulseA and
pulseB, to test whether driving the generator cleanly to zero before the
frequency change removes the transient -- this is the direct verification for
the same fix applied to stageA2_acquire_only.py / stageC_chirp_acquire.py.

HARDWARE SIDE ONLY -- acquire and save raw data; analysis happens off-board.

Run on the ZCU216 (needs root for QickSoc()):
    sudo BOARD=ZCU216 XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 boundary_capture.py f1 f2 seg_len_us tag [flush]
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

PRE_US = 0.05    # captured before the boundary -- a couple periods of f1 (clean, since
                 # by segA_len the pulse1 startup transient has long settled)
POST_US = 0.75   # captured after the boundary -- covers the ~0.65us startup transient
                 # PLUS several clean periods of f2 once it settles


class BoundaryProgram(AveragerProgramV2):
    def _initialize(self, cfg):
        gen_ch = cfg['gen_ch']
        ro_ch = cfg['ro_ch']
        self.declare_gen(ch=gen_ch, nqz=1, mixer_freq=cfg['mixer_freq'], ro_ch=ro_ch)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])
        self.add_pulse(ch=gen_ch, name="pulseA", ro_ch=ro_ch, style="const",
                       freq=cfg['f1'], length=cfg['seg_len'], phase=0, gain=cfg['gain'])
        self.add_pulse(ch=gen_ch, name="pulseB", ro_ch=ro_ch, style="const",
                       freq=cfg['f2'], length=cfg['seg_len'], phase=0, gain=cfg['gain'])
        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['ro_freq'], gen_ch=gen_ch, phase=0)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)

    def _body(self, cfg):
        self.pulse(ch=cfg['gen_ch'], name="pulseA", t=0)
        if cfg['flush']:
            # zero-gain flush between pulseA and pulseB (~5ns at 599.04MHz fabric
            # clock -- negligible next to PRE_US/POST_US, shifts the true boundary
            # by that much relative to the nominal t=seg_len used for the trigger)
            self.pulse(ch=cfg['gen_ch'], name="dummypulse", t="auto")
        self.pulse(ch=cfg['gen_ch'], name="pulseB", t="auto")
        self.trigger(ros=[cfg['ro_ch']], pins=[0], t=cfg['seg_len'] - PRE_US)


def main():
    f1 = float(sys.argv[1]) if len(sys.argv) > 1 else 109.0
    f2 = float(sys.argv[2]) if len(sys.argv) > 2 else 111.0
    seg_len_us = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    tag = sys.argv[4] if len(sys.argv) > 4 else ""
    flush = bool(int(sys.argv[5])) if len(sys.argv) > 5 else False
    print(f"f1={f1}, f2={f2}, seg_len_us={seg_len_us}, tag={tag!r}, flush={flush}")

    print("Instantiating QickSoc() with d_1.bit...")
    soc = QickSoc(bitfile=BITFILE)
    soccfg = soc

    config = {
        'gen_ch': GEN_CH, 'ro_ch': RO_CH, 'mixer_freq': 100,
        'f1': f1, 'f2': f2, 'seg_len': seg_len_us, 'flush': flush,
        'ro_freq': 0, 'ro_len': PRE_US + POST_US, 'gain': 1.0,
    }

    prog = BoundaryProgram(soccfg, reps=1, final_delay=0.0, cfg=config)
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
    out_csv = os.path.join(OUT_DIR, f"boundary_raw_iq{suffix}.csv")
    np.savetxt(out_csv, np.column_stack([sample_idx, I_arr, Q_arr]),
               delimiter=",", header="sample_idx,I,Q", comments="")
    print(f"[OK] Saved raw I/Q to {out_csv} ({n_samples} samples)")

    meta = {
        "decimated_fs_mhz": DECIMATED_FS_MHZ, "n_samples": n_samples,
        "f1_mhz": f1, "f2_mhz": f2, "seg_len_us": seg_len_us,
        "pre_us": PRE_US, "post_us": POST_US, "flush": flush,
        "gen_ch": GEN_CH, "ro_ch": RO_CH, "bitfile": BITFILE,
    }
    meta_path = os.path.join(OUT_DIR, f"boundary_meta{suffix}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Saved metadata to {meta_path}")
    print("[OK] Done -- analyze boundary_raw_iq.csv + boundary_meta.json off-board.")


if __name__ == "__main__":
    main()
