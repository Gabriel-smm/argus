"""
    cd judge
    python -m argus_judge signals.jsonl --site configs/site_campus.toml -o report.json

signals.jsonl is the output of `python -m pipeline.ingest ... --classify`. Add --track (a GPX or
CSV GPS log) with --capture-start to put each signal on a map, or --lat and --lon for one fixed spot.
"""

import argparse
import json
import sys
from pathlib import Path

from argus_judge import (LocationError, ProfileError, attach_locations, build_report, load_site,
                         read_track, summary_text, to_dict, to_geojson)
from argus_judge.locate import parse_time


def read_rows(path: Path) -> list[dict]:
    text = path.read_text().strip()
    if not text:
        return []
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("every row must be a JSON object")
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Judge classified signals against a site profile.")
    p.add_argument("signals", type=Path, help="JSONL (or a JSON list) of ingest rows")
    p.add_argument("--site", type=Path, required=True, help="a site profile, such as configs/site_campus.toml")
    p.add_argument("-o", "--output", type=Path, help="write the full report as JSON")
    p.add_argument("--geojson", type=Path, help="write located verdicts as GeoJSON for a map")
    p.add_argument("--text", action="store_true", help="print the plain-text summary the chat model gets")
    p.add_argument("--track", type=Path, help="GPS log of the sensor: .gpx, or .csv with time, lat, lon")
    p.add_argument("--capture-start", help="when the IQ capture began, e.g. 2026-11-13T15:00:00Z")
    p.add_argument("--utc-offset-hours", type=float, default=0.0,
                   help="offset of times that carry no zone (sweep CSVs): -5 for US Eastern standard time")
    p.add_argument("--max-gap-s", type=float, default=30.0, help="longest wait for a GPS fix (default 30)")
    p.add_argument("--lat", type=float, help="fixed sensor latitude when there is no track")
    p.add_argument("--lon", type=float, help="fixed sensor longitude when there is no track")
    p.add_argument("--accuracy-m", type=float, help="how far off the fixed position may be, in metres")
    args = p.parse_args(argv)
    if (args.lat is None) != (args.lon is None):
        p.error("--lat and --lon go together")

    try:
        site = load_site(args.site)
        rows = read_rows(args.signals)
        track = read_track(args.track, args.utc_offset_hours) if args.track else None
        start = parse_time(args.capture_start, args.utc_offset_hours) if args.capture_start else None
    except (ProfileError, LocationError, ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    manual = {"lat": args.lat, "lon": args.lon, "accuracy_m": args.accuracy_m} if args.lat is not None else None
    locations = attach_locations(rows, track, start, manual, args.utc_offset_hours, args.max_gap_s)
    report = build_report(rows, site, locations)

    if args.output:
        args.output.write_text(json.dumps(to_dict(report), indent=2) + "\n")
    if args.geojson:
        args.geojson.write_text(json.dumps(to_geojson(report), indent=2) + "\n")
    print(summary_text(report) if args.text or not (args.output or args.geojson) else
          f"{sum(report.counts.values())} verdicts: {report.counts}; {report.located} located.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
