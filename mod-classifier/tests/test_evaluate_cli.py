"""End to end on a fake run folder built to the PROTOCOL run-output contract.

Synthetic logits stand in for a model here only; no report uses them.
"""

import hashlib
import json

import numpy as np
import pytest

from mcls import manifest as manifest_mod
from mcls.contracts import WINDOW_SAMPLES, ManifestRow
from mcls.evaluate import calibrate as C
from mcls.evaluate.__main__ import compare, evaluate_run, main
from mcls.evaluate.runio import burst_keys, load_predictions

CLASSES = ["drone_link", "wifi", "bluetooth", "background"]


def _row(window_id, recording, split, label, shard, offset, snr, is_real=True):
    stats = (None, None, None) if snr is None else (snr, 1e6, 0.5)
    return ManifestRow(
        window_id=window_id, shard=shard, offset=offset, length=WINDOW_SAMPLES, dataset="fake",
        recording_id=recording, label=label, label_strength="strong", native_rate_hz=20e6,
        center_frequency_hz=2.44e9, band="ism_2400", is_real=is_real, license="CC-BY-4.0", split=split,
        snr_db_est=stats[0], bandwidth_hz=stats[1], duty_cycle=stats[2])


def _build(tmp_path, synthetic_train=0, name="run", seed=0):
    """Manifest with val/test/cross_test windows; each recording holds 2 bursts of 3 windows."""
    rng = np.random.default_rng(seed)
    rows, preds = [], {}
    for split in ("train", "val", "test", "cross_test"):
        ids, recs, labels, logits, snrs = [], [], [], [], []
        for c, label in enumerate(CLASSES):
            for r in range(4):
                rec = f"{split}-{label}-{r}"
                for b in range(2):
                    snr = None if label == "background" else float(5 * b + r)
                    for w in range(3):
                        k = b * 3 + w
                        wid = f"fake/{rec}/{k:06d}"
                        rows.append(_row(wid, rec, split, label, f"{rec}.s000.npy", k * WINDOW_SAMPLES, snr))
                        z = rng.normal(size=len(CLASSES))
                        z[c] += 3.0
                        ids.append(wid); recs.append(rec); labels.append(c); logits.append(z * 2.0)
                        snrs.append(np.nan if snr is None else snr)
        preds[split] = dict(window_id=np.array(ids), recording_id=np.array(recs), label=np.array(labels, np.int64),
                            logits=np.array(logits, np.float32), snr_db_est=np.array(snrs, np.float32))
    for i in range(synthetic_train):
        rows.append(_row(f"fake/syn/{i:06d}", "syn", "train", "drone_link", "syn.npy", i * WINDOW_SAMPLES, 1.0, False))
    mpath = tmp_path / "manifest.jsonl"
    manifest_mod.write(mpath, rows)
    run = tmp_path / name
    run.mkdir()
    sha = hashlib.sha256(mpath.read_bytes()).hexdigest()
    (run / "meta.json").write_text(json.dumps({"git_commit": "abc", "manifest_sha256": sha, "seed": seed,
                                               "classes": CLASSES, "model": "fake", "created": "now"}))
    for split in ("val", "test", "cross_test"):
        np.savez(run / f"predictions_{split}.npz", **preds[split])
    return run, mpath, preds


def test_burst_keys_split_on_stats_change(tmp_path):
    rows = [_row(f"w{k}", "r", "test", "wifi", "s.npy", k * WINDOW_SAMPLES, 1.0 if k < 3 else 2.0) for k in range(6)]
    rows += [_row(f"b{k}", "r", "test", "background", "s.npy", (6 + k) * WINDOW_SAMPLES, None) for k in range(2)]
    keys = burst_keys(rows)
    assert len({keys[f"w{k}"] for k in range(3)}) == 1
    assert keys["w0"] != keys["w3"]
    assert keys["b0"] != keys["b1"]  # idle windows are one-window groups
    assert len(set(keys.values())) == 4


def test_calibrate_then_evaluate(tmp_path):
    run, mpath, _ = _build(tmp_path)
    assert C.main(["--run", str(run)]) == 0
    cal = json.loads((run / "calibration.json").read_text())
    assert cal["temperature"] > 0 and cal["ece_after"] <= cal["ece_before"]
    assert cal["unknown_threshold"]["val_kept"] >= 0.95
    assert set(cal["held_out"]) == {"test", "cross_test"}
    assert "false_alarm_at_threshold" in cal["held_out"]["test"]
    assert main(["--run", str(run), "--manifest", str(mpath)]) == 0
    m = json.loads((run / "metrics.json").read_text())
    assert set(m["splits"]) == {"test", "cross_test"}
    test = m["splits"]["test"]
    assert test["n_windows"] == 4 * 4 * 6 and test["real_only_verified"]
    # 3 burst classes x 4 recordings x 2 bursts, plus 24 idle background windows as single groups
    assert test["burst"]["n"] == 24 + 24
    assert test["recording"]["n"] == 16
    assert test["accuracy_vs_snr"]["n_snr_unknown"] == 4 * 6
    assert "at_unknown_threshold" in test["false_alarm_background"]
    assert [r["split"] for r in m["side_by_side"]] == ["cross_test", "test"]
    assert m["manifest"]["leakage"]["ok"] is True
    assert m["training_rows"] == {"real": 96, "synthetic": 0, "synthetic_in_training": False}
    assert m["gate_inputs"]["ece_after"] is not None
    assert all(g["pass"] in (True, False, None) for g in m["gates"])


def test_drops_rows_not_real_from_test(tmp_path):
    run, mpath, _ = _build(tmp_path)
    rows = manifest_mod.read(mpath)
    for r in rows:
        if r.split == "test" and r.label == "wifi":
            r.is_real = False
    manifest_mod.write(mpath, rows)
    meta = json.loads((run / "meta.json").read_text())
    meta["manifest_sha256"] = hashlib.sha256(mpath.read_bytes()).hexdigest()[:16]  # short digest form
    (run / "meta.json").write_text(json.dumps(meta))
    m = evaluate_run(run, mpath, plots=False)
    t = m["splits"]["test"]
    assert t["n_dropped_not_real"] == 24
    assert t["window"]["per_class"]["wifi"]["support"] == 0


def test_manifest_hash_mismatch_is_refused(tmp_path):
    run, mpath, _ = _build(tmp_path)
    mpath.write_text(mpath.read_text() + "\n")
    with pytest.raises(ValueError, match="does not match"):
        evaluate_run(run, mpath, plots=False)
    assert main(["--run", str(run), "--manifest", str(mpath)]) == 2


def test_without_manifest_reports_nothing(tmp_path, capsys):
    # A run holding simulated rows must never get headline numbers unchecked.
    run, _, _ = _build(tmp_path)
    with pytest.raises(ValueError, match="--manifest is required"):
        evaluate_run(run, None, plots=False)
    assert main(["--run", str(run)]) == 2
    assert "--manifest is required" in capsys.readouterr().err
    assert not (run / "metrics.json").exists()
    # comparison of several runs is refused the same way
    assert main(["--run", str(run), "--run", str(run)]) == 2
    assert not (run / "comparison.json").exists()


def test_comparison_of_runs_with_and_without_synthetic(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, mpath_a, _ = _build(tmp_path / "a", name="real_only")
    b, mpath_b, _ = _build(tmp_path / "b", synthetic_train=5, name="with_syn", seed=1)
    ma = evaluate_run(a, mpath_a, plots=False)
    mb = evaluate_run(b, mpath_b, plots=False)
    table = compare([ma, mb])
    assert table["same_manifest"] is False
    assert table["with_synthetic_training_rows"] == [str(b)]
    assert table["without_synthetic_training_rows"] == [str(a)]
    assert table["table"][0]["test_window_macro_f1"] is not None


def test_contract_violations_are_reported(tmp_path):
    run, _, preds = _build(tmp_path)
    bad = dict(preds["test"])
    bad["logits"] = bad["logits"][:, :3]
    np.savez(run / "predictions_test.npz", **bad)
    with pytest.raises(ValueError, match="logits shape"):
        load_predictions(run / "predictions_test.npz", len(CLASSES))
    del bad["snr_db_est"]
    np.savez(run / "predictions_test.npz", **bad)
    with pytest.raises(ValueError, match="missing arrays"):
        load_predictions(run / "predictions_test.npz", len(CLASSES))


def test_calibrate_needs_val(tmp_path):
    run, _, _ = _build(tmp_path)
    (run / "predictions_val.npz").unlink()
    assert C.main(["--run", str(run)]) == 2
