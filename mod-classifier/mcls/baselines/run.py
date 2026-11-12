"""Fit a baseline on a manifest and write its run folder (PROTOCOL run-output contract).

    runs/<name>/
      config.toml               the effective run config
      meta.json                 git_commit, manifest_sha256, seed, classes, model, created
      predictions_<split>.npz   window_id, recording_id, label, logits, snr_db_est (val, test, cross_test)
      model.pkl                 the fitted FeatureClassifier (mcls.baselines.load)

metrics.json is the evaluator's. When Engineer 7's `python -m mcls.train` calls
`train`, it has already written config.toml and meta.json; they are left as is.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np

from mcls import config as config_module
from mcls import manifest as manifest_module
from mcls import taxonomy
from mcls.contracts import WINDOW_SAMPLES, ManifestRow
from mcls.baselines import features
from mcls.baselines.classifier import FeatureClassifier
from mcls.baselines.models import MODELS, build

#: Splits that get a predictions file, when they have rows.
PREDICT_SPLITS = ("val", "test", "cross_test")
WEAK_WEIGHT = 0.5
#: Windows read and featurized at a time (32 MB of samples).
CHUNK = 1024


def train(config: dict, run_dir: Path, manifest: Path | None = None, classes: tuple[str, ...] | None = None) -> None:
    """Fit config["model"]["name"] on the train split, select on val, write run_dir.

    `classes` overrides the taxonomy's class list (tests use it).
    """
    config_module.validate(config)
    name = config["model"]["name"]
    if name not in MODELS:
        raise ValueError(f"model.name {name!r} is not a baseline (choose from {sorted(MODELS)})")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest if manifest is not None else config["data"]["manifest"])
    seed = int(config["run"]["seed"])
    if classes is None:
        classes = taxonomy.load().classes(config["data"]["classes"])
    classes = tuple(classes)

    effective = copy.deepcopy(config)
    effective["data"]["manifest"] = str(manifest_path)
    if not (run_dir / "config.toml").exists():
        (run_dir / "config.toml").write_text(to_toml(effective))
    if not (run_dir / "meta.json").exists():
        write_meta(run_dir, manifest_path, seed, classes, name)

    splits = select_rows(manifest_module.read(manifest_path), classes, config["data"], seed)
    if not splits["train"]:
        raise ValueError(f"{manifest_path}: no train rows with a label in {classes}")
    store = window_store(manifest_path.parent)
    X = {split: featurize(rows, store) for split, rows in splits.items()}
    y = {split: label_indices(rows, classes) for split, rows in splits.items()}

    mean = X["train"].astype(np.float64).mean(axis=0)
    std = X["train"].astype(np.float64).std(axis=0)
    std[std < 1e-9] = 1.0
    classifier = FeatureClassifier(None, classes, mean, std)
    model = build(name, len(classes), seed=seed, params=config.get("optim", {}))
    weights = np.array([WEAK_WEIGHT if r.label_strength == "weak" else 1.0 for r in splits["train"]])
    model.fit(
        classifier.standardize(X["train"]),
        y["train"],
        classifier.standardize(X["val"]),
        y["val"],
        sample_weight=weights,
    )
    classifier.model = model
    classifier.save(run_dir)

    for split in PREDICT_SPLITS:
        rows = splits[split]
        if rows:
            write_predictions(run_dir / f"predictions_{split}.npz", rows, y[split], classifier.logits_from_features(X[split]))


# ---------------------------------------------------------------------------
# Rows and windows
# ---------------------------------------------------------------------------


def select_rows(rows: list[ManifestRow], classes: tuple[str, ...], data: dict, seed: int) -> dict[str, list[ManifestRow]]:
    """Rows per split: labels in `classes` only; real rows only outside train unless
    data.use_simulated (and then simulated rows only in train); train capped per class."""
    use_simulated = bool(data.get("use_simulated", False))
    splits: dict[str, list[ManifestRow]] = {"train": [], "val": [], "test": [], "cross_test": []}
    for row in rows:
        if row.label not in classes or row.split not in splits:
            continue
        if not row.is_real and not (use_simulated and row.split == "train"):
            continue
        splits[row.split].append(row)
    cap = data.get("max_windows_per_class")
    if cap:
        splits["train"] = cap_per_class(splits["train"], int(cap), seed)
    return splits


def cap_per_class(rows: list[ManifestRow], cap: int, seed: int) -> list[ManifestRow]:
    """At most `cap` rows per label, chosen by a seeded draw; manifest order kept."""
    rng = np.random.default_rng(seed)
    by_label: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        by_label.setdefault(row.label, []).append(i)
    keep: list[int] = []
    for label in sorted(by_label):
        index = by_label[label]
        keep += index if len(index) <= cap else sorted(rng.choice(index, cap, replace=False).tolist())
    return [rows[i] for i in sorted(keep)]


def label_indices(rows: list[ManifestRow], classes: tuple[str, ...]) -> np.ndarray:
    lookup = {name: i for i, name in enumerate(classes)}
    return np.array([lookup[r.label] for r in rows], dtype=np.int64)


class ShardReader:
    """Reads windows straight from shards (np.load mmap); offset indexes the flattened shard.

    The same behaviour as Engineer 5's mcls.dataset.WindowStore, used until that is merged.
    """

    def __init__(self, root: Path | None = None):
        self.root = None if root is None else Path(root)
        self._open: dict[str, np.ndarray] = {}

    def _shard(self, name: str) -> np.ndarray:
        if name not in self._open:
            path = Path(name)
            if not path.is_absolute() and self.root is not None:
                path = self.root / path
            self._open[name] = np.load(path, mmap_mode="r").reshape(-1)
        return self._open[name]

    def windows(self, rows: list[ManifestRow]) -> np.ndarray:
        out = np.empty((len(rows), WINDOW_SAMPLES), dtype=np.complex64)
        for i, row in enumerate(rows):
            out[i] = self._shard(row.shard)[row.offset : row.offset + row.length]
        return out


def window_store(root: Path):
    """Engineer 5's WindowStore when present, else ShardReader."""
    try:
        from mcls.dataset import WindowStore
    except ImportError:
        return ShardReader(root)
    return WindowStore(root)


def featurize(rows: list[ManifestRow], store) -> np.ndarray:
    blocks = [features.extract(store.windows(rows[i : i + CHUNK])) for i in range(0, len(rows), CHUNK)]
    if not blocks:
        return np.zeros((0, len(features.FEATURE_NAMES)), dtype=np.float32)
    return np.concatenate(blocks)


# ---------------------------------------------------------------------------
# Run-folder files
# ---------------------------------------------------------------------------


def write_predictions(path: Path, rows: list[ManifestRow], labels: np.ndarray, logits: np.ndarray) -> None:
    snr = np.array([np.nan if r.snr_db_est is None else r.snr_db_est for r in rows], dtype=np.float32)
    np.savez(
        path,
        window_id=np.array([r.window_id for r in rows], dtype=str),
        recording_id=np.array([r.recording_id for r in rows], dtype=str),
        label=np.asarray(labels, dtype=np.int64),
        logits=np.asarray(logits, dtype=np.float32),
        snr_db_est=snr,
    )


def write_meta(run_dir: Path, manifest_path: Path, seed: int, classes: tuple[str, ...], model: str) -> None:
    meta = {
        "git_commit": git_commit(),
        "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
        "seed": seed,
        "classes": list(classes),
        "model": model,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    (Path(run_dir) / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def to_toml(config: dict) -> str:
    """A config dict (sections of scalars and lists) as TOML that tomllib reads back unchanged."""
    lines = []
    for section, values in config.items():
        if not isinstance(values, dict):
            raise ValueError(f"top-level key {section!r} must be a section")
        lines.append(f"[{section}]")
        lines += [f"{key} = {_toml_value(value)}" for key, value in values.items()]
        lines.append("")
    return "\n".join(lines)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise ValueError(f"cannot write {type(value).__name__} to TOML")
