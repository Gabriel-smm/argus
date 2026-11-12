"""Small synthetic shards in the assumed front-end layout, for tests and downstream engineers.

Not real data: random unit-RMS windows, written as one `.npy` per recording
([k, WINDOW_SAMPLES] complex64) plus a `rows.jsonl` next to them with relative
shard paths. Never use these for a reported number.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from mcls.contracts import SAMPLE_DTYPE, WINDOW_SAMPLES, ManifestRow, band_of


def make_fake_shards(
    out_dir: Path,
    seed: int = 0,
    dataset: str = "fake",
    classes: tuple[str, ...] = ("drone_link", "wifi"),
    recordings_per_class: int = 4,
    windows_per_recording: int = 6,
    emitters: tuple[str, ...] = ("model_a", "model_b"),
    weak_every: int = 3,
) -> list[ManifestRow]:
    """Write fake shards and rows.jsonl into out_dir; return the rows (shard paths relative)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    rows: list[ManifestRow] = []
    centre = 2.44e9
    for c, label in enumerate(classes):
        for r in range(recordings_per_class):
            recording = f"{dataset}_{label}_{r}"
            data = rng.standard_normal((windows_per_recording, WINDOW_SAMPLES, 2)).astype(np.float32)
            windows = (data[..., 0] + 1j * data[..., 1]).astype(SAMPLE_DTYPE)
            windows /= np.sqrt(np.mean(np.abs(windows) ** 2, axis=1, keepdims=True))
            shard = f"{recording}.npy"
            np.save(out_dir / shard, windows.astype(SAMPLE_DTYPE))
            emitter = emitters[r % len(emitters)] if label == "drone_link" and emitters else None
            for w in range(windows_per_recording):
                rows.append(ManifestRow(
                    window_id=f"{recording}/{w:04d}", shard=shard, offset=w * WINDOW_SAMPLES,
                    length=WINDOW_SAMPLES, dataset=dataset, recording_id=recording, label=label,
                    label_strength="weak" if weak_every and (r * windows_per_recording + w) % weak_every == 0 else "strong",
                    native_rate_hz=20e6, center_frequency_hz=centre, band=band_of(centre), is_real=True,
                    license="CC BY 4.0", split="train", emitter_id=emitter, snr_db_est=20.0 + c,
                    bandwidth_hz=10e6,
                ))
    with open(out_dir / "rows.jsonl", "w") as out:
        for row in rows:
            out.write(json.dumps(row.to_dict()) + "\n")
    return rows
