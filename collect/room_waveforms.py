"""Generator waveforms that imitate signals found in an ordinary room, for the
classes the N5172B package does not make:

- GFSK: Bluetooth-like. Gaussian frequency shift keying in short packets, each
  packet optionally on a different frequency (hopping).
- OOK: key-fob-like. On-off keying of a carrier at a few kbit/s, in short bursts.
- OFDM_BURST: Wi-Fi-like. The package's OFDM signal, cut into packets with gaps.

They are imitations, not standard-compliant signals (no Bluetooth or Wi-Fi
framing). Each returns the package's Waveform, so the controller uploads it
like any other.
"""

from dataclasses import dataclass

import numpy as np

from collect.siggen.n5172b_waveforms import (MAX_SAMPLES, Waveform, WaveformConfig,
                                             _normalise, build_waveform)

ROOM_MODES = ("GFSK", "OOK", "OFDM_BURST")
EDGE_S = 2e-6  # packet ramp-up and ramp-down


@dataclass(frozen=True)
class RoomConfig:
    mode: str = "GFSK"
    symbol_rate_hz: float = 1e6   # GFSK symbols per second (Bluetooth: 1e6)
    bt: float = 0.5               # GFSK Gaussian filter bandwidth-time product
    mod_index: float = 0.32       # GFSK modulation index (classic Bluetooth: 0.32)
    hop_hz: float = 0.0           # GFSK packets hop within +/- this
    bit_rate_hz: float = 4e3      # OOK bit rate
    bandwidth_hz: float = 10e6    # OFDM_BURST nominal bandwidth
    packet_s: float = 400e-6      # length of one packet
    duty: float = 0.3             # fraction of time a packet is on air
    packets: int = 8              # packets in one generator loop
    frequency_offset_hz: float = 0.0
    seed: int = 1


ROOM_FIELDS = {name for name in RoomConfig.__dataclass_fields__}


def _gaps(rng, config, rate):
    """Random gap lengths (samples) averaging the requested duty cycle."""
    mean_gap = config.packet_s * (1 / config.duty - 1)
    return np.round(rng.uniform(0.5, 1.5, config.packets) * mean_gap * rate).astype(int)


def _ramp(n, rate):
    edge = min(n // 2, max(1, round(EDGE_S * rate)))
    window = np.ones(n)
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, edge))
    window[:edge], window[n - edge:] = ramp, ramp[::-1]
    return window


def _assemble(packets, gaps):
    parts = []
    for packet, gap in zip(packets, gaps):
        parts += [packet, np.zeros(gap, dtype=complex)]
    iq = np.concatenate(parts)
    iq = iq[:len(iq) // 4 * 4]
    if len(iq) > MAX_SAMPLES:
        raise ValueError("Waveform needs more than 1,000,000 samples; use fewer or shorter packets")
    return iq


def _gfsk(config, rng):
    sps = 8
    hop = abs(config.hop_hz)
    bw = config.symbol_rate_hz * (1 + config.mod_index)
    # Without hopping 8 samples per symbol is enough; with hopping the sample rate
    # must cover the whole hop range.
    rate = max(sps * config.symbol_rate_hz, 2.5 * (hop + bw))
    sps = rate / config.symbol_rate_hz
    t = np.arange(-2, 2, 1 / sps)
    sigma = np.sqrt(np.log(2)) / (2 * np.pi * config.bt)
    gauss = np.exp(-t ** 2 / (2 * sigma ** 2))
    gauss /= gauss.sum()
    n = round(config.packet_s * rate)
    packets = []
    for _ in range(config.packets):
        bits = rng.integers(0, 2, int(np.ceil(n / sps)) + 1) * 2 - 1
        freq = np.convolve(np.repeat(bits, int(np.ceil(sps)))[:n], gauss, mode="same")
        phase = np.pi * config.mod_index * np.cumsum(freq) / sps
        if hop:
            phase += 2 * np.pi * rng.uniform(-hop, hop) * np.arange(n) / rate
        packets.append(np.exp(1j * phase) * _ramp(n, rate))
    meta = {"symbol_rate_hz": config.symbol_rate_hz, "bt": config.bt,
            "mod_index": config.mod_index, "hop_hz": hop}
    return _assemble(packets, _gaps(rng, config, rate)), rate, bw, hop + bw / 2, meta


def _ook(config, rng):
    sps = 32
    rate = sps * config.bit_rate_hz
    bits_per_packet = max(8, round(config.packet_s * config.bit_rate_hz))
    edge = max(1, sps // 8)
    shape = np.convolve(np.ones(edge) / edge, np.ones(1), mode="full")
    packets = []
    for _ in range(config.packets):
        bits = rng.integers(0, 2, bits_per_packet)
        bits[:4] = [1, 0, 1, 0]  # preamble, so every packet has energy
        envelope = np.convolve(np.repeat(bits, sps).astype(float), shape, mode="same")
        packets.append(envelope.astype(complex))
    bw = 4 * config.bit_rate_hz
    meta = {"bit_rate_hz": config.bit_rate_hz}
    return _assemble(packets, _gaps(rng, config, rate)), rate, bw, bw / 2, meta


def _ofdm_burst(config, rng):
    base = build_waveform(WaveformConfig(mode="OFDM", bandwidth_hz=config.bandwidth_hz,
                                         seed=config.seed))
    rate = base.sample_rate_hz
    n = round(config.packet_s * rate)
    source = np.tile(base.iq.astype(complex), int(np.ceil(n * config.packets / len(base.iq))) + 1)
    packets = []
    for k in range(config.packets):
        start = rng.integers(0, len(source) - n)
        packets.append(source[start:start + n] * _ramp(n, rate))
    meta = {"ofdm": {k: base.metadata[k] for k in ("fft_size", "active_carriers")
                     if k in base.metadata}}
    bw = config.bandwidth_hz
    return _assemble(packets, _gaps(rng, config, rate)), rate, bw, bw / 2, meta


def build_room_waveform(config):
    mode = config.mode.upper()
    if mode not in ROOM_MODES:
        raise ValueError("Room mode must be one of " + ", ".join(ROOM_MODES))
    if not 0 < config.duty <= 1:
        raise ValueError("duty must be in (0, 1]")
    rng = np.random.default_rng(config.seed)
    builder = {"GFSK": _gfsk, "OOK": _ook, "OFDM_BURST": _ofdm_burst}[mode]
    iq, rate, bw, half_span, meta = builder(config, rng)
    offset = float(config.frequency_offset_hz)
    iq = _normalise(iq)
    metadata = dict(meta, mode=mode, bandwidth_hz=float(bw), frequency_offset_hz=offset,
                    lower_edge_hz=offset - half_span, upper_edge_hz=offset + half_span,
                    packet_s=config.packet_s, duty=config.duty, packets=config.packets,
                    seed=config.seed, sample_rate_hz=float(rate), samples=len(iq),
                    duration_seconds=len(iq) / rate)
    summary = "{} | BW {:.3g} MHz | packets {:.3g} ms at duty {:.2g}".format(
        mode, bw / 1e6, config.packet_s * 1e3, config.duty)
    return Waveform(iq=iq, sample_rate_hz=float(rate), summary=summary, metadata=metadata)
