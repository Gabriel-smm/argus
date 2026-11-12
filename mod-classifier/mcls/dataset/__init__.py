"""Data pipeline: manifest building, window access, samplers, augmentation (numpy only).

The torch `Dataset` lives in `mcls.dataset.torch_dataset` and is never imported
from here, so this package works without PyTorch.
"""

from mcls.dataset.augment import Augmenter
from mcls.dataset.rows import (
    DEFAULT_CAP_PER_CLASS,
    WEAK_WEIGHT,
    build,
    cap_per_class,
    check_emitter_holdout,
    collect_rows,
    holdout_emitters,
    label_indices,
    relative_to,
    row_weights,
    split_rows,
)
from mcls.dataset.sampler import BalancedSampler, class_weights
from mcls.dataset.store import WindowStore, audit_window_hashes, window_hash

__all__ = [
    "Augmenter",
    "BalancedSampler",
    "DEFAULT_CAP_PER_CLASS",
    "WEAK_WEIGHT",
    "WindowStore",
    "audit_window_hashes",
    "build",
    "cap_per_class",
    "check_emitter_holdout",
    "class_weights",
    "collect_rows",
    "holdout_emitters",
    "label_indices",
    "relative_to",
    "row_weights",
    "split_rows",
    "window_hash",
]
