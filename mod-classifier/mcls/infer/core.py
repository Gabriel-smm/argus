"""Bursts in, one class and a calibrated confidence per burst out.

Order of operations, per burst (PLAN 5.5 and 5.7):

1. Take the burst's samples plus one window of context each side and bring
   them to 20 MS/s with Engineer 4's `Channelizer`, centred on the burst when
   the recording is wider than 20 MHz (narrower ones are only resampled, as in
   training). The resampler's start-up lag is taken into account when mapping
   the burst's times to 20 MS/s sample indices.
2. Cut windows with Engineer 4's `burst_windows` (4096 samples, hop 2048, the
   activity test, at most `max_windows` spread over the burst) and normalise
   them to unit RMS (`cut`). The activity test's floor comes from the excerpt,
   not from a 0.21 s block as in training; when it rejects every window, the
   burst's windows are used unfiltered so every burst gets a class.
3. Logits per window (`classifier.logits` when it has one, else
   log(`classifier.classify`)), divided by the temperature.
4. Average the windows' logits (as Engineer 8's burst-level evaluation does,
   `mcls.evaluate.metrics.burst_logits`), softmax, multiply by the band prior
   and renormalise.
5. Top probability under the threshold -> `unknown`.

Why `logits` first: Engineer 7's `classify` already divides by the temperature
stored in the checkpoint; dividing again by calibration.json's temperature
would apply it twice. A classifier with only `classify` gives probabilities;
their logs are its logits minus a per-window constant, so a single window is
exact and a multi-window average equals the mean of log-probabilities.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from mcls.contracts import SAMPLE_DTYPE, SAMPLE_RATE_HZ, WINDOW_SAMPLES, Classifier, check_probabilities, check_windows
from mcls.infer.calibration import Calibration
from mcls.infer.priors import BandPriors

UNKNOWN = "unknown"
#: Training windows overlap by half (Engineer 4, e4.md).
HOP = WINDOW_SAMPLES // 2
#: Windows per burst at inference, for latency (PLAN 6.2: 50 ms per burst). Training keeps
#: up to 64 (e4's default); burst-level evaluation should use the same cap as here.
MAX_WINDOWS = 8

#: For tests: resample(iq, sample_rate_hz, offset_hz) -> complex64 at SAMPLE_RATE_HZ, assumed lag-free.
Resampler = Callable[[np.ndarray, float, float | None], np.ndarray]


@dataclass
class BurstClass:
    signal_class: str
    confidence: float
    probs: dict[str, float] = field(default_factory=dict)
    windows: int = 0

    def row_fields(self, digits: int = 4) -> dict:
        """The three fields `pipeline.ingest --classify` adds to a row."""
        return {
            "signal_class": self.signal_class,
            "class_confidence": round(self.confidence, digits),
            "class_probs": {name: round(p, digits) for name, p in self.probs.items()},
        }


def to_rate(iq: np.ndarray, sample_rate_hz: float, offset_hz: float,
            resample: Resampler | None = None) -> tuple[np.ndarray, Callable[[float], float]]:
    """(samples at 20 MS/s, map from an input sample index to the matching 20 MS/s index).

    Wider recordings are centred on `offset_hz` (the burst); narrower ones only
    resampled, as Engineer 4's front end does in training.
    """
    ratio = SAMPLE_RATE_HZ / sample_rate_hz
    if sample_rate_hz == SAMPLE_RATE_HZ:
        return np.ascontiguousarray(iq, dtype=SAMPLE_DTYPE), lambda s: float(s)
    offset = offset_hz if sample_rate_hz > SAMPLE_RATE_HZ else 0.0
    if resample is not None:
        return np.ascontiguousarray(resample(iq, sample_rate_hz, offset or None), dtype=SAMPLE_DTYPE), lambda s: s * ratio
    from mcls.frontend.channelize import Channelizer  # Engineer 4

    ch = Channelizer(sample_rate_hz, offset)
    out = np.concatenate([ch.process(np.asarray(iq, dtype=SAMPLE_DTYPE)), ch.flush()])
    r = ch.resampler
    if r is None:
        return out, lambda s: s * ratio
    # Output m sits at upsampled index first_j + m * down, i.e. input sample (first_j + m * down - delay) / up
    # (mcls.frontend.resample.RationalResampler); the start-up transient is dropped.
    ntaps = len(r.taps)
    first_j = -(-(ntaps - 1) // r.down) * r.down
    delay = (ntaps - 1) / 2
    return out, lambda s: (s * r.up + delay - first_j) / r.down


def normalize(windows: np.ndarray) -> np.ndarray:
    """Each window scaled to unit RMS; an all-zero window stays zero."""
    rms = np.sqrt(np.mean(np.abs(windows) ** 2, axis=1, keepdims=True))
    return (windows / np.where(rms > 0, rms, 1.0)).astype(SAMPLE_DTYPE)


def burst_windows(iq20: np.ndarray, start: int | None = None, end: int | None = None,
                  max_windows: int = MAX_WINDOWS) -> np.ndarray:
    """(n, 4096) unit-RMS windows of the burst iq20[start:end], cut as Engineer 4 cuts training windows.

    Falls back to the unfiltered windows when the activity test rejects all, and
    to one zero-padded window when iq20 is shorter than a window.
    """
    from mcls.frontend import windows as W  # Engineer 4

    n = len(iq20)
    if n == 0:
        return np.zeros((0, WINDOW_SAMPLES), dtype=SAMPLE_DTYPE)
    if n < WINDOW_SAMPLES:
        padded = np.zeros(WINDOW_SAMPLES, dtype=SAMPLE_DTYPE)
        padded[:n] = iq20
        return normalize(padded[None, :])
    start = 0 if start is None else int(min(max(start, 0), n))
    end = n if end is None else int(min(max(end, start), n))
    burst = {"start": start, "end": end}
    wins, _ = W.burst_windows(iq20, [burst], max_windows)
    if not wins:
        starts = W.burst_starts(start, end, n, n)
        if len(starts) > max_windows:
            starts = [starts[i] for i in np.unique(np.linspace(0, len(starts) - 1, max_windows).round().astype(int))]
        wins = [W.Window(s, burst) for s in starts]
    return W.cut(iq20, wins)


def window_logits(classifier: Classifier, windows: np.ndarray) -> np.ndarray:
    """(n, K) logits before temperature."""
    check_windows(windows)
    logits = getattr(classifier, "logits", None)
    if callable(logits):
        out = np.asarray(logits(windows), dtype=np.float64)
        if out.shape != (len(windows), len(classifier.classes)) or not np.isfinite(out).all():
            raise ValueError(f"classifier.logits returned {out.shape}, expected {(len(windows), len(classifier.classes))} finite")
        return out
    probs = np.asarray(classifier.classify(windows), dtype=np.float64)
    check_probabilities(probs, len(windows), tuple(classifier.classes))
    return np.log(np.clip(probs, 1e-12, None))


def _log_softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(axis=-1, keepdims=True)
    return x - np.log(np.exp(x).sum(axis=-1, keepdims=True))


def aggregate(logits: np.ndarray, classes: Sequence[str], *, temperature: float = 1.0,
              prior: np.ndarray | None = None, unknown_threshold: float | None = None) -> BurstClass:
    """One burst's class from its windows' logits (n, K): temperature, mean logits, prior, threshold."""
    classes = tuple(classes)
    if len(logits) == 0:
        uniform = 1.0 / len(classes)
        return BurstClass(UNKNOWN, uniform, {c: uniform for c in classes}, 0)
    score = (np.asarray(logits, dtype=np.float64) / temperature).mean(axis=0)
    if prior is not None:
        score = score + np.log(np.asarray(prior, dtype=np.float64))
    probs = np.exp(_log_softmax(score))
    top = int(np.argmax(probs))
    confidence = float(probs[top])
    name = classes[top] if unknown_threshold is None or confidence >= unknown_threshold else UNKNOWN
    return BurstClass(name, confidence, {c: float(p) for c, p in zip(classes, probs)}, len(logits))


def _span(burst: dict, sample_rate_hz: float, total: int) -> tuple[int, int]:
    """Native-rate sample range [start, end) of a burst."""
    start = min(total, max(0, int(math.floor(burst.get("start_s", 0.0) * sample_rate_hz))))
    end_s = burst.get("end_s")
    if end_s is None and burst.get("burst_duration_s") is not None:
        end_s = burst.get("start_s", 0.0) + burst["burst_duration_s"]
    if end_s is None:
        # Unknown end (a truncated burst): enough for MAX_WINDOWS windows from the start.
        end = start + int(math.ceil((WINDOW_SAMPLES + (MAX_WINDOWS - 1) * HOP) * sample_rate_hz / SAMPLE_RATE_HZ))
    else:
        end = int(math.ceil(end_s * sample_rate_hz))
    return start, min(total, max(end, start + 1))


def classify_bursts(iq: np.ndarray, sample_rate_hz: float, center_frequency_hz: float, bursts: Sequence[dict],
                    classifier: Classifier, *, calibration: Calibration | None = None,
                    priors: BandPriors | None = None, max_windows: int = MAX_WINDOWS,
                    resample: Resampler | None = None) -> list[BurstClass]:
    """One BurstClass per burst, in order.

    `bursts` are `detect_bursts(iq, sample_rate_hz, center_frequency_hz)` dicts:
    `start_s`, `end_s` (or `burst_duration_s`; neither means "runs on") and
    `center_frequency_hz` (the burst's RF centre, used for the band prior and to
    centre the 20 MHz slice).
    """
    calibration = calibration or Calibration()
    classes = tuple(classifier.classes)
    results = []
    # Context each side: one window at 20 MS/s plus room for the resampler's start-up transient.
    pad = int(math.ceil(WINDOW_SAMPLES * sample_rate_hz / SAMPLE_RATE_HZ)) + 256
    for burst in bursts:
        lo, hi = _span(burst, sample_rate_hz, len(iq))
        ctx_lo, ctx_hi = max(0, lo - pad), min(len(iq), hi + pad)
        burst_hz = float(burst.get("center_frequency_hz", center_frequency_hz))
        iq20, index = to_rate(iq[ctx_lo:ctx_hi], sample_rate_hz, burst_hz - center_frequency_hz, resample)
        start20 = int(math.floor(index(lo - ctx_lo)))
        end20 = int(math.ceil(index(hi - ctx_lo)))
        windows = burst_windows(iq20, start20, end20, max_windows)
        logits = window_logits(classifier, windows) if len(windows) else np.zeros((0, len(classes)))
        prior = priors.for_frequency(burst_hz, classes) if priors is not None else None
        results.append(aggregate(logits, classes, temperature=calibration.temperature, prior=prior,
                                 unknown_threshold=calibration.unknown_threshold))
    return results
