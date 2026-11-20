"""Repeatable baseband test waveforms for the N5172B internal ARB.

Only NumPy is needed. Single-carrier bandwidth is the ideal RRC null-to-null
width, OFDM bandwidth is active-subcarrier count times spacing, and FM reports
the Carson estimate. These definitions are not measured 99% occupied bandwidth.
The finite random records repeat when played by the instrument.
Frequency offset is metadata for the instrument's continuous hardware rotator;
it does not mix or quantize the uploaded I/Q samples.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict

import numpy as np


# The repository's saved instrument snapshot reports baseband option 653,
# whose documented ARB clock maximum is 75 MSa/s.
MAX_SAMPLE_RATE_HZ = 75e6
MIN_SAMPLE_RATE_HZ = 1e3
MAX_BANDWIDTH_HZ = 40e6
# Conservative nominal-band guard for option 653's 60 MHz RF bandwidth.
# https://www.keysight.com/content/dam/keysight/en/doc/ungate/configuration-guides/5990-9958.pdf
# This is narrower than the hardware baseband-offset command's +/-50 MHz range.
MAX_BASEBAND_EDGE_HZ = 30e6
MAX_SAMPLES = 1_000_000
PEAK_AMPLITUDE = 0.7
SINGLE_CARRIER_MODES = ("BPSK", "QPSK", "8PSK", "16QAM", "64QAM")
MODES = SINGLE_CARRIER_MODES + ("FM", "OFDM")


@dataclass(frozen=True)
class WaveformConfig:
    mode: str = "BPSK"
    bandwidth_hz: float = 1e6
    alpha: float = 0.35
    fm_deviation_hz: float = 75e3
    fm_tone_hz: float = 15e3
    ofdm_fft: int = 256
    ofdm_active: int = 128
    ofdm_cp: int = 32
    ofdm_constellation: str = "QPSK"
    seed: int = 1
    frequency_offset_hz: float = 0.0


@dataclass(frozen=True)
class Waveform:
    iq: np.ndarray
    sample_rate_hz: float
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def _number(value, name, minimum, maximum, *, exclusive_min=False):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(name + " must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(name + " must be a finite number")
    if result > maximum or (result <= minimum if exclusive_min else result < minimum):
        bound = ">" if exclusive_min else ">="
        raise ValueError("{} must be {} {:g} and <= {:g}".format(name, bound, minimum, maximum))
    return result


def _integer(value, name, minimum, maximum):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(name + " must be an integer")
    number = _number(value, name, minimum, maximum)
    if number != int(number):
        raise ValueError(name + " must be an integer")
    return int(number)


def _symbols(rng, count, kind):
    if kind in ("BPSK", "QPSK", "8PSK"):
        order = {"BPSK": 2, "QPSK": 4, "8PSK": 8}[kind]
        return np.exp(2j * np.pi * rng.integers(order, size=count) / order)
    order = {"16QAM": 16, "64QAM": 64}[kind]
    side = int(math.sqrt(order))
    i = 2 * rng.integers(side, size=count) - (side - 1)
    q = 2 * rng.integers(side, size=count) - (side - 1)
    return (i + 1j * q) / math.sqrt(2 * (order - 1) / 3)


def _single_carrier(config, rng, mode):
    bw = _number(config.bandwidth_hz, "Bandwidth (Hz)", 0, MAX_BANDWIDTH_HZ,
                 exclusive_min=True)
    alpha = _number(config.alpha, "RRC alpha", 0, 1)
    symbol_rate = bw / (1 + alpha)
    sample_rate = 8 * symbol_rate
    if sample_rate > MAX_SAMPLE_RATE_HZ:
        raise ValueError("At 8 samples/symbol and alpha {:g}, bandwidth must be <= {:.6g} MHz "
                         "for the 75 MSa/s ARB clock".format(
                             alpha, MAX_SAMPLE_RATE_HZ * (1 + alpha) / 8e6))
    _number(sample_rate, "Derived sample rate (Sa/s)", MIN_SAMPLE_RATE_HZ,
            MAX_SAMPLE_RATE_HZ)
    impulses = np.zeros(32768, dtype=np.complex128)
    impulses[::8] = _symbols(rng, len(impulses) // 8, mode)
    frequency = np.abs(np.fft.fftfreq(len(impulses)))
    lower, upper = (1 - alpha) / 16, (1 + alpha) / 16
    response = np.zeros(len(impulses), dtype=np.float64)
    response[frequency <= lower] = 1
    if alpha:
        transition = (frequency > lower) & (frequency < upper)
        response[transition] = np.sqrt(
            0.5 * (1 + np.cos(np.pi * (frequency[transition] - lower) / (upper - lower))))
    iq = np.fft.ifft(np.fft.fft(impulses) * response)
    summary = "{} | BW {:.6g} MHz | Rs {:.6g} Msym/s | RRC alpha {:.4g}".format(
        mode, bw / 1e6, symbol_rate / 1e6, alpha)
    metadata = {"mode": mode, "bandwidth_hz": bw, "bandwidth_definition":
                "ideal RRC null-to-null", "symbol_rate_hz": symbol_rate,
                "alpha": alpha, "samples_per_symbol": 8, "symbols": 4096}
    return iq, sample_rate, summary, metadata


def _fm(config):
    deviation = _number(config.fm_deviation_hz, "FM deviation (Hz)", 0,
                        MAX_BANDWIDTH_HZ / 2)
    tone = _number(config.fm_tone_hz, "FM tone frequency (Hz)", 0,
                   MAX_BANDWIDTH_HZ / 2, exclusive_min=True)
    bandwidth = 2 * (deviation + tone)
    _number(bandwidth, "FM Carson bandwidth (Hz)", 0, MAX_BANDWIDTH_HZ,
            exclusive_min=True)
    beta = deviation / tone
    if not math.isfinite(beta) or beta > MAX_SAMPLES / 16 - 1:
        raise ValueError("FM deviation/tone ratio requires more than 1,000,000 samples per cycle")
    # Use an integer number of samples per message cycle, so both the message
    # and the FM phase close exactly at each ARB record boundary.
    cycle_samples = int(math.ceil(max(64.0, 16 * (beta + 1), MIN_SAMPLE_RATE_HZ / tone) / 4)) * 4
    if cycle_samples > MAX_SAMPLES:
        raise ValueError("FM deviation/tone ratio requires more than 1,000,000 samples per cycle")
    sample_rate = tone * cycle_samples
    _number(sample_rate, "Derived FM sample rate (Sa/s)", MIN_SAMPLE_RATE_HZ,
            MAX_SAMPLE_RATE_HZ)
    cycles = max(1, int(math.ceil(8192 / cycle_samples)))
    count = cycles * cycle_samples
    if count > MAX_SAMPLES:
        raise ValueError("FM waveform exceeds 1,000,000 samples")
    phase = beta * np.sin(2 * np.pi * np.arange(count) / cycle_samples)
    iq = np.exp(1j * phase)
    summary = "FM sine | deviation {:.6g} kHz | tone {:.6g} kHz | Carson BW ~{:.6g} MHz".format(
        deviation / 1e3, tone / 1e3, bandwidth / 1e6)
    metadata = {"mode": "FM", "bandwidth_hz": bandwidth,
                "bandwidth_definition": "Carson estimate, 2 * (deviation + tone)",
                "deviation_hz": deviation, "tone_hz": tone, "modulation_index": beta,
                "samples_per_cycle": cycle_samples, "message_cycles": cycles,
                "source": "internal ARB IQ synthesis"}
    return iq, sample_rate, summary, metadata


def _ofdm(config, rng):
    bw = _number(config.bandwidth_hz, "Bandwidth (Hz)", 0, MAX_BANDWIDTH_HZ,
                 exclusive_min=True)
    nfft = _integer(config.ofdm_fft, "OFDM FFT size", 64, 4096)
    if nfft & (nfft - 1):
        raise ValueError("OFDM FFT size must be a power of two")
    active = _integer(config.ofdm_active, "Active OFDM carriers", 2, nfft - 2)
    if active % 2:
        raise ValueError("Active OFDM carriers must be even (DC is unused)")
    cp = _integer(config.ofdm_cp, "OFDM cyclic prefix (samples)", 0, nfft)
    constellation = str(config.ofdm_constellation).upper()
    if constellation not in ("QPSK", "16QAM", "64QAM"):
        raise ValueError("OFDM constellation must be QPSK, 16QAM, or 64QAM")
    spacing = bw / active
    sample_rate = spacing * nfft
    if sample_rate > MAX_SAMPLE_RATE_HZ:
        raise ValueError("With {}/{} active carriers, OFDM bandwidth must be <= {:.6g} MHz "
                         "for the 75 MSa/s ARB clock".format(
                             active, nfft, MAX_SAMPLE_RATE_HZ * active / nfft / 1e6))
    _number(sample_rate, "Derived OFDM sample rate (Sa/s)", MIN_SAMPLE_RATE_HZ,
            MAX_SAMPLE_RATE_HZ)
    frame_samples = nfft + cp
    # An integer number of complete OFDM frames; no zero padding at playback.
    count = max(16, int(math.ceil(32768 / frame_samples)))
    multiple = 4 // math.gcd(frame_samples, 4)
    count = int(math.ceil(count / multiple)) * multiple
    if count * frame_samples > MAX_SAMPLES:
        raise ValueError("OFDM waveform exceeds 1,000,000 samples")
    carriers = np.r_[np.arange(-active // 2, 0), np.arange(1, active // 2 + 1)] % nfft
    bins = np.zeros((count, nfft), dtype=np.complex128)
    bins[:, carriers] = _symbols(rng, count * active, constellation).reshape(count, active)
    frames = np.fft.ifft(bins, axis=1)
    if cp:
        frames = np.concatenate((frames[:, -cp:], frames), axis=1)
    iq = frames.reshape(-1)
    summary = "OFDM {} | nominal BW {:.6g} MHz | {}/{} carriers | CP {} | spacing {:.6g} kHz".format(
        constellation, bw / 1e6, active, nfft, cp, spacing / 1e3)
    metadata = {"mode": "OFDM", "bandwidth_hz": bw,
                "bandwidth_definition": "active carrier count times spacing (nominal)",
                "fft_size": nfft, "active_carriers": active, "cyclic_prefix_samples": cp,
                "subcarrier_spacing_hz": spacing, "constellation": constellation,
                "ofdm_symbols": count, "standard": "generic test signal; no protocol framing"}
    return iq, sample_rate, summary, metadata


def _normalise(iq):
    try:
        array = np.asarray(iq, dtype=np.complex128)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("IQ must contain finite complex numbers") from exc
    if array.ndim != 1 or not 60 <= array.size <= MAX_SAMPLES or array.size % 4:
        raise ValueError("IQ must be one-dimensional, 60..1,000,000 samples, and a multiple of four")
    if not np.isfinite(array).all():
        raise ValueError("IQ must contain finite complex numbers")
    # Scaled hypot avoids overflow for otherwise finite, very large inputs.
    largest_component = max(float(np.abs(array.real).max()), float(np.abs(array.imag).max()))
    if largest_component == 0:
        raise ValueError("IQ waveform must have nonzero energy")
    scaled = array / largest_component
    peak = float(np.abs(scaled).max())
    return (scaled * (PEAK_AMPLITUDE / peak)).astype(np.complex64)


def build_waveform(config):
    """Build normalized, repeatable IQ and its physical ARB sample clock.

    Irrelevant per-mode settings are ignored. A ValueError describes unsupported
    values before any instrument connection is needed. ``seed`` controls the
    data record; FM always uses a single sine message. The signed frequency
    offset is applied by the hardware NCO, preserving the exact upload record
    and sample clock. Its nominal band must fit inside +/-30 MHz.
    """
    if not isinstance(config, WaveformConfig):
        raise ValueError("Expected a WaveformConfig")
    mode = str(config.mode).upper()
    if mode not in MODES:
        raise ValueError("Mode must be one of " + ", ".join(MODES))
    seed = _integer(config.seed, "Random seed", 0, 2**32 - 1)
    offset = _number(config.frequency_offset_hz, "Frequency offset (Hz)",
                     -MAX_BASEBAND_EDGE_HZ, MAX_BASEBAND_EDGE_HZ)
    rng = np.random.default_rng(seed)
    if mode in SINGLE_CARRIER_MODES:
        iq, sample_rate, summary, metadata = _single_carrier(config, rng, mode)
    elif mode == "FM":
        iq, sample_rate, summary, metadata = _fm(config)
    else:
        iq, sample_rate, summary, metadata = _ofdm(config, rng)
    half_bandwidth = metadata["bandwidth_hz"] / 2
    maximum_offset = MAX_BASEBAND_EDGE_HZ - half_bandwidth
    if abs(offset) > maximum_offset:
        raise ValueError("Frequency offset must be within +/-{:.6g} MHz for this nominal bandwidth "
                         "to stay inside the option 653 +/-30 MHz baseband guard".format(
                             maximum_offset / 1e6))
    metadata.update({"frequency_offset_hz": offset,
                     "lower_edge_hz": offset - half_bandwidth,
                     "upper_edge_hz": offset + half_bandwidth})
    if offset:
        summary += " | offset {:+.6g} kHz".format(offset / 1e3)
    iq = _normalise(iq)
    power = np.abs(iq.astype(np.complex128)) ** 2
    metadata.update({"seed": seed, "sample_rate_hz": sample_rate, "samples": len(iq),
                     "duration_seconds": len(iq) / sample_rate, "peak_magnitude": PEAK_AMPLITUDE,
                     "rms": float(np.sqrt(power.mean())),
                     "papr_db": float(10 * np.log10(power.max() / power.mean()))})
    return Waveform(iq=iq, sample_rate_hz=float(sample_rate), summary=summary, metadata=metadata)


def to_scpi_iq_bytes(iq):
    """Return normalized interleaved I,Q, signed big-endian 16-bit samples.

    The caller wraps these bytes in an IEEE 488.2 definite-length binary block.
    N5172B waveform files use this fixed big-endian layout; FORM:BORD is not
    needed for the file download.
    Input arrays are never modified.
    """
    array = _normalise(iq)
    words = np.empty((len(array), 2), dtype=">i2")
    words[:, 0] = np.rint(array.real.astype(np.float64) * 32767).astype(np.int16)
    words[:, 1] = np.rint(array.imag.astype(np.float64) * 32767).astype(np.int16)
    return words.tobytes()
