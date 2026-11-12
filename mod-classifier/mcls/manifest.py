"""The manifest: one JSON line per window, plus splits and the leakage check.

JSONL keeps the manifest readable and needs no extra package. If it grows past
a few million rows, the data-pipeline engineer may add a Parquet copy; JSONL
stays the reference.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from mcls.contracts import SPLITS, ManifestRow

#: Default share of recordings per split (by recording, never by window).
SPLIT_SHARES = {"train": 0.70, "val": 0.15, "test": 0.15}


def write(path: Path, rows: Iterable[ManifestRow], classes: tuple[str, ...] | None = None) -> int:
    """Validate and write rows; return how many were written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w") as out:
        for row in rows:
            row.validate(classes)
            out.write(json.dumps(row.to_dict()) + "\n")
            count += 1
    return count


def read(path: Path, classes: tuple[str, ...] | None = None) -> list[ManifestRow]:
    """Read and validate a manifest; errors name the line at fault."""
    rows = []
    with open(path) as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = ManifestRow.from_dict(json.loads(line))
                row.validate(classes)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path.name}, line {number}: {exc}") from exc
            rows.append(row)
    return rows


def digest(path: Path) -> str:
    """Short sha256 of a manifest file, recorded with every training run."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def split_of(recording_id: str, seed: int, shares: dict[str, float] = SPLIT_SHARES) -> str:
    """Deterministic split for a recording: the same id and seed always land in the same split."""
    value = int.from_bytes(hashlib.sha256(f"{seed}:{recording_id}".encode()).digest()[:8], "big") / 2**64
    cumulative = 0.0
    for name, share in shares.items():
        cumulative += share
        if value < cumulative:
            return name
    return list(shares)[-1]


def assign_splits(rows: list[ManifestRow], seed: int, cross_test_datasets: Iterable[str] = ()) -> None:
    """Set `split` on every row, in place, by recording.

    Datasets named in `cross_test_datasets` are held out whole as `cross_test`
    (train on one source of a class, test on another).
    """
    held_out = set(cross_test_datasets)
    for row in rows:
        row.split = "cross_test" if row.dataset in held_out else split_of(row.recording_id, seed)


def check_leakage(rows: Iterable[ManifestRow]) -> None:
    """Raise ValueError if a recording or a window id appears in more than one split."""
    splits_by_recording: dict[tuple[str, str], set[str]] = defaultdict(set)
    seen_windows: dict[str, str] = {}
    for row in rows:
        if row.split not in SPLITS:
            raise ValueError(f"{row.window_id}: unknown split {row.split!r}")
        splits_by_recording[(row.dataset, row.recording_id)].add(row.split)
        previous = seen_windows.setdefault(row.window_id, row.split)
        if previous != row.split:
            raise ValueError(f"window {row.window_id} is in both {previous} and {row.split}")
    leaks = {key: sorted(value) for key, value in splits_by_recording.items() if len(value) > 1}
    if leaks:
        sample = list(leaks.items())[:3]
        raise ValueError(f"{len(leaks)} recordings appear in more than one split, e.g. {sample}")
