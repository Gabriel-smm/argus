import json
from pathlib import Path

from argus_judge import assess_noise_floor, load_site

ROOT = Path(__file__).resolve().parents[1]
site = load_site(ROOT / "configs" / "site_campus.toml")


def rows(floor):
    return [{"center_frequency_hz": 915e6, "noise_floor_db": floor}, {"center_frequency_hz": 910e6, "noise_floor_db": floor}]


def test_a_big_rise_is_flagged():
    (a,) = assess_noise_floor(rows(-78.0), site)
    assert a.flagged and a.rise_db == 18.0 and a.band == "ism_915"


def test_a_small_rise_is_not():
    (a,) = assess_noise_floor(rows(-92.0), site)
    assert not a.flagged and a.rise_db == 4.0


def test_a_band_with_no_measurements_is_skipped():
    assert assess_noise_floor([{"center_frequency_hz": 2.4e9, "noise_floor_db": -50}], site) == []


def test_the_classifier_agreeing_is_recorded():
    data = [json.loads(line) for line in (ROOT / "fixtures" / "jamming_sweep.jsonl").read_text().splitlines()]
    by_band = {a.band: a for a in assess_noise_floor(data, site)}
    assert by_band["ism_915"].flagged and not by_band["ism_915"].classifier_agrees
    assert by_band["gnss_l1"].flagged and by_band["gnss_l1"].classifier_agrees
