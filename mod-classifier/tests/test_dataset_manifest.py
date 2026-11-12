import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from mcls import manifest
from mcls.contracts import WINDOW_SAMPLES
from mcls.dataset import (
    WindowStore,
    audit_window_hashes,
    build,
    cap_per_class,
    collect_rows,
    holdout_emitters,
    label_indices,
    row_weights,
)
from mcls.dataset import build_manifest
from mcls.dataset.fakes import make_fake_shards


@pytest.fixture
def shards(tmp_path):
    make_fake_shards(tmp_path / "a", seed=1, dataset="ds_a", recordings_per_class=6)
    make_fake_shards(tmp_path / "b", seed=2, dataset="ds_b", recordings_per_class=3, emitters=())
    return [tmp_path / "a", tmp_path / "b"]


def test_collect_resolves_relative_shards_and_sorts(shards):
    rows = collect_rows(shards)
    assert len(rows) == (6 + 3) * 2 * 6
    assert [r.window_id for r in rows] == sorted(r.window_id for r in rows)
    assert all(Path(r.shard).is_absolute() and Path(r.shard).exists() for r in rows)


def test_collect_reads_front_end_rows_without_split(tmp_path):
    # e4.md: rows files are <stem>.sNNN.rows.jsonl with every ManifestRow field except "split".
    make_fake_shards(tmp_path, dataset="ds")
    rows_file = sorted(tmp_path.glob("*.s000.rows.jsonl"))[0]
    assert "split" not in json.loads(rows_file.read_text().splitlines()[0])
    # Other .jsonl files (a manifest written into the same folder) are not front-end rows.
    (tmp_path / "manifest.jsonl").write_text('{"not": "a row"}\n')
    rows = collect_rows([tmp_path])
    assert len(rows) == 2 * 4 * 6 and {r.split for r in rows} == {"train"}


def test_collect_rejects_duplicate_window_ids(tmp_path):
    make_fake_shards(tmp_path / "a", dataset="same")
    make_fake_shards(tmp_path / "b", dataset="same")
    with pytest.raises(ValueError, match="appears in"):
        collect_rows([tmp_path / "a", tmp_path / "b"])


def test_cap_per_class_per_dataset_is_deterministic_and_order_free(shards):
    rows = collect_rows(shards)
    capped = cap_per_class(rows, 10, seed=3)
    counts = Counter((r.dataset, r.label) for r in capped)
    assert counts[("ds_a", "drone_link")] == 10 and counts[("ds_b", "wifi")] == 10
    again = cap_per_class(list(reversed(rows)), 10, seed=3)
    assert [r.window_id for r in again] == [r.window_id for r in capped]
    other = cap_per_class(rows, 10, seed=4)
    assert [r.window_id for r in other] != [r.window_id for r in capped]
    assert len(cap_per_class(rows, 0, seed=3)) == len(rows)


def test_build_splits_by_recording_and_cross_test(shards):
    rows = build(shards, seed=5, cross_test=["ds_b"], cap=0)
    manifest.check_leakage(rows)
    assert {r.split for r in rows if r.dataset == "ds_b"} == {"cross_test"}
    by_recording = {}
    for r in rows:
        by_recording.setdefault(r.recording_id, set()).add(r.split)
    assert all(len(s) == 1 for s in by_recording.values())


def test_holdout_emitter_moves_whole_model(shards):
    rows = build(shards, seed=5, cap=0, holdout=["model_a"], holdout_split="test")
    held = [r for r in rows if r.emitter_id == "model_a"]
    assert held and {r.split for r in held} == {"test"}
    assert any(r.split == "train" and r.emitter_id == "model_b" for r in rows)


def test_holdout_by_recording_substring(shards):
    rows = collect_rows(shards)
    moved = holdout_emitters(rows, ["ds_b_wifi"], split="val", match="recording")
    assert moved == 3 * 6
    assert {r.split for r in rows if "ds_b_wifi" in r.recording_id} == {"val"}


def test_holdout_unknown_emitter_is_an_error(shards):
    with pytest.raises(ValueError, match="no rows match"):
        build(shards, seed=5, cap=0, holdout=["nope"])


def test_hash_audit_finds_identical_windows_across_splits(shards):
    rows = build(shards, seed=5, cap=0)
    store = WindowStore()
    assert audit_window_hashes(rows, store) == []
    train = next(r for r in rows if r.split == "train")
    other = next(r for r in rows if r.split != "train")
    # Point a window of another split at the same samples as a train window.
    other.shard, other.offset = train.shard, train.offset
    leaks = audit_window_hashes(rows, store)
    assert len(leaks) == 1
    assert {wid for wid, _ in leaks[0][1]} == {train.window_id, other.window_id}


def test_labels_and_weights(shards):
    rows = collect_rows(shards)
    labels = label_indices(rows, ("drone_link", "wifi"))
    assert labels.dtype == np.int64 and set(labels.tolist()) == {0, 1}
    weights = row_weights(rows)
    assert weights.dtype == np.float32
    assert set(weights.tolist()) == {1.0, 0.5}
    assert all(w == (0.5 if r.label_strength == "weak" else 1.0) for w, r in zip(weights, rows))
    with pytest.raises(ValueError, match="not one of"):
        label_indices(rows, ("wifi",))


def test_cli_writes_manifest_and_prints_digest(shards, tmp_path, capsys):
    out = tmp_path / "data" / "manifest.jsonl"
    argv = ["--out", str(out), "--seed", "7", "--cross-test", "ds_b", "--cap-per-class", "20", "--classes", "v1"]
    for s in shards:
        argv += ["--shards", str(s)]
    assert build_manifest.main(argv) == 0
    printed = capsys.readouterr().out
    assert f"sha256={manifest.digest(out)}" in printed
    rows = manifest.read(out)
    assert all(not Path(r.shard).is_absolute() for r in rows)
    windows, labels = WindowStore(out.parent).get(rows[:5], ("drone_link", "wifi"))
    assert windows.shape == (5, WINDOW_SAMPLES)
    # Same inputs and seed: byte-identical manifest.
    first = out.read_bytes()
    assert build_manifest.main(argv) == 0
    assert out.read_bytes() == first
    argv[argv.index("7")] = "8"
    assert build_manifest.main(argv) == 0
    assert out.read_bytes() != first


def test_cli_fails_on_identical_windows_across_splits(tmp_path, capsys):
    rows = make_fake_shards(tmp_path / "s", recordings_per_class=8)
    # Rewrite the second recording's rows so it reuses the first recording's shard samples.
    first, second = rows[0], next(r for r in rows if r.recording_id != rows[0].recording_id)
    rows_file = tmp_path / "s" / second.shard.replace(".npy", ".rows.jsonl")
    lines = []
    for line in rows_file.read_text().splitlines():
        d = json.loads(line)
        d["shard"] = first.shard
        lines.append(json.dumps(d))
    rows_file.write_text("\n".join(lines) + "\n")
    # Find a seed that puts the two recordings in different splits.
    seed = next(s for s in range(100) if manifest.split_of(first.recording_id, s) != manifest.split_of(second.recording_id, s))
    code = build_manifest.main(["--shards", str(tmp_path / "s"), "--out", str(tmp_path / "m.jsonl"), "--seed", str(seed)])
    assert code == 1
    assert "identical windows" in capsys.readouterr().err
