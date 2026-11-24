"""A site profile: what is normal at one site. Policy lives here (TOML), not in code."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

# The class names mod-classifier produces (taxonomy.toml, v2c plus adsb), plus the two
# answers the Judge itself understands: "unknown" (below the calibrated threshold) and
# "background" (no signal).
CLASSES = ("drone_link", "wifi", "bluetooth", "background", "gnss_jammer", "lora",
           "pulsed_radar", "other_ism", "adsb")


class ProfileError(ValueError):
    """The site profile is missing something or says something that makes no sense."""


@dataclass(frozen=True)
class Expected:
    signal_class: str
    min_hz: float
    max_hz: float
    max_bandwidth_hz: float | None
    note: str

    def matches(self, signal_class: str, frequency_hz: float, bandwidth_hz: float) -> bool:
        if signal_class != self.signal_class or not self.min_hz <= frequency_hz <= self.max_hz:
            return False
        return self.max_bandwidth_hz is None or bandwidth_hz <= self.max_bandwidth_hz


@dataclass(frozen=True)
class Baseline:
    """The quiet noise floor of a band at this site, measured with the same radio and gain."""
    name: str
    min_hz: float
    max_hz: float
    noise_floor_db: float


@dataclass(frozen=True)
class Site:
    site_id: str
    name: str
    site_type: str
    owner: str
    status: str                      # e.g. "DRAFT: waiting for review"
    lat: float | None
    lon: float | None
    red_classes: tuple[str, ...]     # red when seen and not listed under expected
    min_confidence_for_blue: float   # extra bar on top of the classifier's own "unknown" threshold
    noise_rise_db: float             # noise-floor rise over baseline that counts as possible jamming
    expected: tuple[Expected, ...]
    baselines: tuple[Baseline, ...]


def _need(table: dict, key: str, where: str):
    if key not in table:
        raise ProfileError(f"{where} is missing '{key}'.")
    return table[key]


def _check_class(name: str, where: str) -> str:
    if name not in CLASSES:
        raise ProfileError(f"{where}: '{name}' is not a signal class. Use one of: {', '.join(CLASSES)}.")
    return name


def _range(table: dict, where: str) -> tuple[float, float]:
    low, high = float(_need(table, "min_hz", where)), float(_need(table, "max_hz", where))
    if not 0 < low <= high:
        raise ProfileError(f"{where}: min_hz must be above 0 and not above max_hz.")
    return low, high


def parse_site(data: dict) -> Site:
    site = _need(data, "site", "The profile")
    policy = data.get("policy", {})
    expected = []
    for number, entry in enumerate(data.get("expected", []), 1):
        where = f"[[expected]] entry {number}"
        low, high = _range(entry, where)
        limit = entry.get("max_bandwidth_hz")
        expected.append(Expected(_check_class(_need(entry, "signal_class", where), where), low, high,
                                 None if limit is None else float(limit), entry.get("note", "")))
    baselines = []
    for number, entry in enumerate(data.get("baseline", []), 1):
        where = f"[[baseline]] entry {number}"
        low, high = _range(entry, where)
        baselines.append(Baseline(_need(entry, "name", where), low, high, float(_need(entry, "noise_floor_db", where))))
    red = tuple(_check_class(c, "policy.red_classes") for c in policy.get("red_classes", ["drone_link", "gnss_jammer"]))
    minimum = float(policy.get("min_confidence_for_blue", 0.0))
    rise = float(policy.get("noise_rise_db", 10.0))
    if not 0 <= minimum <= 1:
        raise ProfileError("policy.min_confidence_for_blue must be between 0 and 1.")
    if rise <= 0:
        raise ProfileError("policy.noise_rise_db must be above 0.")
    return Site(
        site_id=str(_need(site, "id", "[site]")), name=str(_need(site, "name", "[site]")),
        site_type=str(site.get("type", "other")), owner=str(site.get("owner", "")),
        status=str(site.get("status", "DRAFT")),
        lat=site.get("lat"), lon=site.get("lon"),
        red_classes=red, min_confidence_for_blue=minimum, noise_rise_db=rise,
        expected=tuple(expected), baselines=tuple(baselines),
    )


def load_site(path) -> Site:
    try:
        return parse_site(tomllib.loads(Path(path).read_text()))
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path}: not valid TOML ({exc}).") from None
