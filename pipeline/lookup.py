"""The site check: compare each signal with the band table and the site profile.

Laya names a signal. The site check answers a different question: is this signal
normal here? It sorts every signal into one of three groups, with a reason and
what to check next:

- expected: it fits a band that normally carries this kind of signal, and that
  band is on the site's expected list.
- unknown: no band on the list fits it, or it fits a band that is allowed but
  not normally seen at this site.
- needs_review: it is on a restricted list, it sits where any visible signal is
  suspicious (GPS L1), or it looks like a drone link with no Remote ID heard.

It uses plain rules over small files in data/context/, so a person can read why
each signal landed where it did, and swap the site file without retraining.

Try it without Laya or Ollama:

    python -m pipeline.lookup data/observations-site-demo.jsonl
"""

import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = ROOT / "data" / "context"
BANDS_FILE = CONTEXT / "bands.csv"
ISM_DEVICES_FILE = CONTEXT / "ism_devices.csv"
DEFAULT_SITE = CONTEXT / "site.json"

EXPECTED = "expected"
UNKNOWN = "unknown"
REVIEW = "needs_review"
GROUPS = (REVIEW, UNKNOWN, EXPECTED)

# A measured width may be this many times narrower or wider than the band's
# listed range and still fit. Measured widths are rough, especially at low SNR.
WIDTH_TOLERANCE = 2.0
UNKNOWN_MODULATIONS = {"", "UNKNOWN", "?", "NONE"}
# A signal on less than this share of the time, with a measured pulse interval,
# is read as pulsed when its modulation is unknown. Pulsed radar in the NIST set
# is mostly far below 1%; DroneRF drone bursts are almost all above it.
PULSED_DUTY_CYCLE = 0.01


def _split(text):
    return {part.strip().upper() for part in text.split(";") if part.strip()}


def load_bands(path=BANDS_FILE, ism_devices=ISM_DEVICES_FILE):
    """Read the band table. Frequencies become Hz, widths Hz."""
    path = Path(path)
    count = 0
    if Path(ism_devices).is_file():
        with Path(ism_devices).open(encoding="utf-8") as handle:
            count = sum(1 for _ in csv.DictReader(handle))
    bands = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            bands.append(
                {
                    "id": row["band_id"],
                    "name": row["name"],
                    "low_hz": float(row["low_mhz"]) * 1e6,
                    "high_hz": float(row["high_mhz"]) * 1e6,
                    "use_case": row["use_case"],
                    "width_min_hz": float(row["width_min_khz"]) * 1e3,
                    "width_max_hz": float(row["width_max_khz"]) * 1e3,
                    "modulations": _split(row["modulations"]),
                    "hops": row["hops"],
                    "drone_link": row["drone_link"] == "yes",
                    "flag": row["flag"],
                    "meaning": row["plain_meaning"],
                    "check_next": row["check_next"].replace("{rtl433_count}", str(count)),
                    "source": row["source"],
                }
            )
    if not bands:
        raise ValueError(f"{path} has no bands.")
    return bands


def load_site(path=None):
    """The site profile from ARGUS_SITE, or the demo site."""
    path = Path(path or os.environ.get("ARGUS_SITE") or DEFAULT_SITE)
    if not path.is_absolute() and not path.is_file():
        path = ROOT / path
    if not path.is_file():
        raise FileNotFoundError(
            f"The site profile {path} was not found. Set ARGUS_SITE to a site file "
            f"or leave it unset to use {DEFAULT_SITE.relative_to(ROOT)}."
        )
    site = json.loads(path.read_text(encoding="utf-8"))
    site.setdefault("expected_bands", [])
    site.setdefault("restricted", [])
    site.setdefault("nearby", [])
    return site


def _mhz(hertz):
    for unit, size in (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3)):
        if hertz >= size:
            return f"{hertz / size:.4g} {unit}"
    return f"{hertz:g} Hz"


def _fits_width(band, width):
    if width <= 0:
        return True  # not measured
    return band["width_min_hz"] / WIDTH_TOLERANCE <= width <= band["width_max_hz"] * WIDTH_TOLERANCE


def _fits_modulation(band, modulation):
    modulation = (modulation or "").strip().upper()
    if modulation in UNKNOWN_MODULATIONS or not band["modulations"]:
        return True
    return modulation in band["modulations"]


def _fits_hopping(band, hopping):
    if hopping is None or band["hops"] == "either":
        return True
    return band["hops"] == ("yes" if hopping else "no")


def _lower(name):
    return name[0].lower() + name[1:]


def _names(bands):
    return ", ".join(band["name"] for band in bands)


# Everyday names for what a signal probably is, by the band it matched. Used by the
# dashboard's site report so a non-expert sees "Drones" rather than band names.
MYSTERY = "Mystery signals"
KIND_BY_BAND = {
    "wifi_24": "Wi-Fi & Bluetooth",
    "wifi_5": "Wi-Fi & Bluetooth",
    "bluetooth": "Wi-Fi & Bluetooth",
    "drone_ctrl_900": "Drones",
    "drone_ctrl_24": "Drones",
    "drone_video_24": "Drones",
    "drone_video_58": "Drones",
    "drone_ctrl_58": "Drones",
    "gnss_l1": "GPS",
    "aviation_voice": "Aircraft",
    "dme": "Aircraft",
    "ssr_1030": "Aircraft",
    "adsb_1090": "Aircraft",
    "radar_altimeter": "Aircraft",
    "lband_radar": "Radar",
    "radar_s": "Radar",
    "radar_s3": "Radar",
    "navy_radar_35": "Radar",
    "weather_radar_c": "Radar",
    "cell_low": "Phone networks",
    "cell_mid": "Phone networks",
    "cell_25": "Phone networks",
    "cell_345": "Phone networks",
    "cbrs": "Phone networks",
    "cband_5g": "Phone networks",
    "ism_315": "Sensors & gadgets",
    "ism_433": "Sensors & gadgets",
    "srd_868": "Sensors & gadgets",
    "ism_915": "Sensors & gadgets",
    "fm_broadcast": "Radio stations",
    "noaa_weather": "Radio stations",
    "amateur_2m": "Ham radio",
}


def _result(site, group, matches, reason, check_next, protected=False, title="", kind=None):
    if kind is None:
        kind = KIND_BY_BAND.get(matches[0]["id"], MYSTERY) if matches else MYSTERY
    return {
        "triage": group,
        "title": title,
        "kind": kind,
        "matches": [band["id"] for band in matches],
        "reason": reason,
        "check_next": check_next,
        "protected": protected,
        "site": site.get("name", "this site"),
    }


def _nearby_reason(site, bands):
    """Name a nearby feature that explains why one of these bands is expected."""
    ids = {band["id"] for band in bands}
    for feature in site["nearby"]:
        if ids & set(feature.get("implies", [])):
            distance = feature.get("distance_km")
            where = f" {distance:g} km away" if isinstance(distance, (int, float)) else " nearby"
            return f" {feature['name']} is{where}."
    return ""


def check(observation, bands, site):
    """Sort one signal into expected, unknown or needs_review, and say why."""
    hertz = observation["center_frequency_hz"]
    width = observation.get("bandwidth_hz", 0) or 0
    modulation = observation.get("modulation", "unknown")
    duty = observation.get("duty_cycle")
    if (
        (modulation or "").strip().upper() in UNKNOWN_MODULATIONS
        and isinstance(duty, (int, float))
        and duty < PULSED_DUTY_CYCLE
        and observation.get("pulse_interval_s")
    ):
        modulation = "PULSED"  # from the burst features: short pulses at a steady interval
    hopping = observation.get("hopping")
    remote_id = observation.get("remote_id")
    where = _mhz(hertz)
    shape = f"{_mhz(width)} wide" if width else "width not measured"
    if modulation and modulation.strip().upper() not in UNKNOWN_MODULATIONS:
        shape += f", {modulation}"

    # Narrowest band first, so 1090 MHz reads as ADS-B rather than the wide DME band around it.
    in_range = sorted(
        (band for band in bands if band["low_hz"] <= hertz <= band["high_hz"]),
        key=lambda band: band["high_hz"] - band["low_hz"],
    )

    for entry in site["restricted"]:
        if entry["low_mhz"] * 1e6 <= hertz <= entry["high_mhz"] * 1e6:
            return _result(
                site,
                REVIEW,
                in_range,
                f"{where} is on this site's restricted list ({entry['name']}): {entry['why']}",
                "Report it to whoever owns the site's frequency list.",
                title="On the restricted list",
            )

    if not in_range:
        return _result(
            site,
            UNKNOWN,
            [],
            f"No band on our list covers {where}.",
            "Look it up by frequency and width in Artemis-DB (sigidwiki).",
            title="Not on our map",
        )

    alert = [band for band in in_range if band["flag"] == "alert_any_signal"]
    if alert:
        band = alert[0]
        return _result(site, REVIEW, alert, f"{where} is in {band['name']}. {band['meaning']}", band["check_next"], True,
                       title="Something on GPS")

    fits = [
        band
        for band in in_range
        if _fits_width(band, width) and _fits_modulation(band, modulation) and _fits_hopping(band, hopping)
    ]
    if not fits:
        return _result(
            site,
            UNKNOWN,
            in_range,
            f"{where} is in {_names(in_range)}, but a signal {shape} does not match what normally uses it.",
            "Look it up by frequency and width in Artemis-DB (sigidwiki); it may be a device we have not listed.",
            any(band["flag"] == "protected" for band in in_range),
            title="Doesn't fit its band",
            kind=MYSTERY,
        )

    drones = [band for band in fits if band["drone_link"]]
    others = [band for band in fits if not band["drone_link"]]
    protected = any(band["flag"] == "protected" for band in fits)
    if drones:
        if remote_id is True:
            return _result(
                site,
                UNKNOWN,
                drones,
                f"Fits a {_lower(drones[0]['name'])} and the drone is broadcasting Remote ID, so it can be identified.",
                "Read its Remote ID: serial number, position and operator location.",
                title="Drone that identified itself",
            )
        if remote_id is False or not others:
            heard = "no Remote ID was heard" if remote_id is False else "Remote ID was not checked"
            return _result(
                site,
                REVIEW,
                drones,
                f"{where}, {shape} fits a {_lower(drones[0]['name'])}, and {heard}.",
                drones[0]["check_next"],
                title="Drone with no ID" if remote_id is False else "Possible drone",
            )

    candidates = others or fits
    expected = [band for band in candidates if band["id"] in site["expected_bands"]]
    if not expected:
        return _result(
            site,
            UNKNOWN,
            candidates,
            f"Fits {_names(candidates)}, which is allowed but not normally seen at {site.get('name', 'this site')}.",
            candidates[0]["check_next"],
            protected,
            title="Not usual for this place",
        )

    band = expected[0]
    reason = f"Fits {band['name']}: {band['meaning']}{_nearby_reason(site, expected)}"
    if len(expected) > 1:
        reason += f" It could also be {_names(expected[1:])}."
    if drones:
        reason += f" It could also be a {_lower(drones[0]['name'])}; Remote ID was not checked."
    return _result(site, EXPECTED, expected + drones, reason, band["check_next"], protected, title="Normal here")


def check_all(observations, bands=None, site=None):
    bands = bands if bands is not None else load_bands()
    site = site if site is not None else load_site()
    return [check(observation, bands, site) for observation in observations]


def main():
    """Print the site check for a data file, and agreement with expected_triage if present."""
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "observations-site-demo.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    site = load_site()
    results = check_all(rows, site=site)
    print(f"Site: {site['name']} ({site.get('frequency_list', 'no list named')})\n")
    scored = correct = 0
    for row, result in zip(rows, results):
        mark = ""
        if "expected_triage" in row:
            scored += 1
            correct += row["expected_triage"] == result["triage"]
            mark = "  ok" if row["expected_triage"] == result["triage"] else f"  MISS (wanted {row['expected_triage']})"
        print(f"[{row.get('id', '?')}] {result['triage']}{mark}\n    {result['reason']}\n    next: {result['check_next']}")
    counts = {group: sum(result["triage"] == group for result in results) for group in GROUPS}
    print(f"\n{counts}")
    if scored:
        print(f"Agreement with expected_triage: {correct}/{scored} ({correct / scored:.0%})")


if __name__ == "__main__":
    main()
