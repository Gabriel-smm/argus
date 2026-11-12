"""The training loop for the neural models (PLAN.md 5.3). Imports torch.

    fit(config, run_dir, resume=False, data=None) -> dict

One epoch: balanced (or seeded shuffled) batches of `batch_size`, loss with
label smoothing and per-row weights (plus the masked family loss when the
auxiliary head is on), backward under mixed precision on cuda, gradient clip,
optimizer step, schedule step, EMA update. After each epoch the EMA weights
are scored on validation; the best macro-F1 is saved to checkpoint.pt and
training stops after `early_stop_patience` epochs without improvement.
last.pt is written every epoch so --resume continues where a job stopped.
At the end, predictions_<split>.npz is written from checkpoint.pt for every
split that has rows among val, test and cross_test.

Config keys read with defaults (PLAN.md 5.3): optim.name adamw, lr 1e-3,
weight_decay 1e-2, momentum 0.9, schedule onecycle, epochs 40, batch_size 256,
label_smoothing 0.1, grad_clip 1.0, ema_decay 0.999, early_stop_patience 8.
Proposed keys not yet in mcls/config.py (read with .get, defaults in
brackets): optim.loss [ce], optim.focal_gamma [2.0], optim.nesterov [true],
optim.balanced_sampler [true], optim.aux_weight [0.5], model.aux_head [false].
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, Sampler

from mcls.models import FAMILIES, build
from mcls.models.heads import main_logits
from mcls.train import checkpoint as ckpt
from mcls.train import runs
from mcls.train.device import resolve_device
from mcls.train.ema import EMA
from mcls.train.losses import classification_loss, family_loss
from mcls.train.optimizers import make_optimizer, make_scheduler
from mcls.train.stopping import EarlyStopper, macro_f1

PREDICTION_SPLITS = ("val", "test", "cross_test")


@dataclass
class RunData:
    """What the loop trains on. `rows[split][i]` describes item i of `datasets[split]`
    (needs window_id, recording_id, snr_db_est). `train_labels` feeds the balanced sampler."""

    datasets: dict[str, Dataset]
    rows: dict[str, list]
    train_labels: np.ndarray
    sampler_factory: object = None  # callable(train_labels, seed) -> object with .epoch(e) -> indices; None = shuffle
    extra: dict = field(default_factory=dict)


class EpochSampler(Sampler):
    """Yields `order(epoch)`; the loop sets `epoch` before each pass so the order is seeded per epoch."""

    def __init__(self, order, length: int):
        self.order = order
        self.length = length
        self.epoch = 0

    def __iter__(self):
        return iter(np.asarray(self.order(self.epoch), dtype=np.int64).tolist())

    def __len__(self) -> int:
        return self.length


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)  # also seeds every CUDA device
    torch.backends.cudnn.benchmark = False


def load_data(config: dict, classes: tuple[str, ...]) -> RunData:
    """Build the datasets from the manifest with Engineer 5's mcls.dataset (published interface in e5.md)."""
    from mcls import manifest as manifest_io
    from mcls.dataset import BalancedSampler, WindowStore, cap_per_class, label_indices
    from mcls.dataset.augment import Augmenter
    from mcls.dataset.torch_dataset import WindowDataset

    data = config["data"]
    seed = config["run"]["seed"]
    path = Path(data["manifest"])
    rows = manifest_io.read(path, classes)
    if not data.get("use_simulated", False):
        rows = [r for r in rows if r.is_real]
    by_split = {split: [r for r in rows if r.split == split] for split in ("train",) + PREDICTION_SPLITS}
    if data.get("max_windows_per_class"):
        by_split["train"] = cap_per_class(by_split["train"], data["max_windows_per_class"], seed)
    if not by_split["train"] or not by_split["val"]:
        raise ValueError(f"{path}: train and val splits must both have rows")
    store = WindowStore(root=path.parent)
    augment = config.get("augment", {})
    augmenter = Augmenter.from_config(augment) if augment.get("enabled", False) else None
    datasets = {}
    for split, split_rows in by_split.items():
        if split_rows:
            datasets[split] = WindowDataset(split_rows, store, classes,
                                            augmenter=augmenter if split == "train" else None, seed=seed)
    return RunData(
        datasets=datasets,
        rows={s: r for s, r in by_split.items() if r},
        train_labels=label_indices(by_split["train"], classes),
        sampler_factory=lambda labels, s: BalancedSampler(labels, s),
    )


def fit(config: dict, run_dir: Path, resume: bool = False, data: RunData | None = None) -> dict:
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text())
    classes = tuple(meta["classes"])
    seed = int(config["run"]["seed"])
    optim = config.get("optim", {})
    model_cfg = config["model"]
    seed_everything(seed)
    device = resolve_device(config["run"].get("device", "auto"))
    amp = device.type == "cuda"

    if data is None:
        data = load_data(config, classes)
    model_kwargs = {
        "num_classes": len(classes),
        "width": int(model_cfg.get("width", 32)),
        "dropout": float(model_cfg.get("dropout", 0.2)),
        "num_families": len(FAMILIES) if model_cfg.get("aux_head", False) else 0,
    }
    model = build(model_cfg["name"], **model_kwargs).to(device)
    ema = EMA(model, float(optim.get("ema_decay", 0.999)))

    batch_size = int(optim.get("batch_size", 256))
    train_loader, sampler = _train_loader(data, batch_size, seed, device, optim.get("balanced_sampler", True))
    epochs = int(optim.get("epochs", 40))
    total_steps = max(epochs * len(train_loader), 1)
    optimizer = make_optimizer(model, optim)
    scheduler = make_scheduler(optimizer, optim, total_steps)
    scaler = _grad_scaler(amp)
    stopper = EarlyStopper(int(optim.get("early_stop_patience", 8)))
    start_epoch = 0
    finished = False

    last_path = run_dir / ckpt.LAST
    if resume and last_path.is_file():
        state = ckpt.load_last(last_path, map_location=device)
        model.load_state_dict(state["model"])
        ema.load_state_dict(state["ema"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        scaler.load_state_dict(state["scaler"])
        stopper.load_state_dict(state["stopper"])
        _set_rng_state(state["rng"])
        start_epoch = int(state["epoch"]) + 1
        finished = bool(state.get("finished", False))

    loss_args = {
        "label_smoothing": float(optim.get("label_smoothing", 0.1)),
        "kind": optim.get("loss", "ce"),
        "focal_gamma": float(optim.get("focal_gamma", 2.0)),
    }
    aux_weight = float(optim.get("aux_weight", 0.5))
    grad_clip = float(optim.get("grad_clip", 1.0))

    for epoch in range(start_epoch, epochs):
        if finished:
            break
        started = time.time()
        sampler.epoch = epoch
        train_set = data.datasets["train"]
        if hasattr(train_set, "set_epoch"):
            train_set.set_epoch(epoch)
        model.train()
        total_loss, batches = 0.0, 0
        for batch in train_loader:
            x = batch["iq"].to(device, non_blocking=True).float()
            y = batch["label"].to(device, non_blocking=True).long()
            w = batch["weight"].to(device, non_blocking=True).float()
            with _autocast(amp):
                out = model(x)
                loss = classification_loss(main_logits(out), y, w, **loss_args)
                if isinstance(out, tuple) and "family" in batch:
                    loss = loss + aux_weight * family_loss(out[1], batch["family"].to(device).long())
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            ema.update(model)
            total_loss += float(loss.detach())
            batches += 1

        logits, labels, weights = predict(ema.module, data.datasets["val"], batch_size, device)
        val_f1 = macro_f1(labels, logits.argmax(axis=1), len(classes))
        val_loss = float(classification_loss(torch.from_numpy(logits), torch.from_numpy(labels),
                                             torch.from_numpy(weights), **loss_args))
        improved = stopper.step(val_f1)
        if improved:
            ckpt.save_best(run_dir / ckpt.BEST, model_name=model_cfg["name"], model_kwargs=model_kwargs,
                           state_dict=ema.state_dict(), classes=classes,
                           family_classes=FAMILIES if model_kwargs["num_families"] else (),
                           config=config, epoch=epoch, val_macro_f1=val_f1, meta=meta)
        finished = stopper.should_stop or epoch == epochs - 1
        record = {"epoch": epoch, "lr": optimizer.param_groups[0]["lr"], "train_loss": total_loss / max(batches, 1),
                  "val_loss": val_loss, "val_macro_f1": val_f1, "best": improved, "seconds": time.time() - started}
        with open(run_dir / "history.jsonl", "a") as handle:
            handle.write(json.dumps(record) + "\n")
        ckpt.save_last(last_path, {
            "epoch": epoch, "finished": finished, "model": model.state_dict(), "ema": ema.state_dict(),
            "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
            "scaler": scaler.state_dict(), "stopper": stopper.state_dict(), "rng": _get_rng_state(),
        })
        print(f"epoch {epoch}: train_loss {record['train_loss']:.4f} val_loss {val_loss:.4f} "
              f"val_macro_f1 {val_f1:.4f}{' (best)' if improved else ''}", flush=True)
        if finished:
            break

    write_all_predictions(run_dir, data, classes, batch_size, device)
    return {"best_val_macro_f1": stopper.best, "run_dir": str(run_dir)}


def predict(model, dataset: Dataset, batch_size: int, device) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Logits (float32 N x K), labels (int64) and row weights (float32) in dataset order."""
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=_workers(device),
                        pin_memory=device.type == "cuda")
    model.eval()
    logits, labels, weights = [], [], []
    with torch.inference_mode():
        for batch in loader:
            x = batch["iq"].to(device, non_blocking=True).float()
            with _autocast(device.type == "cuda"):
                out = main_logits(model(x))
            logits.append(out.float().cpu().numpy())
            labels.append(batch["label"].numpy().astype(np.int64))
            weights.append(batch["weight"].numpy().astype(np.float32))
    return np.concatenate(logits), np.concatenate(labels), np.concatenate(weights)


def write_all_predictions(run_dir: Path, data: RunData, classes, batch_size: int, device) -> list[str]:
    """predictions_<split>.npz from checkpoint.pt (best EMA weights), logits before temperature."""
    payload = ckpt.load_best(run_dir / ckpt.BEST)
    model = ckpt.build_from(payload).to(device)
    written = []
    for split in PREDICTION_SPLITS:
        if split not in data.datasets:
            continue
        logits, labels, _ = predict(model, data.datasets[split], batch_size, device)
        rows = data.rows[split]
        runs.write_predictions(
            run_dir / f"predictions_{split}.npz",
            window_id=[r.window_id for r in rows],
            recording_id=[r.recording_id for r in rows],
            label=labels,
            logits=logits,
            snr_db_est=[r.snr_db_est for r in rows],
            num_classes=len(classes),
        )
        written.append(split)
    return written


def _train_loader(data: RunData, batch_size: int, seed: int, device, balanced: bool):
    n = len(data.datasets["train"])
    if balanced and data.sampler_factory is not None:
        balanced_sampler = data.sampler_factory(data.train_labels, seed)
        order = balanced_sampler.epoch
    else:
        def order(epoch: int) -> np.ndarray:
            return np.random.default_rng([seed, epoch]).permutation(n)
    length = len(order(0))
    sampler = EpochSampler(order, length)
    loader = DataLoader(
        data.datasets["train"], batch_size=batch_size, sampler=sampler, num_workers=_workers(device),
        pin_memory=device.type == "cuda", drop_last=length > batch_size,
        generator=torch.Generator().manual_seed(seed),
    )
    return loader, sampler


def _workers(device) -> int:
    if device.type != "cuda":
        return 0
    return int(os.environ.get("MCLS_WORKERS", min(8, os.cpu_count() or 1)))


def _autocast(enabled: bool):
    if not enabled:
        return contextlib.nullcontext()
    return torch.autocast(device_type="cuda", dtype=torch.float16)


def _grad_scaler(enabled: bool):
    if hasattr(torch, "amp") and hasattr(torch.amp, "GradScaler"):
        return torch.amp.GradScaler("cuda", enabled=enabled)
    return torch.cuda.amp.GradScaler(enabled=enabled)


def _get_rng_state() -> dict:
    state = {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state()}
    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()
    return state


def _set_rng_state(state: dict) -> None:
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"].cpu())
    if "cuda" in state and torch.cuda.is_available():
        torch.cuda.set_rng_state_all([s.cpu() for s in state["cuda"]])
