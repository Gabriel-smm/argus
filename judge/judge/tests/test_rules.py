import json
from pathlib import Path

import pytest

from argus_judge import CLASSES, judge_row, load_site

ROOT = Path(__file__).resolve().parents[1]
campus = load_site(ROOT / "configs" / "site_campus.toml")
plant = load_site(ROOT / "configs" / "site_power_plant.toml")


def row(signal_class, confidence=0.9, freq=2.437e9, bandwidth=20e6, **extra):
    return {"id": 1, "center_frequency_hz": freq, "bandwidth_hz": bandwidth, "modulation": "unknown",
            "signal_class": signal_class, "class_confidence": confidence, **extra}


def test_expected_wifi_is_blue():
    v = judge_row(row("wifi", 0.97), campus)
    assert (v.disposition, v.rule_id) == ("blue", "expected-wifi")


def test_a_drone_link_the_site_does_not_list_is_red():
    v = judge_row(row("drone_link", 0.91, freq=2.4425e9, bandwidth=8e6, hopping=True), campus)
    assert (v.disposition, v.use_case) == ("red", "drone")


def test_a_jammer_class_is_red_for_the_jamming_use_case():
    v = judge_row(row("gnss_jammer", 0.85, freq=1575.42e6), campus)
    assert (v.disposition, v.use_case) == ("red", "jamming")


def test_unknown_is_white_and_never_blue():
    v = judge_row(row("unknown", 0.41), campus)
    assert (v.disposition, v.rule_id) == ("white", "unknown-low-confidence")


def test_background_is_not_a_verdict():
    assert judge_row(row("background"), campus) is None


def test_a_row_with_no_class_is_white_not_guessed():
    v = judge_row({"id": 1, "center_frequency_hz": 915e6, "bandwidth_hz": 1e5}, campus)
    assert (v.disposition, v.rule_id) == ("white", "not-classified")


def test_a_known_signal_outside_the_profile_is_white():
    assert judge_row(row("wifi", 0.95, freq=5.9e9), campus).rule_id == "not-in-profile"


def test_too_wide_for_the_profile_is_not_expected():
    assert judge_row(row("bluetooth", 0.9, freq=2.44e9, bandwidth=20e6), campus).disposition == "white"


def test_wifi_that_hops_is_flagged_not_blue():
    v = judge_row(row("wifi", 0.84, freq=2.46e9, hopping=True), campus)
    assert (v.disposition, v.rule_id, v.use_case) == ("white", "wifi-hopping", "drone")


def test_the_same_signal_is_routine_on_a_campus_and_red_at_a_power_plant():
    wifi = row("wifi", 0.97, freq=2.437e9)
    assert judge_row(wifi, campus).disposition == "blue"
    assert judge_row(wifi, plant).disposition == "red"


def test_the_site_can_raise_the_bar_for_blue():
    site = load_site(ROOT / "configs" / "site_campus.toml")
    strict = type(site)(**{**site.__dict__, "min_confidence_for_blue": 0.95})
    assert judge_row(row("wifi", 0.9), strict).rule_id == "below-site-bar"


@pytest.mark.parametrize("signal_class", [c for c in CLASSES if c != "background"])
def test_unlisted_signals_are_never_blue(signal_class):
    # A frequency no profile lists: it can be red or white, but never blue.
    assert judge_row(row(signal_class, 0.99, freq=100e6, bandwidth=1e3), campus).disposition != "blue"


def test_fixture_rows_get_the_expected_colors():
    rows = [json.loads(line) for line in (ROOT / "fixtures" / "campus_walk.jsonl").read_text().splitlines()]
    colors = {r["id"]: (v.disposition if (v := judge_row(r, campus)) else None) for r in rows}
    assert colors == {0: "blue", 1: "blue", 2: "red", 3: "white", 4: None, 5: "blue", 6: "white"}
