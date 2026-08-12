"""Predicted (simulated, NOT measured) per-cycle waveforms and spectrum for
Stage G's engineered AM-sideband comb. No hardware involved -- pure math,
matching the exact design parameters in stageG_am_comb_sweep.py.

Three independent views of the same one-cycle design:
1. The "arb waveform" -- the gain ENVELOPE itself (what actually gets
   uploaded to the generator's envelope memory as idata/qdata). This is a
   sum of exactly 4 cosines (0.5, 1.5, 2.5, 3.5MHz), nothing else.
2. The "RF waveform" -- the actual physical DAC output: envelope x carrier
   (109.5MHz). This is what would really come out of the SMA port.
3. The predicted spectrum (many cycles, for real frequency resolution) --
   should show 8 sharp lines at 106-113MHz and ~78dB of suppression
   everywhere else (see FreqSweep_Analysis.ipynb's "Stage G design" section
   for the validated numbers).

Run directly (no QickSoc / hardware needed):
    python simulate_am_comb.py

Edit the CONFIG block below to change center frequency, modulation offsets,
sample rate, number of cycles for the FFT, or titles/axis limits.
"""
import os
import numpy as np
import matplotlib.pyplot as plt

# ============================== CONFIG ==================================
F_CENTER_MHZ = 109.5                        # fixed carrier -- sweeps via Stage C's
                                             # cascade mechanism in the real design
MOD_OFFSETS_MHZ = [0.5, 1.5, 2.5, 3.5]      # -> 8 sidebands at center +/- these
DAC_FS_MHZ = 9584.64                         # gen0's real DAC sample rate (envelope table rate)
SAMPS_PER_CLK = 16                           # gen0's envelope-length granularity
N_CYCLES_FFT = 50                            # modulation periods to simulate for the FFT panel

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images")
OUT_PNG = os.path.join(OUT_DIR, "am_comb_per_cycle.png")

# Plot appearance -- edit freely
SPEC_XLIM = (F_CENTER_MHZ - 10, F_CENTER_MHZ + 10)
TITLE_ARB = "Arb waveform (gain envelope uploaded to generator memory)"
TITLE_RF = "RF waveform (actual DAC output: envelope x carrier)"
TITLE_FFT = "Predicted spectrum ({n_cycles} cycles)"
# ==========================================================================


def build_envelope(f_center_mhz, mod_offsets_mhz, dac_fs_mhz, samps_per_clk):
    """Exactly the N needed cosines, nothing else. Rounds envelope length to
    a multiple of samps_per_clk, then re-derives the modulation frequencies
    as exact odd harmonics of the resulting discretized period so the table
    is perfectly periodic (no wraparound discontinuity)."""
    t_mod_us_nominal = 1.0 / mod_offsets_mhz[0]
    n_env = int(round(t_mod_us_nominal * dac_fs_mhz / samps_per_clk) * samps_per_clk)
    fundamental_mhz = dac_fs_mhz / n_env
    harmonics = [fundamental_mhz * (2 * k + 1) for k in range(len(mod_offsets_mhz))]
    t_env = np.arange(n_env) / dac_fs_mhz
    m = sum(np.cos(2 * np.pi * f * t_env) for f in harmonics)
    m = m / np.max(np.abs(m))
    t_mod_us_actual = n_env / dac_fs_mhz
    return t_env, m, harmonics, t_mod_us_actual


def main():
    t_env, m, harmonics, t_mod_us = build_envelope(F_CENTER_MHZ, MOD_OFFSETS_MHZ, DAC_FS_MHZ, SAMPS_PER_CLK)
    print(f"t_mod_us={t_mod_us:.6f}, harmonics={harmonics}")

    rf = m * np.cos(2 * np.pi * F_CENTER_MHZ * t_env)

    # --- FFT panel: repeat for N_CYCLES_FFT periods for real resolution ---
    n_env = len(m)
    carrier_t = np.arange(N_CYCLES_FFT * n_env) / DAC_FS_MHZ
    env_repeated = np.tile(m, N_CYCLES_FFT)
    x = env_repeated * np.cos(2 * np.pi * F_CENTER_MHZ * carrier_t)
    n = len(x)
    hann = np.hanning(n)
    spec = np.abs(np.fft.rfft((x - x.mean()) * hann))
    freqs = np.fft.rfftfreq(n, d=1 / DAC_FS_MHZ)

    targets = sorted([F_CENTER_MHZ + o for o in MOD_OFFSETS_MHZ] + [F_CENTER_MHZ - o for o in MOD_OFFSETS_MHZ])
    colors = plt.cm.viridis(np.linspace(0, 1, len(targets)))

    fig, axes = plt.subplots(3, 1, figsize=(12, 12))

    # 1. arb waveform (envelope only)
    axes[0].plot(t_env, m, color="crimson", lw=1.3)
    axes[0].set_xlabel("time [us]")
    axes[0].set_ylabel("gain (normalized)")
    axes[0].set_title(TITLE_ARB)
    axes[0].set_xlim(t_env[0], t_env[-1])

    # 2. RF waveform (envelope x carrier -- the real DAC output)
    axes[1].plot(t_env, rf, color="steelblue", lw=0.5)
    axes[1].plot(t_env, m, color="crimson", lw=1.0, ls="--", alpha=0.6, label="envelope (for reference)")
    axes[1].plot(t_env, -m, color="crimson", lw=1.0, ls="--", alpha=0.6)
    axes[1].set_xlabel("time [us]")
    axes[1].set_ylabel("DAC output (normalized)")
    axes[1].set_title(TITLE_RF)
    axes[1].set_xlim(t_env[0], t_env[-1])
    axes[1].legend(fontsize=8, loc="upper right")

    # 3. predicted spectrum
    axes[2].plot(freqs, spec, lw=1.0, color="steelblue")
    axes[2].set_xlim(SPEC_XLIM)
    for k, f0 in enumerate(targets):
        axes[2].axvline(f0, color=colors[k], ls="--", lw=1)
        axes[2].annotate(f"{f0:.0f}", xy=(f0, spec.max() * 0.92), ha="center",
                         fontsize=8, color=colors[k], fontweight="bold")
    axes[2].set_xlabel("freq [MHz]")
    axes[2].set_ylabel("|FFT|")
    axes[2].set_title(TITLE_FFT.format(n_cycles=N_CYCLES_FFT))

    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print(f"[OK] saved {OUT_PNG}")


if __name__ == "__main__":
    main()
