from datetime import datetime, timezone

import pytest

from pipeline import judge
from pipeline.schema import Classification, Detection, Method, SignalClass


@pytest.fixture(scope="module")
def profile():
    return judge.load_profile()


def run(profile, label, confidence, freq, bandwidth, pattern="unknown"):
    detection = Detection(detection_id="d", capture_id="c", center_freq_hz=freq,
                          bandwidth_hz=bandwidth, burst_pattern=pattern)
    classification = Classification(detection_id="d", method=Method.ML, label=SignalClass(label),
                                    confidence=confidence)
    return judge.judge(detection, classification, profile)


def test_expected_wifi_is_blue(profile):
    verdict = run(profile, "wifi", 0.97, 2.437e9, 20e6, "continuous")
    assert verdict.disposition == "blue" and verdict.rule_id == "expected-wifi"


def test_low_confidence_is_never_blue(profile):
    assert run(profile, "wifi", 0.6, 2.437e9, 20e6).disposition == "white"


def test_unexpected_drone_is_red(profile):
    verdict = run(profile, "drone", 0.91, 2.4425e9, 8e6, "hopping")
    assert verdict.disposition == "red" and verdict.affiliation == "possible_threat"


def test_unsure_drone_is_white_not_red(profile):
    assert run(profile, "drone", 0.3, 2.4425e9, 8e6).disposition == "white"


def test_known_signal_outside_the_profile_is_white(profile):
    assert run(profile, "wifi", 0.95, 5.9e9, 20e6).rule_id == "not-in-profile"


def test_wrong_pattern_is_not_expected(profile):
    # Bluetooth is expected to hop; a steady narrow carrier is not what the profile lists.
    assert run(profile, "bluetooth", 0.9, 2.44e9, 1e6, "continuous").disposition == "white"


def test_unknown_label_is_white(profile):
    assert run(profile, "unknown", 0.95, 1e9, 1e6).disposition == "white"
