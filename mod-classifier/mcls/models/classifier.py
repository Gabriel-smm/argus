"""A trained checkpoint behind the `mcls.contracts.Classifier` protocol (for Engineer 10).

    clf = load_classifier("runs/cnn1d_v1/checkpoint.pt")
    probs = clf.classify(windows)      # complex64 (n, 4096) -> (n, len(clf.classes)), rows sum to 1

Probabilities are softmax(logits / temperature), with the temperature stored
in the checkpoint (1.0 until the evaluator fits it). Torch is imported when a
classifier is loaded, not when this module is imported.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mcls.contracts import check_windows
from mcls.models import iq_array


class CheckpointClassifier:
    def __init__(self, model, classes, temperature: float = 1.0, device="cpu", batch_size: int = 512):
        self.model = model.to(device).eval()
        self.classes: tuple[str, ...] = tuple(classes)
        self.temperature = float(temperature)
        self.device = device
        self.batch_size = batch_size

    def logits(self, windows: np.ndarray) -> np.ndarray:
        """Float32 (n, K) logits before temperature."""
        import torch

        from mcls.models.heads import main_logits

        check_windows(windows)
        out = np.empty((len(windows), len(self.classes)), dtype=np.float32)
        with torch.inference_mode():
            for start in range(0, len(windows), self.batch_size):
                x = torch.from_numpy(iq_array(windows[start:start + self.batch_size])).to(self.device)
                out[start:start + len(x)] = main_logits(self.model(x)).float().cpu().numpy()
        return out

    def classify(self, windows: np.ndarray) -> np.ndarray:
        return softmax(self.logits(windows) / self.temperature)


def softmax(logits: np.ndarray) -> np.ndarray:
    z = logits.astype(np.float64)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def load_classifier(path, device="cpu", batch_size: int = 512) -> CheckpointClassifier:
    from mcls.train.checkpoint import build_from, load_best

    payload = load_best(Path(path))
    return CheckpointClassifier(build_from(payload), payload["classes"], payload["temperature"], device, batch_size)
