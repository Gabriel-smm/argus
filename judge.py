"""Decide blue / white / red for one classified detection, using a site profile.

The rules live here; the POLICY (what is expected, how sure we must be) lives in the
site profile file, so the policy owner can change it without touching Python.
"""

import json
from pathlib import Path

from pipeline.schema import (
    Affiliation,
    BurstPattern,
    Classification,
    Detection,
    Disposition,
    ExpectedSignal,
    SignalClass,
    SiteProfile,
    UseCase,
    Verdict,
)

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / "data" / "contract" / "site_profile_campus.json"
# DECISION (policy owner): how sure we must be before calling something a threat.
RED_MIN_CONFIDENCE = 0.5


def load_profile(path=DEFAULT_PROFILE):
    return SiteProfile.model_validate(json.loads(Path(path).read_text()))


def _matches(entry: ExpectedSignal, detection: Detection, label: SignalClass):
    if entry.label != label or not entry.freq.contains(detection.center_freq_hz):
        return False
    if entry.max_bandwidth_hz and detection.bandwidth_hz > entry.max_bandwidth_hz:
        return False
    known = detection.burst_pattern != BurstPattern.UNKNOWN
    return not (entry.allowed_patterns and known and detection.burst_pattern not in entry.allowed_patterns)


def _verdict(detection, disposition, affiliation, reason, rule, confidence, profile, next_step, use_case):
    return Verdict(
        detection_id=detection.detection_id,
        disposition=disposition,
        affiliation=affiliation,
        reason=reason,
        rule_id=rule,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        confidence=confidence,
        blue_min_confidence=profile.blue_min_confidence,
        next_step=next_step,
        use_case=use_case,
    )


def judge(detection: Detection, classification: Classification, profile: SiteProfile) -> Verdict:
    label, confidence = classification.label, classification.confidence
    expected = next((e for e in profile.expected if _matches(e, detection, label)), None)

    # 1. A threat class this site does not list: red if we are sure enough, else white.
    if label in profile.threat_classes and expected is None:
        if confidence >= RED_MIN_CONFIDENCE:
            return _verdict(
                detection, Disposition.RED, Affiliation.POSSIBLE_THREAT,
                f"Looks like a {label.value} signal, and this site's profile does not expect one.",
                "threat-class-not-expected", confidence, profile,
                "Report to security with the time and location.", UseCase.DRONE,
            )
        return _verdict(
            detection, Disposition.WHITE, Affiliation.UNKNOWN,
            f"Might be a {label.value} signal, but the model is not sure enough to alarm.",
            "threat-low-confidence", confidence, profile,
            "Re-scan closer to the source and review.", UseCase.DRONE,
        )
    # 2. Low confidence is never blue.
    if confidence < profile.blue_min_confidence:
        return _verdict(
            detection, Disposition.WHITE, Affiliation.UNKNOWN,
            f"Confidence {confidence:.2f} is below the {profile.blue_min_confidence:.2f} bar for blue.",
            "low-confidence-white", confidence, profile,
            "Re-scan or note it for review.", UseCase.SITE_BASELINE,
        )
    # 3. Matches something this site expects.
    if expected is not None:
        return _verdict(
            detection, Disposition.BLUE, expected.affiliation,
            expected.note or f"A {label.value} signal this site expects.",
            f"expected-{label.value}", confidence, profile, "No action.", UseCase.SITE_BASELINE,
        )
    # 4. Recognised but not in the profile, or not recognised at all.
    return _verdict(
        detection, Disposition.WHITE, Affiliation.UNKNOWN,
        "Not in this site's profile, so it cannot be called expected."
        if label != SignalClass.UNKNOWN else "Could not be matched to a known signal.",
        "not-in-profile", confidence, profile, "Review and consider adding it to the profile.",
        UseCase.SITE_BASELINE,
    )
