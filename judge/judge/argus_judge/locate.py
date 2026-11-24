"""Where was the SENSOR when it heard a signal?  (Not where the signal came from.)

One sensor cannot find an emitter, so every location here is the sensor's own position:
  * a GPS track (GPX, or a CSV with time, lat, lon) matched to each signal by time, or
  * one manual position for the whole capture.
A signal with no fix close enough in time gets no location, never a guess.
"""

import csv
import xml.etree.ElementTree as ET
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path


class LocationError(ValueError):
    """A time or a track file could not be read."""


def parse_time(text, utc_offset_hours: float = 0.0) -> datetime:
    """A UTC datetime. A time with no zone is taken as local time at utc_offset_hours from UTC.

    rtl_power writes local time and GPX files use UTC, so pass the offset (for example -5
    for US Eastern standard time) when the capture came from a sweep CSV.
    """
    raw = str(text).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        raise LocationError(f"{text!r} is not a time such as 2026-11-13T15:00:00Z.") from None
    if moment.tzinfo is None:
        moment = (moment - timedelta(hours=utc_offset_hours)).replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def read_track(path, utc_offset_hours: float = 0.0) -> list[tuple[datetime, float, float]]:
    """(time, lat, lon) points sorted by time, from a .gpx or .csv file."""
    path = Path(path)
    points = []
    if path.suffix.lower() == ".gpx":
        try:
            root = ET.fromstring(path.read_text())
        except ET.ParseError as exc:
            raise LocationError(f"{path.name}: not a valid GPX file ({exc}).") from None
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] != "trkpt":
                continue
            stamp = next((c.text for c in node if c.tag.rsplit("}", 1)[-1] == "time" and c.text), None)
            if stamp is None:
                continue
            points.append((parse_time(stamp, utc_offset_hours), float(node.attrib["lat"]), float(node.attrib["lon"])))
    else:
        with path.open(newline="") as handle:
            for number, row in enumerate(csv.DictReader(handle), 2):
                low = {k.strip().lower(): v for k, v in row.items() if k}
                pick = lambda names: next((low[n] for n in names if low.get(n)), None)
                stamp, lat, lon = pick(("time", "timestamp", "datetime")), pick(("lat", "latitude")), pick(("lon", "lng", "longitude"))
                if None in (stamp, lat, lon):
                    raise LocationError(f"{path.name} line {number}: needs time, lat and lon columns.")
                points.append((parse_time(stamp, utc_offset_hours), float(lat), float(lon)))
    if not points:
        raise LocationError(f"{path.name} has no GPS points.")
    return sorted(points)


def fix_at(track, when: datetime, max_gap_s: float = 30.0) -> dict | None:
    """The track point nearest in time, or None when it is more than max_gap_s away."""
    times = [point[0] for point in track]
    index = bisect_left(times, when)
    near = [track[i] for i in (index - 1, index) if 0 <= i < len(track)]
    moment, lat, lon = min(near, key=lambda p: abs((p[0] - when).total_seconds()))
    gap = abs((moment - when).total_seconds())
    if gap > max_gap_s:
        return None
    return {"lat": lat, "lon": lon, "source": "gps", "gap_s": round(gap, 1)}


def row_time(row: dict, capture_start: datetime | None, utc_offset_hours: float = 0.0) -> datetime | None:
    """When a signal was heard: its first_seen (sweeps) or capture start plus start_s (IQ)."""
    try:
        if row.get("first_seen"):
            return parse_time(row["first_seen"], utc_offset_hours)
    except LocationError:
        return None
    if capture_start is not None and row.get("start_s") is not None:
        return capture_start + timedelta(seconds=float(row["start_s"]))
    return None


def attach_locations(rows, track=None, capture_start=None, manual=None,
                     utc_offset_hours: float = 0.0, max_gap_s: float = 30.0) -> list[dict | None]:
    """One location (or None) per row, in order. Manual is the fallback for rows without a GPS fix."""
    fallback = None
    if manual is not None:
        fallback = {"lat": manual["lat"], "lon": manual["lon"], "source": "manual"}
        if manual.get("accuracy_m") is not None:
            fallback["accuracy_m"] = manual["accuracy_m"]
    out = []
    for row in rows:
        found = None
        if track:
            when = row_time(row, capture_start, utc_offset_hours)
            found = fix_at(track, when, max_gap_s) if when else None
        out.append(found or fallback)
    return out
