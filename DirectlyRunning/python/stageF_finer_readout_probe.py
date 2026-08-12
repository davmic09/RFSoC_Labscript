"""Stage F -- UNTESTED, NEVER RUN ON HARDWARE. Finer-resolution 8-tone
spectrum via a PFB readout channel (lower native decimated rate = better FFT
resolution for the same sample budget), instead of the dyn_readout (RO_CH=10,
307.2MHz decimated) used throughout Stages A-E.

Why: Stage D's 8-tone spectrum could only be resolved to ~12MHz-wide FFT bins
per tone (25 samples/tone, RO_CH=10's fixed 307.2MHz decimated rate) -- nowhere
near enough to separate the 1MHz-spaced comb; the full-step FFT (200 samples,
all 8 tones concatenated) only did a bit better (~1.5MHz bins), still not
enough, and concatenating a tone's captures across steps to get more samples
was tried and discarded (introduces spectral leakage -- the DDS phase across
those gaps was never verified to be coherent, and the result looked exactly
like it isn't).

FFT resolution is dictated by Δf=fs/N (total real time spanned by one
continuous capture, not sample count alone). RO_CH=10's 307.2MHz decimated
rate looks like a fixed hardware property of that specific readout block (not
software-adjustable) -- but the board's printed config also listed 8
`axis_pfb_readout_v4` channels (indices 2-9) with a natively lower decimated
rate, 38.4MHz -- 8x lower, so the same sample budget spans 8x more real time,
giving 8x finer resolution. Even split 8 ways across tones (~512 samples/tone
if using the full budget), that's ~75kHz bins -- vastly more than enough to
resolve a 1MHz-spaced comb, versus the current ~12MHz bins.

TWO THINGS THIS SCRIPT HAS NOT VERIFIED -- check these BEFORE trusting any of
the acquisition code below (the channel-probe section is meant to be run
first, on its own, for exactly this reason):

1. PHYSICAL WIRING: the PFB channels are wired to ADC port 5 (per the printed
   config: "ADC tile 2, blk 1 is 1_226 on JHC8, or QICK box ADC port 5"), not
   ADC port 0 (JHC5) where the DAC0<->ADC0 loopback has lived for every prior
   stage. The loopback cable needs to move to ADC port 5 (keeping DAC0 as the
   source) before any of this can work at all.

2. SOFTWARE CONFIG PATH: the dyn_readout channels used throughout Stages A-E
   are "configured by tProc" per-program, via the standard v2
   declare_readout()/add_readoutconfig()/send_readoutconfig() calls. The
   printed board config listed the PFB channels as "configured by PYNQ"
   instead -- possibly meaning they need the different, lower-level
   qick.py `config_mux_readout(pfbpath, cfgs)` call instead of (or in
   addition to) the standard API used below. This script guesses the
   standard v2 API "just works" transparently for any readout type (the
   ReadoutManager abstraction in asm_v2.py might paper over the hardware
   difference) -- THIS IS UNCONFIRMED. If the channel-probe/acquisition
   cell hangs, that's the likely cause -- Stage A hit a real multi-minute
   hang from an analogous readout-config gap on the dyn_readout the first
   time around (missing add_readoutconfig/send_readoutconfig); don't wait
   more than ~30s before Ctrl-C / killing the process if this happens.

Also unverified: whether the PFB readout's internal buffer limit matches the
confirmed acquire_decimated 4096-sample cap seen on RO_CH=10, or is different
-- the printed config showed DIFFERENT PFB channels with different internal
buffer depths (channels 2-5: 1024-sample decimated buffer; channels 6-9:
4096-sample decimated buffer). This script defaults to RO_CH=6 (one of the
4096-depth ones) as a first guess -- re-check against a fresh `print(soc)`
once reconnected, since firmware could have changed.

HARDWARE SIDE ONLY (once actually run) -- acquire and save raw data; analysis
happens off-board, same pattern as every other stage.

Suggested usage once reconnected AND rewired (do NOT skip the probe step):
    # 1. Confirm the PFB channel details are what this script assumes:
    sudo BOARD=ZCU216 XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 stageF_finer_readout_probe.py --probe-only
    # 2. Only if that looks right, run the real acquisition:
    sudo BOARD=ZCU216 XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 stageF_finer_readout_probe.py final
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
RO_CH = 6            # UNVERIFIED GUESS -- one of the 4096-decimated-sample PFB
                      # channels (2-5 only have 1024). Re-check against a fresh
                      # print(soc) before trusting this.
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
DECIMATED_FS_MHZ = 38.4    # UNVERIFIED -- from the printed config for
                            # axis_pfb_readout_v4 channels; re-confirm live.
FABRIC_MHZ = 599.04
DUMMY_LEN_US = 3 / FABRIC_MHZ

TONE_STARTS_MHZ = [106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0, 113.0]
N_TONES = len(TONE_STARTS_MHZ)
SEG_LEN_US = 15.0    # UNVERIFIED -- generous per-tone window (~1.5x Stage D's
                      # whole 20-step run per tone) now that resolution no
                      # longer forces a short window; revisit once the real
                      # PFB buffer cap is confirmed (see module docstring).
RO_LEN_US = 13.0      # -> ~500 samples/tone at 38.4MHz if DECIMATED_FS_MHZ is
                      # right (500*8=4000 total, under the assumed 4096-ish
                      # cap for this readout -- UNCONFIRMED, see docstring)
TRIG_TIME_US = 1.5    # UNVERIFIED -- the ~0.4-0.65us transient was
                      # characterized on RO_CH=10; PFB channels have their own
                      # (uncharacterized) pipeline latency. Generous guess,
                      # re-derive properly (e.g. adapt boundary_capture.py to
                      # this channel) before trusting close to the edges.


def probe_readout_channel(soc, ro_ch):
    """Print this channel's actual config -- run this BEFORE the real
    acquisition and compare against the assumptions above (RO_CH, decimated
    rate, buffer depth, ADC port) before trusting any of it."""
    print(f"=== soc['readouts'][{ro_ch}] ===")
    print(soc['readouts'][ro_ch])


class FinerReadoutProgram(AveragerProgramV2):
    """Static (non-swept) 8-tone capture, one continuous longer window per
    tone -- structurally the same as stageD_multitone_acquire.py's per-tone
    pulse+trigger+flush sequence, minus the sweep (no register cascade, no
    step_loop) since the goal here is just a resolvable spectrum, not a
    sweep. If this works, the register-cascade sweep from Stage D could be
    grafted back on the same way it was added to Stage C's mechanism.
    """
    def _initialize(self, cfg):
        gen_ch = cfg['gen_ch']
        ro_ch = cfg['ro_ch']

        self.declare_gen(ch=gen_ch, nqz=1, mixer_freq=cfg['mixer_freq'], ro_ch=ro_ch)
        self.declare_readout(ch=ro_ch, length=cfg['ro_len'])
        for k, f0 in enumerate(cfg['tone_freqs']):
            self.add_pulse(ch=gen_ch, name=f"tone{k}", ro_ch=ro_ch, style="const",
                           freq=f0, length=cfg['flat_len'], phase=0, gain=cfg['gain'])
        self.add_readoutconfig(ch=ro_ch, name="myro", freq=cfg['ro_freq'], gen_ch=gen_ch, phase=0)
        self.send_readoutconfig(ch=ro_ch, name="myro", t=0)

    def _body(self, cfg):
        t = 0.0
        for k in range(cfg['n_tones']):
            self.pulse(ch=cfg['gen_ch'], name=f"tone{k}", t=t)
            self.trigger(ros=[cfg['ro_ch']], pins=[0], t=t + cfg['trig_time'])
            self.pulse(ch=cfg['gen_ch'], name="dummypulse", t=t + cfg['flat_len'])
            t += cfg['flat_len'] + DUMMY_LEN_US


def main():
    probe_only = "--probe-only" in sys.argv
    tag = next((a for a in sys.argv[1:] if not a.startswith("--")), "")

    print("Instantiating QickSoc() with d_1.bit...")
    soc = QickSoc(bitfile=BITFILE)
    soccfg = soc

    probe_readout_channel(soc, RO_CH)
    if probe_only:
        print("[probe-only] Stopping here -- compare the printed config above "
              "against this script's RO_CH/DECIMATED_FS_MHZ/buffer-depth "
              "assumptions before running the real acquisition.")
        return

    print(f"tag={tag!r}")
    config = {
        'gen_ch': GEN_CH, 'ro_ch': RO_CH, 'mixer_freq': 100,
        'tone_freqs': TONE_STARTS_MHZ, 'n_tones': N_TONES,
        'ro_freq': 0, 'ro_len': RO_LEN_US, 'flat_len': SEG_LEN_US,
        'trig_time': TRIG_TIME_US, 'gain': 1.0,
    }

    prog = FinerReadoutProgram(soccfg, reps=1, final_delay=0.0, cfg=config)
    print(prog)   # inspect the ASM before trusting acquire_decimated -- same
                  # habit that caught real bugs in Stage D before it ever ran

    iq_list = prog.acquire_decimated(soc, progress=True)
    iq = np.asarray(iq_list[0])
    print("acquire_decimated returned shape:", iq.shape)

    # NOTE: shape handling copied from Stage D's fix (acquire_decimated groups
    # by triggers-per-rep automatically -- expect (n_tones, n_samples, 2)
    # here, NOT a flat array; adjust if the actual returned shape differs,
    # exactly the kind of thing the Stage D draft got wrong before it was
    # tested on real hardware).
    if iq.ndim == 3:
        n_samples = iq.shape[1]
        I_arr = iq[:, :, 0].astype(float)
        Q_arr = iq[:, :, 1].astype(float)
    else:
        raise RuntimeError(f"Unexpected shape {iq.shape} -- inspect manually "
                            f"before assuming how to reshape it.")

    tone_idx = np.repeat(np.arange(N_TONES), n_samples)
    sample_idx = np.tile(np.arange(n_samples), N_TONES)
    suffix = f"_{tag}" if tag else ""
    out_csv = os.path.join(OUT_DIR, f"finerro_raw_iq{suffix}.csv")
    np.savetxt(out_csv, np.column_stack([tone_idx, sample_idx, I_arr.ravel(), Q_arr.ravel()]),
               delimiter=",", header="tone_idx,sample_idx,I,Q", comments="")
    print(f"[OK] Saved raw I/Q to {out_csv} ({N_TONES} tones x {n_samples} samples)")

    meta = {
        "decimated_fs_mhz": DECIMATED_FS_MHZ, "n_tones": N_TONES, "n_samples_per_tone": n_samples,
        "tone_starts_mhz": TONE_STARTS_MHZ, "seg_len_us": SEG_LEN_US, "ro_len_us": RO_LEN_US,
        "trig_time_us": TRIG_TIME_US, "gen_ch": GEN_CH, "ro_ch": RO_CH, "bitfile": BITFILE,
        "UNTESTED": True,
    }
    meta_path = os.path.join(OUT_DIR, f"finerro_meta{suffix}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[OK] Saved metadata to {meta_path}")
    print("[OK] Done -- analyze finerro_raw_iq.csv + finerro_meta.json off-board.")


if __name__ == "__main__":
    main()
