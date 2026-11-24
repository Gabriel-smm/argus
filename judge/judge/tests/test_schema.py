"""The shipped JSON Schemas describe what the Judge actually reads and writes."""
import json
from pathlib import Path

import pytest

from argus_judge import build_report, load_site, to_dict

jsonschema = pytest.importorskip("jsonschema")
ROOT = Path(__file__).resolve().parents[1]
SITE = load_site(ROOT / "configs" / "site_campus.toml")


def schema(name):
    return json.loads((ROOT / "schema" / name).read_text())


def rows(name):
    return [json.loads(line) for line in (ROOT / "fixtures" / name).read_text().splitlines()]


@pytest.mark.parametrize("fixture", ["campus_walk.jsonl", "jamming_sweep.jsonl"])
def test_fixture_rows_match_the_input_schema(fixture):
    for row in rows(fixture):
        jsonschema.validate(row, schema("input_row.schema.json"))


@pytest.mark.parametrize("fixture", ["campus_walk.jsonl", "jamming_sweep.jsonl"])
def test_a_report_matches_the_report_schema(fixture):
    located = [{"lat": 41.7, "lon": -86.2, "source": "gps", "gap_s": 2.0}] + [None] * (len(rows(fixture)) - 1)
    report = to_dict(build_report(rows(fixture), SITE, located))
    jsonschema.validate(json.loads(json.dumps(report)), schema("report.schema.json"))


def test_the_schema_rejects_a_bad_colour():
    report = json.loads(json.dumps(to_dict(build_report(rows("campus_walk.jsonl"), SITE))))
    report["verdicts"][0]["disposition"] = "green"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report, schema("report.schema.json"))
