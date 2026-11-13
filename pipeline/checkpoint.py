"""Which Laya checkpoint the pipeline loads."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# What finetune/train.py writes. The base checkpoint answers the signal type
# question at chance, so it is never used unless asked for by name.
FINE_TUNED = ROOT / "models" / "laya-rf-modes"


def label():
    """The checkpoint's short name, for records. Never fails, unlike resolve()."""
    chosen = os.environ.get("LAYA_CHECKPOINT")
    return Path(chosen).name if chosen else FINE_TUNED.name


def resolve():
    """LAYA_CHECKPOINT when set, otherwise the fine-tuned folder, which must exist."""
    chosen = os.environ.get("LAYA_CHECKPOINT")
    if chosen:
        return chosen
    if not (FINE_TUNED / "model.safetensors").is_file():
        raise FileNotFoundError(
            f"The fine-tuned Laya checkpoint was not found at {FINE_TUNED}. "
            "Copy the laya-rf-modes folder there, or set LAYA_CHECKPOINT to a "
            "checkpoint folder or a Hugging Face id."
        )
    return str(FINE_TUNED)
