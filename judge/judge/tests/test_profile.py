from pathlib import Path

import pytest

from argus_judge import ProfileError, load_site, parse_site

ROOT = Path(__file__).resolve().parents[1]


def test_both_shipped_profiles_load():
    assert load_site(ROOT / "configs" / "site_campus.toml").site_id == "campus-demo"
    assert load_site(ROOT / "configs" / "site_power_plant.toml").site_type == "power_plant"


def test_an_unknown_class_names_the_problem():
    with pytest.raises(ProfileError, match="'laser' is not a signal class"):
        parse_site({"site": {"id": "x", "name": "x"}, "expected": [{"signal_class": "laser", "min_hz": 1, "max_hz": 2}]})


def test_a_missing_field_names_the_problem():
    with pytest.raises(ProfileError, match="missing 'id'"):
        parse_site({"site": {"name": "x"}})


def test_a_backwards_range_is_refused():
    with pytest.raises(ProfileError, match="min_hz"):
        parse_site({"site": {"id": "x", "name": "x"}, "expected": [{"signal_class": "wifi", "min_hz": 5, "max_hz": 2}]})


def test_the_bar_must_be_a_probability():
    with pytest.raises(ProfileError, match="between 0 and 1"):
        parse_site({"site": {"id": "x", "name": "x"}, "policy": {"min_confidence_for_blue": 1.5}})
