"""Collect per-shard rows, cap classes, hold out emitters, and build a split manifest.

Builds on `mcls.manifest` (orchestrator-owned): splits come from
`assign_splits`, leakage from `check_leakage`. Everything here is a pure
function of its inputs and a seed, so the same shards and seed always give the
same manifest file and sha256.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from mcls import manifest
from mcls.contracts import LABEL_STRENGTHS, SPLITS, ManifestRow

#: PLAN 3.6: cap each class at about 30 thousand windows per dataset.
DEFAULT_CAP_PER_CLASS = 30_000
#: PLAN 5.3: weak-label windows get weight 0.5.
WEAK_WEIGHT = 0.5


def seeded_rng(seed: int, *keys: str) -> np.random.Generator:
    """A generator that depends only on `seed` and the string `keys` (never on Python's hash())."""
    material = hashlib.sha256(json.dumps([seed, *keys]).encode()).digest()
    return np.random.default_rng(int.from_bytes(material[:16], "big"))


def collect_rows(shard_dirs: Iterable[Path]) -> list[ManifestRow]:
    """Read every `*.jsonl` under each directory (recursively), one ManifestRow dict per line.

    A relative `shard` path is resolved against the directory of the .jsonl file
    that names it; returned rows carry absolute shard paths. Rows are returned
    sorted by window_id. A window_id seen twice is an error.
    """
    rows: list[ManifestRow] = []
    seen: dict[str, Path] = {}
    for directory in shard_dirs:
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"shard directory not found: {directory}")
        for path in sorted(directory.rglob("*.jsonl")):
            with open(path) as source:
                for number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    try:
                        row = ManifestRow.from_dict(json.loads(line))
                    except (ValueError, TypeError) as exc:
                        raise ValueError(f"{path}, line {number}: {exc}") from exc
                    shard = Path(row.shard)
                    if not shard.is_absolute():
                        row.shard = str((path.parent / shard).resolve())
                    if row.window_id in seen:
                        raise ValueError(f"window_id {row.window_id!r} appears in {seen[row.window_id]} and {path}")
                    seen[row.window_id] = path
                    rows.append(row)
    rows.sort(key=lambda r: r.window_id)
    return rows


def cap_per_class(rows: Sequence[ManifestRow], cap: int, seed: int) -> list[ManifestRow]:
    """Keep at most `cap` windows per (dataset, label); a seeded random choice. cap <= 0 keeps all.

    The choice depends only on the window ids in each group and the seed, not on
    input order. Output is sorted by window_id.
    """
    if cap <= 0:
        return sorted(rows, key=lambda r: r.window_id)
    groups: dict[tuple[str, str], list[ManifestRow]] = defaultdict(list)
    for row in rows:
        groups[(row.dataset, row.label)].append(row)
    kept: list[ManifestRow] = []
    for (dataset, label), group in sorted(groups.items()):
        group.sort(key=lambda r: r.window_id)
        if len(group) <= cap:
            kept.extend(group)
            continue
        choice = seeded_rng(seed, "cap", dataset, label).permutation(len(group))[:cap]
        kept.extend(group[i] for i in choice)
    kept.sort(key=lambda r: r.window_id)
    return kept


def holdout_emitters(
    rows: Iterable[ManifestRow],
    emitter_ids: Iterable[str],
    split: str = "test",
    match: str = "emitter",
) -> int:
    """Move every row of the named emitters (drone models) to `split`, in place (PLAN 3.5).

    `match="emitter"` compares `emitter_id` exactly; `match="recording"` takes
    any row whose recording_id contains one of the names (for rows that carry
    the model only in their recording id). Returns how many rows moved.

    Every recording of a held-out emitter goes to `split` whole, so after this
    the emitter appears in `split` and nowhere else.
    """
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    if match not in ("emitter", "recording"):
        raise ValueError("match must be 'emitter' or 'recording'")
    names = set(emitter_ids)
    moved = 0
    for row in rows:
        if match == "emitter":
            hit = row.emitter_id is not None and row.emitter_id in names
        else:
            hit = any(name in row.recording_id for name in names)
        if hit:
            row.split = split
            moved += 1
    return moved


def check_emitter_holdout(rows: Iterable[ManifestRow], emitter_ids: Iterable[str], split: str = "test") -> None:
    """Raise ValueError if a held-out emitter appears outside `split`."""
    names = set(emitter_ids)
    for row in rows:
        if row.emitter_id in names and row.split != split:
            raise ValueError(f"held-out emitter {row.emitter_id!r} in {row.split}: {row.window_id}")


def build(
    shard_dirs: Iterable[Path],
    seed: int,
    cross_test: Iterable[str] = (),
    cap: int = DEFAULT_CAP_PER_CLASS,
    holdout: Iterable[str] = (),
    holdout_split: str = "test",
    holdout_match: str = "emitter",
) -> list[ManifestRow]:
    """Collect, cap, split by recording, hold out emitters, and check leakage."""
    rows = cap_per_class(collect_rows(shard_dirs), cap, seed)
    manifest.assign_splits(rows, seed, cross_test)
    holdout = tuple(holdout)
    if holdout:
        if holdout_emitters(rows, holdout, holdout_split, holdout_match) == 0:
            raise ValueError(f"no rows match held-out emitters {list(holdout)}")
    manifest.check_leakage(rows)
    if holdout and holdout_match == "emitter":
        check_emitter_holdout(rows, holdout, holdout_split)
    return rows


def relative_to(rows: Iterable[ManifestRow], base: Path) -> list[ManifestRow]:
    """Copies of rows whose shard paths are relative to `base` (the manifest's directory)."""
    base = Path(base).resolve()
    out = []
    for row in rows:
        data = row.to_dict()
        data["shard"] = Path(os.path.relpath(Path(row.shard).resolve(), base)).as_posix()
        out.append(ManifestRow.from_dict(data))
    return out


def label_indices(rows: Sequence[ManifestRow], classes: Sequence[str]) -> np.ndarray:
    """int64 index of each row's label in `classes`; raises on a label outside them."""
    index = {name: i for i, name in enumerate(classes)}
    try:
        return np.array([index[row.label] for row in rows], dtype=np.int64)
    except KeyError as exc:
        raise ValueError(f"label {exc.args[0]!r} is not one of {tuple(classes)}") from None


def row_weights(rows: Sequence[ManifestRow], weak_weight: float = WEAK_WEIGHT) -> np.ndarray:
    """float32 loss weight per row: 1.0 for strong labels, `weak_weight` for weak (PLAN 5.3)."""
    weights = {"strong": 1.0, "weak": weak_weight}
    assert set(weights) == set(LABEL_STRENGTHS)
    return np.array([weights[row.label_strength] for row in rows], dtype=np.float32)


def split_rows(rows: Iterable[ManifestRow], split: str) -> list[ManifestRow]:
    """The rows of one split, in manifest order."""
    return [row for row in rows if row.split == split]
