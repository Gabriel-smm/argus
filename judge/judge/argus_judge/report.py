"""Run every row through the rules and bundle the result for the UI and the chat."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from argus_judge.jamming import Assessment, assess_noise_floor
from argus_judge.profile import Site
from argus_judge.rules import BLUE, RED, WHITE, Verdict, judge_row


@dataclass
class Report:
    site: dict
    generated_at: str
    counts: dict
    verdicts: list[Verdict]
    jamming: list[Assessment]
    background_skipped: int
    located: int
    notes: list[str] = field(default_factory=list)


def build_report(rows: list[dict], site: Site, locations: list | None = None, now: datetime | None = None) -> Report:
    rows = [{**row, "id": row.get("id", index)} for index, row in enumerate(rows)]
    locations = locations or [None] * len(rows)
    verdicts, skipped = [], 0
    for row, location in zip(rows, locations):
        verdict = judge_row(row, site)
        if verdict is None:
            skipped += 1
            continue
        verdict.location = location
        verdicts.append(verdict)
    notes = ["Locations are where the sensor was, not where the signal came from."]
    if site.status.upper().startswith("DRAFT"):
        notes.append(f"The site profile '{site.site_id}' is a draft: {site.status}")
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return Report(
        site={"id": site.site_id, "name": site.name, "type": site.site_type, "status": site.status, "owner": site.owner},
        generated_at=stamp,
        counts={name: sum(v.disposition == name for v in verdicts) for name in (BLUE, WHITE, RED)},
        verdicts=verdicts,
        jamming=assess_noise_floor(rows, site),
        background_skipped=skipped,
        located=sum(v.location is not None for v in verdicts),
        notes=notes,
    )


def to_dict(report: Report) -> dict:
    return asdict(report)


def summary_text(report: Report) -> str:
    """Plain text for the chat model: counts and reasons, never raw rows."""
    c = report.counts
    lines = [
        f"Site: {report.site['name']} ({report.site['status']}).",
        "Verdicts (blue = expected here, white = unknown, red = not expected here):",
        f"- blue: {c[BLUE]}, white: {c[WHITE]}, red: {c[RED]}; {report.background_skipped} background-only rows skipped",
    ]
    for v in report.verdicts:
        if v.disposition == BLUE:
            continue
        where = f", sensor at {v.location['lat']:.5f}, {v.location['lon']:.5f}" if v.location else ""
        lines.append(f"- signal {v.id}: {v.disposition.upper()}, {v.signal_class or 'no class'}, "
                     f"{(v.center_frequency_hz or 0) / 1e6:.4g} MHz{where}. {v.reason} Next step: {v.next_step}")
    for a in report.jamming:
        if a.flagged:
            agree = " The classifier also saw a jammer signature." if a.classifier_agrees else ""
            lines.append(f"- POSSIBLE JAMMING in {a.band}: {a.reason}{agree}")
    return "\n".join(lines)


def to_geojson(report: Report) -> dict:
    """Points for a map. GeoJSON is longitude first."""
    features = [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [v.location["lon"], v.location["lat"]]},
         "properties": {"id": v.id, "disposition": v.disposition, "signal_class": v.signal_class,
                        "reason": v.reason, "next_step": v.next_step,
                        "center_frequency_hz": v.center_frequency_hz, "location_source": v.location["source"]}}
        for v in report.verdicts if v.location
    ]
    return {"type": "FeatureCollection", "features": features,
            "properties": {"note": "Points are where the sensor was, not where the signal came from."}}
