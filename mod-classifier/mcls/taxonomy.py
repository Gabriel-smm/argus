"""Read configs/taxonomy.toml: the class set and the label of every file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from mcls.contracts import LABEL_STRENGTHS

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "configs" / "taxonomy.toml"


@dataclass(frozen=True)
class Label:
    label: str
    strength: str
    note: str | None = None


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    license: str
    is_real: bool
    url: str


class Taxonomy:
    def __init__(self, data: dict):
        classes = data.get("classes", {})
        self.v1: tuple[str, ...] = tuple(classes.get("v1", ()))
        self.v2: tuple[str, ...] = tuple(classes.get("v2", ()))
        if not self.v1:
            raise ValueError("taxonomy: [classes] v1 is empty")
        overlap = set(self.v1) & set(self.v2)
        if overlap:
            raise ValueError(f"taxonomy: classes in both v1 and v2: {sorted(overlap)}")
        self._datasets = data.get("datasets", {})
        for name in self._datasets:
            self._check_dataset(name)

    @property
    def all_classes(self) -> tuple[str, ...]:
        return self.v1 + self.v2

    def classes(self, version: str = "v1") -> tuple[str, ...]:
        """The class list a model trains on: "v1", or "v2" for v1 plus v2."""
        if version == "v1":
            return self.v1
        if version == "v2":
            return self.all_classes
        raise ValueError(f"unknown class version {version!r}")

    def dataset(self, name: str) -> DatasetInfo:
        entry = self._entry(name)
        return DatasetInfo(name, entry["license"], bool(entry["is_real"]), entry.get("url", ""))

    def label_for(self, dataset: str, file_name: str) -> Label:
        """The label of one file: the first override whose `match` is in the name, else the default."""
        entry = self._entry(dataset)
        for override in entry.get("overrides", []):
            if override["match"] in file_name:
                return Label(override["label"], override["strength"], override.get("note"))
        return Label(entry["default_label"], entry["default_strength"])

    def _entry(self, name: str) -> dict:
        if name not in self._datasets:
            raise KeyError(f"taxonomy has no dataset {name!r}")
        return self._datasets[name]

    def _check_dataset(self, name: str) -> None:
        entry = self._datasets[name]
        for key in ("license", "is_real", "default_label", "default_strength"):
            if key not in entry:
                raise ValueError(f"taxonomy: dataset {name!r} is missing {key}")
        pairs = [(entry["default_label"], entry["default_strength"])]
        pairs += [(o["label"], o["strength"]) for o in entry.get("overrides", [])]
        for label, strength in pairs:
            if label not in self.all_classes:
                raise ValueError(f"taxonomy: dataset {name!r} uses unknown class {label!r}")
            if strength not in LABEL_STRENGTHS:
                raise ValueError(f"taxonomy: dataset {name!r} uses unknown strength {strength!r}")


def load(path: Path = DEFAULT_PATH) -> Taxonomy:
    with open(path, "rb") as handle:
        return Taxonomy(tomllib.load(handle))
