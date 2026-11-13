import json
from pathlib import Path

import pytest

from context_sources import osm_site, rtl433
from pipeline import lookup
from pipeline.context import build_context, build_summary

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "observations-site-demo.jsonl"
BANDS = lookup.load_bands()
SITE = lookup.load_site(lookup.DEFAULT_SITE)


def signal(mhz, width_khz, modulation="unknown", **extra):
    return {"center_frequency_hz": mhz * 1e6, "bandwidth_hz": width_khz * 1e3, "modulation": modulation, **extra}


def triage(observation, site=SITE):
    return lookup.check(observation, BANDS, site)


def test_every_demo_signal_lands_in_its_expected_group():
    rows = [json.loads(line) for line in DEMO.read_text().splitlines() if line.strip()]
    misses = [
        (row["id"], row["expected_triage"], result["triage"])
        for row, result in zip(rows, lookup.check_all(rows, BANDS, SITE))
        if row["expected_triage"] != result["triage"]
    ]
    assert misses == []


def test_band_table_is_well_formed():
    ids = [band["id"] for band in BANDS]
    assert len(ids) == len(set(ids))
    for band in BANDS:
        assert band["low_hz"] < band["high_hz"], band["id"]
        assert band["width_min_hz"] <= band["width_max_hz"], band["id"]
        assert band["hops"] in ("yes", "no", "either"), band["id"]
        assert band["flag"] in ("none", "protected", "alert_any_signal"), band["id"]
        assert "{" not in band["check_next"], band["id"]


def test_site_files_only_name_bands_that_exist():
    ids = {band["id"] for band in BANDS}
    for path in (ROOT / "data" / "context").glob("site*.json"):
        site = json.loads(path.read_text())
        assert set(site["expected_bands"]) <= ids, path.name
        for feature in site.get("nearby", []):
            assert set(feature["implies"]) <= ids, path.name


def test_any_signal_on_gps_l1_needs_a_closer_look():
    result = triage(signal(1575.42, 2000))
    assert result["triage"] == lookup.REVIEW
    assert result["protected"]


def test_drone_link_without_remote_id_needs_a_closer_look():
    assert triage(signal(2440, 2000, "FHSS", hopping=True, remote_id=False))["triage"] == lookup.REVIEW


def test_drone_link_with_remote_id_is_identified_not_flagged():
    result = triage(signal(2440, 2000, "FHSS", hopping=True, remote_id=True))
    assert result["triage"] == lookup.UNKNOWN
    assert "Remote ID" in result["check_next"]


def test_frequency_outside_the_table_is_unknown():
    assert triage(signal(3100, 1000))["triage"] == lookup.UNKNOWN


def test_narrowest_band_wins():
    assert triage(signal(1090, 2000, "PPM"))["matches"][0] == "adsb_1090"


def test_swapping_the_site_changes_what_is_expected():
    overseas = lookup.load_site(ROOT / "data" / "context" / "site_example_overseas.json")
    european = signal(868.3, 100, "FSK")
    assert triage(european)["triage"] == lookup.UNKNOWN
    assert triage(european, overseas)["triage"] == lookup.EXPECTED
    assert triage(signal(433.92, 50, "OOK"), overseas)["triage"] == lookup.REVIEW


def test_missing_site_file_names_the_setting(monkeypatch):
    monkeypatch.setenv("ARGUS_SITE", "data/context/nowhere.json")
    with pytest.raises(FileNotFoundError, match="ARGUS_SITE"):
        lookup.load_site()


def test_context_lists_flagged_signals_with_reasons():
    observations = [signal(2437, 20000, "OFDM", id=0), signal(1575.42, 2000, id=1)]
    rows = [
        {"id": index, "state": f"state {index}.", "answers": {"mode": ("other", 0.9)}, "lookup": result}
        for index, result in enumerate(lookup.check_all(observations, BANDS, SITE))
    ]
    questions = {"mode": {"type": "choice", "instructions": "Which?", "criteria": {"other": "x", "psk": "y"}}}
    names = {"knowledge": "k.json", "data": "d.jsonl"}
    context = build_context(names, questions, rows, total=2)
    assert "- needs a closer look (1): 1" in context
    assert "- expected here (1): 0" in context
    assert "Protected safety band" in context
    summary = build_summary(names, questions, rows, total=2, seconds=1.0)
    assert summary["site_check"] == {"needs_review": 1, "unknown": 0, "expected": 1}


def test_context_without_site_check_is_unchanged():
    rows = [{"id": 0, "state": "s.", "answers": {"mode": ("other", 0.9)}}]
    questions = {"mode": {"type": "choice", "instructions": "Which?", "criteria": {"other": "x", "psk": "y"}}}
    context = build_context({"knowledge": "k", "data": "d"}, questions, rows, total=1)
    assert "Site check" not in context


def test_rtl433_list_is_parsed_and_grouped():
    text = "intro\n\t= Supported device protocols =\n    [01]  Acme Weather Station\n    [02]* Nissan TPMS\nAfter\n"
    rows = rtl433.parse(text)
    assert [(row["rtl433_id"], row["category"], row["on_by_default"]) for row in rows] == [
        (1, "weather station", "yes"),
        (2, "tire pressure sensor", "no"),
    ]


def test_osm_reply_becomes_nearby_features():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 41.7087, "lon": -86.3173,
             "tags": {"aeroway": "aerodrome", "name": "South Bend International Airport", "iata": "SBN"}},
            {"type": "way", "id": 2, "center": {"lat": 41.70, "lon": -86.24},
             "tags": {"power": "substation"}},
            {"type": "node", "id": 3, "lat": 41.71, "lon": -86.25, "tags": {"amenity": "cafe"}},
        ]
    }
    nearby = osm_site.features(payload, 41.703, -86.239)
    assert [item["kind"] for item in nearby] == ["power substation", "airport"]
    assert nearby[1]["name"] == "South Bend International Airport (SBN)"
    assert 6 < nearby[1]["distance_km"] < 7
    assert "adsb_1090" in nearby[1]["implies"]


def test_low_duty_cycle_with_a_pulse_interval_reads_as_pulsed_radar():
    radar = signal(3600, 1000, duty_cycle=0.0007, pulse_interval_s=0.001)
    assert triage(radar)["matches"][0] == "navy_radar_35"
    assert triage(radar)["protected"]
    steady = signal(3600, 20000, "OFDM", duty_cycle=0.5)
    assert triage(steady)["matches"][0] == "cbrs"


def _report(observations, site=SITE):
    from pipeline.context import build_site_report

    rows = [
        {"id": index, "state": "s.", "answers": {"mode": ("other", 0.9)}, "lookup": result}
        for index, result in enumerate(lookup.check_all(observations, BANDS, site))
    ]
    return build_site_report(rows)


def test_report_says_normal_when_everything_is_expected():
    report = _report([signal(2437, 20000, "OFDM", hopping=False), signal(98.7, 200, "FM")])
    assert report["verdict"] == "normal"
    assert report["headline"] == "Normal activity"
    assert report["flagged"] == []
    assert {entry["kind"] for entry in report["kinds"]} == {"Wi-Fi & Bluetooth", "Radio stations"}


def test_report_leads_with_what_needs_a_closer_look():
    report = _report([signal(98.7, 200, "FM"), signal(3100, 1000), signal(1575.42, 2000)])
    assert report["verdict"] == "review"
    assert report["headline"] == "1 signal needs a closer look"
    assert [item["title"] for item in report["flagged"]][0] == "Something on GPS"
    assert report["kinds"][0] == {"kind": "GPS", "count": 1, "worst": "needs_review"}
    assert report["questions"][0].startswith("Is the signal on GPS dangerous")


def test_report_without_site_check_is_none():
    from pipeline.context import build_site_report

    assert build_site_report([{"id": 0, "state": "s.", "answers": {}}]) is None


def test_report_carries_every_signal_worst_first_for_the_category_buttons():
    report = _report([signal(98.7, 200, "FM"), signal(1575.42, 2000), signal(3100, 1000)])
    assert [item["group"] for item in report["signals"]] == ["needs_review", "unknown", "expected"]
    assert {item["kind"] for item in report["signals"]} == {entry["kind"] for entry in report["kinds"]}


def test_provenance_names_the_site_and_changes_when_a_file_is_edited(tmp_path):
    site_file = tmp_path / "site.json"
    site_file.write_text(json.dumps({"name": "Test field", "latitude": 1.5, "longitude": -2.5}), encoding="utf-8")
    first = lookup.provenance(site_file)
    assert first["site"] == {"name": "Test field", "latitude": 1.5, "longitude": -2.5}
    assert first["versions"]["site_profile"].startswith("site.json sha256:")
    assert first["versions"]["band_table"] == lookup.provenance()["versions"]["band_table"]

    site_file.write_text(json.dumps({"name": "Test field", "latitude": 1.6, "longitude": -2.5}), encoding="utf-8")
    assert lookup.provenance(site_file)["versions"]["site_profile"] != first["versions"]["site_profile"]


def test_andrews_detections_become_rows_crediting_him():
    from context_sources import scenarios

    detection = {"detection_id": "d3", "center_freq_hz": 2.4425e9, "bandwidth_hz": 8e6, "duty_cycle": 0.12}
    hopping = scenarios.detection_row({**detection, "burst_pattern": "hopping"}, "scenario_drone.json")
    assert hopping == {
        "id": "d3",
        "center_frequency_hz": 2.4425e9,
        "bandwidth_hz": 8e6,
        "modulation": "unknown",
        "hopping": True,
        "duty_cycle": 0.12,
        "note": "From Andrew's scenario_drone.json, detection d3; illustrative, not a real capture.",
    }
    assert scenarios.detection_row({**detection, "burst_pattern": "continuous"}, "x")["hopping"] is False
    assert "hopping" not in scenarios.detection_row({**detection, "burst_pattern": "bursty"}, "x")


def test_converted_scenes_match_andrews_files():
    # data/scenes/ must be what the converter makes from data/contract/; rerun it after editing his files.
    from context_sources import scenarios

    for name in scenarios.NAMES:
        source = json.loads((scenarios.SOURCE / f"scenario_{name}.json").read_text(encoding="utf-8"))
        rows, jamming = scenarios.convert(source, f"scenario_{name}.json")
        saved = (scenarios.SCENES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in saved] == rows
        assessment = scenarios.SCENES / f"{name}-assessment.json"
        assert (json.loads(assessment.read_text(encoding="utf-8")) if assessment.exists() else None) == jamming
