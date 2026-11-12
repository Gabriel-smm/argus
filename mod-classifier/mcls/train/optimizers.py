"""Optimizers and the schedule wrapper (PLAN.md 5.3). Imports torch.

AdamW (lr 1e-3, weight decay 1e-2) or SGD with Nesterov momentum 0.9. Weight
decay applies to convolution and linear weights only, not to biases or
BatchNorm parameters (any parameter with fewer than 2 dimensions), a common
practice so normalisation scales are not pulled to zero.
"""

from __future__ import annotations

import torch
from torch import nn

from mcls.train.schedules import lambda_for

OPTIMIZERS = ("adamw", "sgd")


def param_groups(model: nn.Module, weight_decay: float) -> list[dict]:
    decay, no_decay = [], []
    for param in model.parameters():
        if not param.requires_grad:
            continue
        (decay if param.ndim >= 2 else no_decay).append(param)
    groups = [{"params": decay, "weight_decay": weight_decay}, {"params": no_decay, "weight_decay": 0.0}]
    return [g for g in groups if g["params"]]


def make_optimizer(model: nn.Module, optim: dict) -> torch.optim.Optimizer:
    """Build from the config's [optim] section; defaults follow PLAN.md 5.3."""
    name = optim.get("name", "adamw")
    lr = float(optim.get("lr", 1e-3))
    weight_decay = float(optim.get("weight_decay", 1e-2))
    groups = param_groups(model, weight_decay)
    if name == "adamw":
        return torch.optim.AdamW(groups, lr=lr)
    if name == "sgd":
        return torch.optim.SGD(groups, lr=lr, momentum=float(optim.get("momentum", 0.9)),
                               nesterov=bool(optim.get("nesterov", True)))
    raise ValueError(f"unknown optimizer {name!r}; expected one of {OPTIMIZERS}")


def make_scheduler(optimizer: torch.optim.Optimizer, optim: dict, total_steps: int):
    """LambdaLR stepped once per optimizer step, following mcls.train.schedules.lr_at."""
    peak = float(optim.get("lr", 1e-3))
    kind = optim.get("schedule", "onecycle")
    return torch.optim.lr_scheduler.LambdaLR(optimizer, lambda_for(total_steps, peak, kind))
