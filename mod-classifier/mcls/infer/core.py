"""Bursts in, one class and a calibrated confidence per burst out.

Order of operations, per burst (PLAN 5.5 and 5.7):

1. Take the burst's samples, widened to at least one window when the burst is
   shorter, and bring them to 20 MS/s with Engineer 4's front end
   (`mcls.frontend.channelize.to_20msps`), centred on the burst when the
   recording is wider than 20 MHz. A 20 MS/s recording is used as it is.
2. Cut 4096-sample windows with a 2048-sample hop (the training windowing),
   keep at most `max_windows` spread evenly over the burst, normalise each to
   unit RMS.
3. Logits per window (`classifier.logits` when it has one, else
   log(`classifier.classify`)), divided by the temperature.
4. Average the windows' log-softmax, add log(band prior), softmax. This is the
   same as multiplying the averaged probabilities by the prior and
   renormalising.
5. Top probability under the threshold -> `unknown`.

Why `logits` first: Engineer 7's `classify` already divides by the temperature
stored in the checkpoint; dividing again by calibration.json's temperature
would apply it twice. A classifier with only `classify` gives probabilities,
whose logs are logits up to a constant, so step 3 is still exact.
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
#: Training cut at most 8 windows per burst (e4.md, --max-windows-per-burst default).
MAX_WINDOWS = 8

#: to_20msps(iq, sample_rate_hz, offset_hz) -> complex64 at SAMPLE_RATE_HZ
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


def _default_resampler(iq: np.ndarray, sample_rate_hz: float, offset_hz: float | None) -> np.ndarray:
    from mcls.frontend.channelize import to_20msps  # Engineer 4

    return to_20msps(iq, sample_rate_hz, offset_hz)


def to_rate(iq: np.ndarray, sample_rate_hz: float, offset_hz: float, resample: Resampler | None) -> np.ndarray:
    """Samples at 20 MS/s. Wider recordings are centred on `offset_hz` (the burst); narrower ones only resampled."""
    if sample_rate_hz == SAMPLE_RATE_HZ:
        return np.ascontiguousarray(iq, dtype=SAMPLE_DTYPE)
    resample = resample or _default_resampler
    offset = offset_hz if sample_rate_hz > SAMPLE_RATE_HZ else None
    return np.ascontiguousarray(resample(iq, sample_rate_hz, offset), dtype=SAMPLE_DTYPE)


def normalize(windows: np.ndarray) -> np.ndarray:
    """Each window scaled to unit RMS; an all-zero window stays zero."""
    rms = np.sqrt(np.mean(np.abs(windows) ** 2, axis=1, keepdims=True))
    return (windows / np.where(rms > 0, rms, 1.0)).astype(SAMPLE_DTYPE)


def burst_windows(iq20: np.ndarray, max_windows: int = MAX_WINDOWS) -> np.ndarray:
    """(n, 4096) unit-RMS windows over a 20 MS/s stretch; one zero-padded window when it is shorter."""
    n = len(iq20)
    if n == 0:
        return np.zeros((0, WINDOW_SAMPLES), dtype=SAMPLE_DTYPE)
    if n < WINDOW_SAMPLES:
        padded = np.zeros(WINDOW_SAMPLES, dtype=SAMPLE_DTYPE)
        padded[:n] = iq20
        return normalize(padded[None, :])
    starts = np.arange(0, n - WINDOW_SAMPLES + 1, HOP)
    if len(starts) > max_windows:
        starts = starts[np.round(np.linspace(0, len(starts) - 1, max_windows)).astype(int)]
    return normalize(np.stack([iq20[s : s + WINDOW_SAMPLES] for s in starts]))


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
    """One burst's class from its windows' logits (n, K): temperature, mean log-prob, prior, threshold."""
    classes = tuple(classes)
    if len(logits) == 0:
        uniform = 1.0 / len(classes)
        return BurstClass(UNKNOWN, uniform, {c: uniform for c in classes}, 0)
    score = _log_softmax(np.asarray(logits, dtype=np.float64) / temperature).mean(axis=0)
    if prior is not None:
        score = score + np.log(np.asarray(prior, dtype=np.float64))
    probs = np.exp(_log_softmax(score))
    top = int(np.argmax(probs))
    confidence = float(probs[top])
    name = classes[top] if unknown_threshold is None or confidence >= unknown_threshold else UNKNOWN
    return BurstClass(name, confidence, {c: float(p) for c, p in zip(classes, probs)}, len(logits))


def _span(burst: dict, sample_rate_hz: float, total: int) -> tuple[int, int]:
    """Native-rate sample range of a burst, widened around its middle to cover at least one window."""
    start = max(0, int(math.floor(burst.get("start_s", 0.0) * sample_rate_hz)))
    end_s = burst.get("end_s")
    if end_s is None and burst.get("burst_duration_s") is not None:
        end_s = burst.get("start_s", 0.0) + burst["burst_duration_s"]
    if end_s is None:
        # Unknown end (a truncated burst): enough for MAX_WINDOWS windows from the start.
        end = start + int(math.ceil((WINDOW_SAMPLES + (MAX_WINDOWS - 1) * HOP) * sample_rate_hz / SAMPLE_RATE_HZ))
    else:
        end = int(math.ceil(end_s * sample_rate_hz))
    end = min(total, max(end, start + 1))
    # One window at 20 MS/s, plus a little for the resampler's edges.
    need = int(math.ceil(WINDOW_SAMPLES * sample_rate_hz / SAMPLE_RATE_HZ)) + 64
    if end - start < need:
        middle = (start + end) // 2
        start = max(0, middle - need // 2)
        end = min(total, start + need)
        start = max(0, end - need)
    return start, end


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
    for burst in bursts:
        lo, hi = _span(burst, sample_rate_hz, len(iq))
        burst_hz = float(burst.get("center_frequency_hz", center_frequency_hz))
        iq20 = to_rate(iq[lo:hi], sample_rate_hz, burst_hz - center_frequency_hz, resample)
        windows = burst_windows(iq20, max_windows)
        logits = window_logits(classifier, windows) if len(windows) else np.zeros((0, len(classes)))
        prior = priors.for_frequency(burst_hz, classes) if priors is not None else None
        results.append(aggregate(logits, classes, temperature=calibration.temperature, prior=prior,
                                 unknown_threshold=calibration.unknown_threshold))
    return results
