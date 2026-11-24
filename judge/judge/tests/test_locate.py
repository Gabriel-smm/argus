from datetime import datetime, timezone
from pathlib import Path

import pytest

from argus_judge import LocationError, attach_locations, build_report, load_site, read_track, to_geojson
from argus_judge.locate import fix_at, parse_time

ROOT = Path(__file__).resolve().parents[1]
GPX = ROOT / "fixtures" / "walk.gpx"
START = datetime(2026, 11, 14, 15, 0, 0, tzinfo=timezone.utc)


def test_a_gpx_track_is_read_in_time_order():
    track = read_track(GPX)
    assert len(track) == 6 and track[0][0] == START


def test_a_csv_track_is_read(tmp_path):
    f = tmp_path / "walk.csv"
    f.write_text("time,lat,lon\n2026-11-14T15:00:00Z,41.7,-86.2\n2026-11-14T15:00:10Z,41.8,-86.3\n")
    assert read_track(f)[1][1:] == (41.8, -86.3)


def test_a_csv_without_the_columns_is_refused(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("when,north,east\n1,2,3\n")
    with pytest.raises(LocationError, match="time, lat and lon"):
        read_track(f)


def test_the_nearest_fix_is_used():
    fix = fix_at(read_track(GPX), parse_time("2026-11-14T15:00:28Z"))
    assert fix["lat"] == 41.7055 and fix["gap_s"] == 2.0


def test_no_fix_when_the_track_is_too_far_away():
    assert fix_at(read_track(GPX), parse_time("2026-11-14T15:10:00Z")) is None


def test_a_time_with_no_zone_uses_the_offset():
    # 10:30 US Eastern standard time (UTC-5) is 15:30 UTC.
    assert parse_time("2026-11-14 10:30:00", -5.0) == datetime(2026, 11, 14, 15, 30, tzinfo=timezone.utc)


def test_a_bad_time_names_the_problem():
    with pytest.raises(LocationError, match="not a time"):
        parse_time("yesterday")


def test_iq_rows_are_placed_by_capture_start_plus_start_s():
    rows = [{"start_s": 5.0}, {"start_s": 130.0}, {"start_s": 900.0}]
    found = attach_locations(rows, read_track(GPX), START)
    assert found[0]["source"] == "gps" and found[1]["gap_s"] == 10.0 and found[2] is None


def test_manual_position_is_the_fallback():
    found = attach_locations([{"start_s": 900.0}], read_track(GPX), START, manual={"lat": 1.0, "lon": 2.0, "accuracy_m": 25})
    assert found[0] == {"lat": 1.0, "lon": 2.0, "source": "manual", "accuracy_m": 25}


def test_rows_with_no_time_and_no_manual_position_get_nothing():
    assert attach_locations([{"center_frequency_hz": 1}], read_track(GPX), None) == [None]


def test_geojson_is_longitude_first_and_skips_unlocated_signals():
    site = load_site(ROOT / "configs" / "site_campus.toml")
    rows = [{"id": 0, "center_frequency_hz": 2.437e9, "bandwidth_hz": 20e6, "signal_class": "wifi", "class_confidence": 0.9},
            {"id": 1, "center_frequency_hz": 2.437e9, "bandwidth_hz": 20e6, "signal_class": "wifi", "class_confidence": 0.9}]
    report = build_report(rows, site, [{"lat": 41.7, "lon": -86.2, "source": "gps"}, None])
    geo = to_geojson(report)
    assert len(geo["features"]) == 1 and geo["features"][0]["geometry"]["coordinates"] == [-86.2, 41.7]
