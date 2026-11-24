"""Use case 2: is the background noise in a band higher than it is at this site normally?"""

from dataclasses import dataclass
from statistics import median

from argus_judge.profile import Site


@dataclass
class Assessment:
    band: str
    baseline_noise_floor_db: float
    observed_noise_floor_db: float
    rise_db: float
    flagged: bool
    signals_used: int
    classifier_agrees: bool   # a row in this band was also classified as gnss_jammer
    reason: str


def assess_noise_floor(rows: list[dict], site: Site) -> list[Assessment]:
    """One assessment per baseline band that has at least one measured signal in it."""
    results = []
    for band in site.baselines:
        in_band = [r for r in rows if band.min_hz <= r.get("center_frequency_hz", 0) <= band.max_hz]
        floors = [r["noise_floor_db"] for r in in_band if r.get("noise_floor_db") is not None]
        if not floors:
            continue
        observed = median(floors)
        rise = round(observed - band.noise_floor_db, 2)
        flagged = rise >= site.noise_rise_db
        agrees = any(r.get("signal_class") == "gnss_jammer" for r in in_band)
        reason = (f"The noise floor is {rise:.1f} dB above this site's normal for {band.name}."
                  if flagged else f"The noise floor in {band.name} is within {site.noise_rise_db:g} dB of normal.")
        results.append(Assessment(band.name, band.noise_floor_db, round(observed, 2), rise, flagged,
                                  len(floors), agrees, reason))
    return results
