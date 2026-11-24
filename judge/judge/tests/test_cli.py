import json
from pathlib import Path

from argus_judge.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
FIX, SITE = ROOT / "fixtures", ROOT / "configs" / "site_campus.toml"


def run(*args):
    return main([str(a) for a in args])


def test_end_to_end_with_a_gps_track(tmp_path, capsys):
    out, geo = tmp_path / "report.json", tmp_path / "v.geojson"
    code = run(FIX / "campus_walk.jsonl", "--site", SITE, "-o", out, "--geojson", geo,
               "--track", FIX / "walk.gpx", "--capture-start", "2026-11-14T15:00:00Z")
    assert code == 0
    report = json.loads(out.read_text())
    assert report["counts"] == {"blue": 3, "white": 2, "red": 1}
    assert report["background_skipped"] == 1 and report["located"] == 5   # the last wifi row is too far from any fix
    assert len(json.loads(geo.read_text())["features"]) == 5


def test_text_summary_names_every_non_blue_signal(capsys):
    assert run(FIX / "campus_walk.jsonl", "--site", SITE, "--text", "--lat", 41.7, "--lon", -86.2) == 0
    text = capsys.readouterr().out
    assert "RED" in text and "drone control or video link" in text and "41.70000" in text


def test_jamming_is_reported(capsys):
    assert run(FIX / "jamming_sweep.jsonl", "--site", SITE, "--text") == 0
    assert capsys.readouterr().out.count("POSSIBLE JAMMING") == 2


def test_a_bad_profile_exits_with_2(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("[site]\nname = 'x'\n")
    assert run(FIX / "campus_walk.jsonl", "--site", bad) == 2
    assert "missing 'id'" in capsys.readouterr().err


def test_lat_without_lon_is_refused():
    import pytest
    with pytest.raises(SystemExit):
        run(FIX / "campus_walk.jsonl", "--site", SITE, "--lat", 41.7)
