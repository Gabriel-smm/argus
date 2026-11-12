"""mcls.infer with fake classifiers: no torch, no trained model."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mcls.contracts import WINDOW_SAMPLES
from mcls.infer import (
    UNKNOWN,
    BandPriors,
    Calibration,
    aggregate,
    burst_windows,
    classify_bursts,
    load_calibration,
    load_priors,
    window_logits,
)
from mcls.infer.loading import calibration_for, load_classifier
from mcls.infer.priors import parse_priors

CLASSES = ("drone_link", "wifi", "bluetooth", "background")
FS = 20e6


class FixedLogits:
    """Returns the same logits for every window; records what it saw."""

    classes = CLASSES

    def __init__(self, logits):
        self._logits = np.asarray(logits, dtype=np.float32)
        self.seen = []

    def logits(self, windows):
        self.seen.append(windows.copy())
        return np.tile(self._logits, (len(windows), 1))

    def classify(self, windows):  # pragma: no cover - logits() is preferred
        raise AssertionError("classify must not be called when logits exists")


class ProbsOnly:
    """A Classifier with classify() only, returning softmax(logits)."""

    classes = CLASSES

    def __init__(self, logits):
        z = np.asarray(logits, dtype=np.float64)
        self.p = np.exp(z - z.max()) / np.exp(z - z.max()).sum()

    def classify(self, windows):
        return np.tile(self.p, (len(windows), 1))


def tone(n, freq=1e6, amp=0.5):
    t = np.arange(n) / FS
    return (amp * np.exp(2j * np.pi * freq * t)).astype(np.complex64)


def softmax(z):
    z = np.asarray(z, dtype=np.float64)
    e = np.exp(z - z.max())
    return e / e.sum()


# -- import hygiene ----------------------------------------------------------


def test_import_does_not_load_torch():
    code = "import sys, mcls.infer; assert 'torch' not in sys.modules, 'torch imported'; print('ok')"
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


# -- windows ------------------------------------------------------------------


def test_burst_windows_shape_hop_cap_and_unit_rms():
    iq = tone(WINDOW_SAMPLES * 20, amp=0.01)
    w = burst_windows(iq, max_windows=8)
    assert w.shape == (8, WINDOW_SAMPLES) and w.dtype == np.complex64
    assert np.allclose(np.sqrt(np.mean(np.abs(w) ** 2, axis=1)), 1.0, atol=1e-5)
    # Few enough windows: every hop is kept.
    assert burst_windows(tone(WINDOW_SAMPLES + 2048 * 2), max_windows=8).shape[0] == 3


def test_short_burst_is_one_zero_padded_window_and_empty_is_none():
    w = burst_windows(tone(1000))
    assert w.shape == (1, WINDOW_SAMPLES)
    assert np.all(w[0, 1000:] == 0)
    assert burst_windows(np.zeros(0, np.complex64)).shape == (0, WINDOW_SAMPLES)


# -- logits -------------------------------------------------------------------


def test_logits_preferred_and_probs_only_equivalent_after_temperature():
    z = [2.0, 0.5, -1.0, 0.0]
    windows = burst_windows(tone(WINDOW_SAMPLES))  # one window: exact
    a = window_logits(FixedLogits(z), windows)
    b = window_logits(ProbsOnly(z), windows)
    for t in (0.5, 1.0, 2.5):
        pa = aggregate(a, CLASSES, temperature=t).probs
        pb = aggregate(b, CLASSES, temperature=t).probs
        assert pa == pytest.approx(pb, abs=1e-9)


def test_bad_classifier_output_is_refused():
    class Bad:
        classes = CLASSES

        def classify(self, windows):
            return np.ones((len(windows), 4))  # rows sum to 4

    with pytest.raises(ValueError):
        window_logits(Bad(), burst_windows(tone(WINDOW_SAMPLES)))


# -- aggregation: temperature, prior, threshold ---------------------------------


def test_temperature_softens_and_probs_sum_to_one():
    z = np.array([[3.0, 0.0, 0.0, 0.0]])
    sharp = aggregate(z, CLASSES, temperature=1.0)
    soft = aggregate(z, CLASSES, temperature=3.0)
    assert sharp.confidence == pytest.approx(softmax([3, 0, 0, 0])[0])
    assert soft.confidence == pytest.approx(softmax([1, 0, 0, 0])[0])
    assert sum(soft.probs.values()) == pytest.approx(1.0)


def test_prior_multiplies_and_renormalises():
    z = np.array([[1.0, 1.2, 0.0, 0.0]])
    prior = np.array([1.0, 0.05, 1.0, 1.0])
    out = aggregate(z, CLASSES, prior=prior)
    expected = softmax([1.0, 1.2, 0, 0]) * prior
    expected /= expected.sum()
    assert [out.probs[c] for c in CLASSES] == pytest.approx(list(expected))
    assert out.signal_class == "drone_link"  # wifi was on top before the prior


def test_window_logits_are_averaged_like_the_evaluator():
    z = np.array([[4.0, 0, 0, 0], [0, 4.0, 0, 0]])
    out = aggregate(z, CLASSES)
    assert out.probs["drone_link"] == pytest.approx(out.probs["wifi"])
    assert out.windows == 2
    # Mean of logits, not of log-softmax: these differ when window scales differ.
    z = np.array([[10.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 1.0, 0, 0]])
    out = aggregate(z, CLASSES, temperature=2.0)
    assert [out.probs[c] for c in CLASSES] == pytest.approx(list(softmax(z.mean(axis=0) / 2.0)))


def test_below_threshold_is_unknown_with_probs_kept():
    z = np.array([[0.2, 0.1, 0.0, 0.0]])
    out = aggregate(z, CLASSES, unknown_threshold=0.9)
    assert out.signal_class == UNKNOWN
    assert out.confidence < 0.9
    assert set(out.probs) == set(CLASSES)
    assert aggregate(z, CLASSES, unknown_threshold=0.1).signal_class == "drone_link"


def test_no_windows_is_unknown():
    out = aggregate(np.zeros((0, 4)), CLASSES, unknown_threshold=0.5)
    assert out.signal_class == UNKNOWN and out.windows == 0


# -- classify_bursts end to end ---------------------------------------------------


def test_classify_bursts_one_result_per_burst_with_prior_by_burst_frequency():
    rng = np.random.default_rng(0)
    iq = (0.001 * (rng.standard_normal(400_000) + 1j * rng.standard_normal(400_000))).astype(np.complex64)
    iq[50_000:150_000] = tone(100_000)
    iq[250_000:252_000] = tone(2_000)  # shorter than a window
    bursts = [
        {"start_s": 50_000 / FS, "end_s": 150_000 / FS, "center_frequency_hz": 2.437e9},
        {"start_s": 250_000 / FS, "end_s": 252_000 / FS, "center_frequency_hz": 98e6},
        {"start_s": 390_000 / FS, "end_s": None, "burst_duration_s": None, "center_frequency_hz": 5.0e9},
    ]
    priors = parse_priors({"band": [{"name": "fm", "lo_hz": 88e6, "hi_hz": 108e6, "source": "unsourced",
                                     "weights": {"wifi": 0.01}}]})
    clf = FixedLogits([0.0, 2.0, 0.0, 0.0])
    out = classify_bursts(iq, FS, 2.4e9, bursts, clf, calibration=Calibration(1.0, 0.5), priors=priors)
    assert [r.signal_class for r in out] == ["wifi", UNKNOWN, "wifi"]
    assert out[0].windows == 8  # capped
    assert out[1].windows == 1  # widened to one full window, not padded
    assert np.count_nonzero(clf.seen[1][0]) == WINDOW_SAMPLES
    assert out[2].windows >= 1  # truncated burst near the end still classified
    fields = out[0].row_fields()
    assert set(fields) == {"signal_class", "class_confidence", "class_probs"}
    json.dumps(fields)


def test_other_rates_go_through_the_resampler_with_burst_offset():
    calls = []

    def fake_resample(iq, fs, offset):
        calls.append((len(iq), fs, offset))
        return np.resize(iq, int(len(iq) * 20e6 / fs)).astype(np.complex64)

    iq = tone(400_000)
    burst = {"start_s": 0.001, "end_s": 0.002, "center_frequency_hz": 2.45e9}
    classify_bursts(iq, 40e6, 2.44e9, [burst], FixedLogits([1, 0, 0, 0]), resample=fake_resample)
    classify_bursts(iq, 10e6, 2.44e9, [burst], FixedLogits([1, 0, 0, 0]), resample=fake_resample)
    assert calls[0][1:] == (40e6, pytest.approx(10e6))  # wider: centred on the burst
    assert calls[1][1:] == (10e6, None)  # narrower: resampled only


# -- calibration, priors, loading ---------------------------------------------------


def test_load_calibration_reads_e8_format(tmp_path):
    (tmp_path / "calibration.json").write_text(json.dumps({
        "temperature": 1.7, "fit_split": "val",
        "unknown_threshold": {"score": "max_softmax", "value": 0.62, "keep_fraction": 0.95,
                              "applied_after_temperature": True},
    }))
    cal = load_calibration(tmp_path)
    assert (cal.temperature, cal.unknown_threshold) == (1.7, 0.62)
    (tmp_path / "model.pkl").write_bytes(b"")
    assert calibration_for(tmp_path / "model.pkl") == tmp_path / "calibration.json"


@pytest.mark.parametrize("bad", [
    {"temperature": 1.0},
    {"temperature": 0.0, "unknown_threshold": {"value": 0.5}},
    {"temperature": 1.0, "unknown_threshold": {"score": "neg_energy", "value": 0.5}},
])
def test_load_calibration_refuses_incomplete(tmp_path, bad):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_calibration(path)


def test_shipped_priors_load_and_are_soft():
    priors = load_priors()
    assert priors.bands, "configs/band_priors.toml is empty"
    for band in priors.bands:
        assert band.source == "unsourced" or band.source.startswith("https://www.ntia.gov/")
        assert all(0 < w <= 1 for w in band.weights.values())
    classes = ("drone_link", "wifi", "adsb")
    assert list(priors.for_frequency(98e6, classes)) == [0.05, 0.05, 0.05]
    assert list(priors.for_frequency(1090e6, classes)) == [0.05, 0.05, 1.0]
    assert list(priors.for_frequency(50e9, classes)) == [1.0, 1.0, 1.0]


@pytest.mark.parametrize("entry", [
    {"lo_hz": 1e6, "hi_hz": 2e6, "source": "unsourced", "weights": {"wifi": 0.0}},
    {"lo_hz": 1e6, "hi_hz": 2e6, "source": "", "weights": {}},
    {"lo_hz": 2e6, "hi_hz": 1e6, "source": "unsourced", "weights": {}},
])
def test_bad_priors_are_refused(entry):
    with pytest.raises(ValueError):
        parse_priors({"band": [entry]})


def test_empty_priors_change_nothing():
    assert list(BandPriors().for_frequency(98e6, CLASSES)) == [1.0] * 4


def test_load_classifier_errors_are_clear(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_classifier(tmp_path)
    (tmp_path / "x.onnx").write_bytes(b"")
    with pytest.raises(ValueError):
        load_classifier(tmp_path / "x.onnx")


def test_reads_calibration_written_by_the_evaluator(tmp_path):
    from mcls.evaluate import calibrate

    rng = np.random.default_rng(3)
    labels = rng.integers(0, 4, 400)
    logits = rng.normal(0, 1, (400, 4))
    logits[np.arange(400), labels] += 2.5
    meta = {"classes": list(CLASSES), "manifest_sha256": "0" * 64, "git_commit": "x", "seed": 0, "model": "fake",
            "created": "2026-11-12T00:00:00+00:00"}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    np.savez(tmp_path / "predictions_val.npz", window_id=np.array([f"w{i}" for i in range(400)]),
             recording_id=np.array([f"r{i % 20}" for i in range(400)]), label=labels.astype(np.int64),
             logits=logits.astype(np.float32), snr_db_est=np.full(400, np.nan, np.float32))
    written = calibrate.run(tmp_path)
    cal = load_calibration(tmp_path)
    assert cal.temperature == written["temperature"]
    assert cal.unknown_threshold == written["unknown_threshold"]["value"]
