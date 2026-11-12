"""Checkpoints. Imports torch.

checkpoint.pt (the model to evaluate and deploy) holds only tensors and plain
Python values, so it loads with torch.load(weights_only=True):

    {"format": "mcls-checkpoint-v1", "model": "cnn1d", "model_kwargs": {...},
     "state_dict": EMA weights, "classes": [...], "family_classes": [...],
     "config": {...}, "temperature": 1.0, "epoch": int, "val_macro_f1": float,
     "git_commit": str, "manifest_sha256": str}

`temperature` is a placeholder at 1.0 until the evaluator (Engineer 8) fits it
on validation and calls `set_temperature`.

last.pt is the full training state for --resume (optimizer, scheduler, scaler,
EMA, early stopping, random states); it holds numpy random state, so it loads
with weights_only=False and must only be read from runs this project wrote.
"""

from __future__ import annotations

import math
from pathlib import Path

import torch

FORMAT = "mcls-checkpoint-v1"
BEST = "checkpoint.pt"
LAST = "last.pt"


def save_best(path: Path, *, model_name: str, model_kwargs: dict, state_dict: dict, classes, family_classes,
              config: dict, epoch: int, val_macro_f1: float, meta: dict, temperature: float = 1.0) -> None:
    payload = {
        "format": FORMAT,
        "model": model_name,
        "model_kwargs": dict(model_kwargs),
        "state_dict": {k: v.detach().cpu() for k, v in state_dict.items()},
        "classes": list(classes),
        "family_classes": list(family_classes),
        "config": config,
        "temperature": float(temperature),
        "epoch": int(epoch),
        "val_macro_f1": float(val_macro_f1),
        "git_commit": str(meta.get("git_commit", "unknown")),
        "manifest_sha256": str(meta.get("manifest_sha256", "")),
    }
    _atomic_save(payload, path)


def load_best(path: Path, map_location="cpu") -> dict:
    payload = torch.load(path, map_location=map_location, weights_only=True)
    if payload.get("format") != FORMAT:
        raise ValueError(f"{path}: not an {FORMAT} checkpoint")
    return payload


def build_from(payload: dict):
    """The model a checkpoint describes, with its weights loaded, in eval mode."""
    from mcls.models import build

    model = build(payload["model"], **payload["model_kwargs"])
    model.load_state_dict(payload["state_dict"])
    return model.eval()


def set_temperature(path: Path, temperature: float) -> None:
    """Rewrite only the temperature of checkpoint.pt (Engineer 8, after fitting on validation)."""
    if not (math.isfinite(temperature) and temperature > 0):
        raise ValueError("temperature must be a positive finite number")
    payload = load_best(path)
    payload["temperature"] = float(temperature)
    _atomic_save(payload, path)


def save_last(path: Path, state: dict) -> None:
    _atomic_save(state, path)


def load_last(path: Path, map_location="cpu") -> dict:
    return torch.load(path, map_location=map_location, weights_only=False)


def _atomic_save(obj, path: Path) -> None:
    """Write to a temporary file then rename, so a job killed mid-save leaves the old file intact."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(obj, tmp)
    tmp.replace(path)
