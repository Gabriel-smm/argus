"""Find the bursts in an IQ capture and measure each one.

`detect_bursts` takes complex IQ samples, the sample rate and the centre frequency
of the capture, and returns one dict per burst with the features the classifier
uses. A burst is a group of pulses less than MAX_PULSE_GAP_S apart; a continuous
signal is one burst with one pulse. No absolute power leaves this module: the
noise floor is only used to decide what is on, and every level is a ratio.
"""

import numpy as np

# Envelope smoothing: half a microsecond, and never fewer than four samples.
SMOOTH_SECONDS = 0.5e-6
SMOOTH_MIN_SAMPLES = 4
# A sample is on when its smoothed power is this far above the floor.
THRESHOLD_DB = 8.0
# Pulses closer than this belong to the same burst.
MAX_PULSE_GAP_S = 20e-3
FFT_SIZE = 1024
HOP = 512
SPECTRUM_SMOOTH_BINS = 5
# A bin counts as signal when it is this many times above the noise spectrum.
FLOOR_MARGIN = 3.0
POWER_CONTAINED = 0.95


def detect_bursts(iq: np.ndarray, sample_rate_hz: float, center_frequency_hz: float) -> list[dict]:
    """One dict per burst, earliest first. Empty when nothing rises above the noise."""
    iq = np.ascontiguousarray(iq, dtype=np.complex64)
    total = len(iq)
    if total == 0:
        return []
    power = (iq.real.astype(np.float64) ** 2) + (iq.imag.astype(np.float64) ** 2)
    smooth = max(SMOOTH_MIN_SAMPLES, round(SMOOTH_SECONDS * sample_rate_hz))
    envelope = _moving_average(power, smooth)

    # The floor is whichever is lower: the median of the envelope (right when the
    # signal is off most of the time) or the median spectral density times the
    # number of bins (right when a narrow signal is on all the time).
    floor = min(np.median(envelope), np.median(_psd([iq])) * FFT_SIZE)
    on = envelope > floor * 10 ** (THRESHOLD_DB / 10)
    pulses = _runs(on, merge_gap=2 * smooth, min_length=smooth + 1)
    if not pulses:
        return []

    off = ~on
    noise_power = float(power[off].mean()) if off.any() else float(floor)
    noise_psd = _psd(_segments(iq, _runs(off, 0, FFT_SIZE))) if off.sum() >= FFT_SIZE else None

    max_gap = MAX_PULSE_GAP_S * sample_rate_hz
    bursts = []
    group = [pulses[0]]
    for pulse in pulses[1:]:
        if pulse[0] - group[-1][0] < max_gap:
            group.append(pulse)
        else:
            bursts.append(_measure(iq, envelope, group, noise_psd, noise_power, sample_rate_hz, center_frequency_hz))
            group = [pulse]
    bursts.append(_measure(iq, envelope, group, noise_psd, noise_power, sample_rate_hz, center_frequency_hz))
    return bursts


def _measure(iq, envelope, pulses, noise_psd, noise_power, sample_rate_hz, center_frequency_hz) -> dict:
    total = len(iq)
    start, end = pulses[0][0], pulses[-1][1]
    truncated = start == 0 or end == total
    on_samples = sum(b - a for a, b in pulses)
    starts = np.array([a for a, _ in pulses], dtype=np.float64)

    burst_psd = _psd(_segments(iq, pulses))
    if noise_psd is None:
        noise_psd = np.full_like(burst_psd, np.median(burst_psd))
    signal = _smooth_bins(np.clip(burst_psd - FLOOR_MARGIN * noise_psd, 0, None))
    bin_hz = sample_rate_hz / FFT_SIZE
    frequencies = (np.arange(FFT_SIZE) - FFT_SIZE / 2) * bin_hz
    low, high = _contained(signal, POWER_CONTAINED)
    band = slice(low, high + 1)
    weights = signal[band]
    if weights.sum() > 0:
        offset = float(np.average(frequencies[band], weights=weights))
    else:
        offset = float(frequencies[int(np.argmax(burst_psd))])
    bandwidth = (high - low + 1) * bin_hz
    snr = 10 * np.log10(burst_psd[band].sum() / max(noise_psd[band].sum(), 1e-30))

    # Hopping: the centre moves from pulse to pulse by more than one pulse's own width.
    hopping = False
    if len(pulses) > 1:
        centres, widths = [], []
        for a, b in pulses:
            pulse_signal = _smooth_bins(np.clip(_psd([iq[a:b]]) - FLOOR_MARGIN * noise_psd, 0, None))
            if pulse_signal.sum() > 0:
                lo, hi = _contained(pulse_signal, POWER_CONTAINED)
                centres.append(np.average(frequencies[lo : hi + 1], weights=pulse_signal[lo : hi + 1]))
                widths.append((hi - lo + 1) * bin_hz)
        if len(centres) > 1:
            hopping = bool(np.std(centres) > max(np.median(widths), 2 * bin_hz))

    return {
        "center_frequency_hz": float(center_frequency_hz + offset),
        "bandwidth_hz": float(bandwidth),
        "snr_db": float(snr),
        "duty_cycle": float(on_samples / (end - start)),
        "burst_duration_s": None if truncated else float((end - start) / sample_rate_hz),
        "hopping": hopping,
        "pulse_interval_s": float(np.median(np.diff(starts)) / sample_rate_hz) if len(pulses) > 1 else None,
        "modulation": "unknown",
        "truncated": bool(truncated),
        # Debug fields, not written to training rows.
        "start_s": float(start / sample_rate_hz),
        "end_s": float(end / sample_rate_hz),
        "pulses": len(pulses),
        "peak_snr_db": float(10 * np.log10(envelope[start:end].max() / max(noise_power, 1e-30))),
    }


def _moving_average(values: np.ndarray, width: int) -> np.ndarray:
    padded = np.concatenate([np.zeros(1), np.cumsum(values)])
    left = width // 2
    index = np.arange(len(values))
    lo = np.clip(index - left, 0, len(values))
    hi = np.clip(index - left + width, 0, len(values))
    return (padded[hi] - padded[lo]) / np.maximum(hi - lo, 1)


def _runs(mask: np.ndarray, merge_gap: int, min_length: int) -> list[tuple[int, int]]:
    """[start, end) spans where mask is true; gaps under merge_gap are bridged."""
    edges = np.flatnonzero(np.diff(np.concatenate([[False], mask, [False]]).astype(np.int8)))
    runs = [(int(edges[i]), int(edges[i + 1])) for i in range(0, len(edges), 2)]
    merged: list[tuple[int, int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(a, b) for a, b in merged if b - a >= min_length]


def _segments(iq: np.ndarray, runs: list[tuple[int, int]]) -> list[np.ndarray]:
    return [iq[a:b] for a, b in runs]


def _psd(segments: list[np.ndarray]) -> np.ndarray:
    """Average power spectrum of the segments, shifted so bin FFT_SIZE/2 is DC.

    Each FFT_SIZE-sample frame is Hann-windowed; a segment shorter than a frame is
    windowed over its own length and zero-padded. Scaled so the bins sum to the
    mean sample power, whatever the window.
    """
    frames = []
    for segment in segments:
        if len(segment) >= FFT_SIZE:
            for offset in range(0, len(segment) - FFT_SIZE + 1, HOP):
                frames.append(segment[offset : offset + FFT_SIZE])
        elif len(segment) > 0:
            frames.append(segment)
    if not frames:
        return np.zeros(FFT_SIZE)
    psd = np.zeros(FFT_SIZE)
    for frame in frames:
        window = np.hanning(len(frame) + 2)[1:-1]
        spectrum = np.fft.fft(frame * window, FFT_SIZE)
        psd += np.abs(spectrum) ** 2 / (FFT_SIZE * np.sum(window**2))
    return np.fft.fftshift(psd / len(frames))


def _smooth_bins(spectrum: np.ndarray) -> np.ndarray:
    kernel = np.ones(SPECTRUM_SMOOTH_BINS) / SPECTRUM_SMOOTH_BINS
    return np.convolve(spectrum, kernel, mode="same")


def _contained(spectrum: np.ndarray, share: float) -> tuple[int, int]:
    """Smallest bin span grown outwards from the peak that holds `share` of the power."""
    peak = int(np.argmax(spectrum))
    target = share * spectrum.sum()
    low = high = peak
    held = spectrum[peak]
    while held < target and (low > 0 or high < len(spectrum) - 1):
        left = spectrum[low - 1] if low > 0 else -1.0
        right = spectrum[high + 1] if high < len(spectrum) - 1 else -1.0
        if left >= right:
            low -= 1
            held += spectrum[low]
        else:
            high += 1
            held += spectrum[high]
    return low, high
