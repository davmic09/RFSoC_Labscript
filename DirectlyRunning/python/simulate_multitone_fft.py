"""Two-panel comparison: what the RFSoC's 8-tone Stage D capture actually
produced (top, real measured magnitude waveform, time domain) vs. what a
genuine continuous capture's spectrum would be predicted to look like
(bottom, simulated FFT -- NOT measured).

Top panel loads Stage D's real saved data (csv/multitone_raw_iq_final.csv +
json/multitone_meta_final.json) and plots the magnitude |I+jQ| of one full
interleaved step's 8 per-tone snippets concatenated back to back, sectioned
and labeled by tone -- real hardware output, time domain, no FFT (Stage D's
own 25-samples/tone captures are too short for a meaningful FFT, which is the
whole reason Stage F/the predicted-spectrum comparison exists). Bottom panel
builds the idealized waveform directly from the known pulse-sequence parameters
(dwell time, dummypulse flush gap, decimated sample rate) assuming a
phase-continuous DDS across hops (matching the empirical finding that
same-frequency boundary transitions are seamless -- see
FreqSweep_Analysis.ipynb's boundary-diagnostic section), then FFTs that.

Extends Stage E's finding (2-tone TDM sidebands spaced at the switching rate)
to the full 8-tone case: expect the 8 real carriers as local peaks, plus
sidebands spaced at f_hop=1/(8*dwell) around each -- with Stage D's actual
0.85us dwell, f_hop~0.146MHz is far finer than the 1MHz tone spacing, so it
shows up as a dense forest filling the gaps rather than a few isolated
sideband pairs.

Run directly (no QickSoc / hardware needed -- just reads Stage D's already-
saved CSV/JSON from disk):
    python simulate_multitone_fft.py

Edit the CONFIG block below to change tone list, dwell, sample rate, number
of cycles simulated, axis limits, or titles.
"""
import json
import os
import numpy as np
import matplotlib.pyplot as plt

# ============================== CONFIG ==================================
TONE_STARTS_MHZ = [106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0, 113.0]
SEG_LEN_US = 0.85           # per-tone dwell (Stage D's actual value)
FABRIC_MHZ = 599.04         # GEN_CH=0 fabric clock, sets the dummypulse length
DUMMY_LEN_US = 3 / FABRIC_MHZ   # dummypulse flush gap (3 fabric cycles)
DECIMATED_FS_MHZ = 307.2    # RO_CH=10's decimated sample rate (Stage D's channel)
N_CYCLES = 12                # how many full round-robins to simulate (bottom panel)
MEASURED_STEP = 0            # which Stage D step to use for the top (real) panel

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
JSON_DIR = os.path.join(DATA_DIR, "json")
CSV_DIR = os.path.join(DATA_DIR, "csv")
OUT_PNG = os.path.join(DATA_DIR, "images", "multitone_predicted_fft.png")

# Plot appearance -- edit freely
XLIM = (100, 120)          # bottom (spectrum) panel x-axis
TITLE_MEASURED = "Actual Hardware"
TITLE_PREDICTED = "Expected FFT for a continuous capture (simulated, f_hop={f_hop:.3f}MHz)"
# ==========================================================================


def simulate_predicted_multitone_fft(tone_starts_mhz, seg_len_us, dummy_len_us,
                                      decimated_fs_mhz, n_cycles):
    """Idealized continuous capture spanning n_cycles full round-robins of
    tone_starts_mhz, each held for seg_len_us then a dummy_len_us zero-gain
    gap, sampled at decimated_fs_mhz. Phase accumulates continuously across
    hops (no reset)."""
    n_tones = len(tone_starts_mhz)
    cycle_us = n_tones * (seg_len_us + dummy_len_us)
    f_hop = 1 / cycle_us
    dt = 1 / decimated_fs_mhz

    seq = []
    t_cursor = 0.0
    for _ in range(n_cycles):
        for f0 in tone_starts_mhz:
            seq.append((t_cursor, t_cursor + seg_len_us, f0))
            t_cursor += seg_len_us
            seq.append((t_cursor, t_cursor + dummy_len_us, None))
            t_cursor += dummy_len_us

    t = np.arange(0, t_cursor, dt)
    I = np.zeros_like(t)
    phase_acc = 0.0
    for (t0, t1, f0) in seq:
        idx0, idx1 = int(t0 / dt), int(t1 / dt)
        if idx1 <= idx0:
            continue
        seg_t = t[idx0:idx1] - t[idx0]
        if f0 is None:
            I[idx0:idx1] = 0.0
        else:
            I[idx0:idx1] = np.cos(2 * np.pi * f0 * seg_t + phase_acc)
            phase_acc = (phase_acc + 2 * np.pi * f0 * (seg_t[-1] + dt)) % (2 * np.pi)

    n = len(I)
    hann = np.hanning(n)
    spec = np.abs(np.fft.rfft((I - I.mean()) * hann))
    freqs = np.fft.rfftfreq(n, d=dt)
    return t, I, freqs, spec, f_hop, cycle_us


def load_measured_waveform(tag, step):
    """Real Stage D data: magnitude |I+jQ| of one full interleaved step's 8
    per-tone snippets concatenated back to back, exactly as actually
    captured on hardware -- no FFT, time domain only. This is what the
    RFSoC actually produced."""
    with open(os.path.join(JSON_DIR, f"multitone_meta_{tag}.json")) as f:
        meta = json.load(f)
    raw = np.loadtxt(os.path.join(CSV_DIR, f"multitone_raw_iq_{tag}.csv"), delimiter=",", skiprows=1)
    _, _, _, I_col, Q_col = raw.T
    n_steps, n_tones, n_samples = meta["n_steps"], meta["n_tones"], meta["n_samples_per_seg"]
    fs = meta["decimated_fs_mhz"]
    I_arr = I_col.reshape(n_steps, n_tones, n_samples)
    Q_arr = Q_col.reshape(n_steps, n_tones, n_samples)

    mag_concat = np.abs(I_arr[step] + 1j * Q_arr[step]).ravel()
    t_concat = np.arange(n_tones * n_samples) / fs
    seg_us = n_samples / fs
    return t_concat, mag_concat, seg_us, meta


def main():
    n_tones = len(TONE_STARTS_MHZ)
    colors = plt.cm.viridis(np.linspace(0, 1, n_tones))

    t_meas, mag_meas, seg_us, meas_meta = load_measured_waveform("final", MEASURED_STEP)

    t_sim, I_sim, freqs_sim, spec_sim, f_hop, cycle_us = simulate_predicted_multitone_fft(
        TONE_STARTS_MHZ, SEG_LEN_US, DUMMY_LEN_US, DECIMATED_FS_MHZ, N_CYCLES)
    print(f"cycle_us={cycle_us:.4f}, f_hop={f_hop:.4f}MHz")

    fig, axes = plt.subplots(2, 1, figsize=(13, 9))

    axes[0].plot(t_meas, mag_meas, lw=0.9, color="steelblue")
    for k, f0 in enumerate(meas_meta["tone_starts_mhz"]):
        if k % 2 == 0:
            axes[0].axvspan(k * seg_us, (k + 1) * seg_us, alpha=0.08, color="gray")
        axes[0].text((k + 0.5) * seg_us, mag_meas.max() * 1.05, f"{f0:.0f}MHz",
                    ha="center", fontsize=8, color=colors[k])
    axes[0].set_ylim(0, mag_meas.max() * 1.15)
    axes[0].set_xlabel("time [us]")
    axes[0].set_ylabel("|I+jQ| magnitude")
    axes[0].set_title(TITLE_MEASURED.format(step=MEASURED_STEP))

    axes[1].plot(freqs_sim, spec_sim, lw=1.3, color="steelblue")
    axes[1].set_xlim(XLIM)
    for k, f0 in enumerate(TONE_STARTS_MHZ):
        axes[1].axvline(f0, color=colors[k], ls="--", lw=1.3)
        axes[1].annotate(f"tone{k}\n{f0:.0f}", xy=(f0, spec_sim.max() * 0.95), ha="center",
                         fontsize=8, color=colors[k], fontweight="bold")
    axes[1].set_xlabel("freq [MHz]")
    axes[1].set_ylabel("|FFT| (predicted)")
    axes[1].set_title(TITLE_PREDICTED.format(f_hop=f_hop))

    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print(f"[OK] saved {OUT_PNG}")


if __name__ == "__main__":
    main()
