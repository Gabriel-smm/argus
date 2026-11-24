"""One rule list, applied in order, that turns a classified signal into blue, white or red."""

from dataclasses import dataclass

from argus_judge.profile import Site

BLUE, WHITE, RED = "blue", "white", "red"

# What each class means in plain words, for the one-line reasons.
PLAIN = {
    "drone_link": "a drone control or video link",
    "wifi": "Wi-Fi",
    "bluetooth": "Bluetooth",
    "gnss_jammer": "interference on a satellite-navigation band (a possible GPS jammer)",
    "lora": "a LoRa sensor link",
    "pulsed_radar": "pulsed radar",
    "other_ism": "another licence-free device (a remote, a weather sensor)",
    "adsb": "aircraft ADS-B",
}
USE_CASE = {"drone_link": "drone", "gnss_jammer": "jamming"}


@dataclass
class Verdict:
    id: object
    disposition: str
    signal_class: str | None
    confidence: float | None
    reason: str
    rule_id: str
    next_step: str
    use_case: str
    center_frequency_hz: float | None
    bandwidth_hz: float | None
    location: dict | None = None


def _verdict(row, disposition, rule_id, reason, next_step, use_case="site_baseline") -> Verdict:
    return Verdict(
        id=row.get("id"), disposition=disposition, signal_class=row.get("signal_class"),
        confidence=row.get("class_confidence"), reason=reason, rule_id=rule_id,
        next_step=next_step, use_case=use_case,
        center_frequency_hz=row.get("center_frequency_hz"), bandwidth_hz=row.get("bandwidth_hz"),
    )


def judge_row(row: dict, site: Site) -> Verdict | None:
    """The verdict for one ingest row, or None when the row is only background."""
    signal_class = row.get("signal_class")
    if signal_class == "background":
        return None
    if signal_class is None:
        return _verdict(row, WHITE, "not-classified", "This signal has no class yet, so it cannot be judged.",
                        "Run the capture through ingest with --classify.")
    if signal_class == "unknown":
        # The classifier already applied its calibrated threshold, so this is its own "not sure".
        return _verdict(row, WHITE, "unknown-low-confidence",
                        "The classifier was not sure enough to name it.", "Re-scan closer or review by hand.")

    freq, bandwidth = row["center_frequency_hz"], row["bandwidth_hz"]
    expected = next((e for e in site.expected if e.matches(signal_class, freq, bandwidth)), None)
    plain = PLAIN.get(signal_class, signal_class)
    use_case = USE_CASE.get(signal_class, "site_baseline")

    if signal_class in site.red_classes and expected is None:
        return _verdict(row, RED, "red-class-not-expected", f"Looks like {plain}, and this site does not list one.",
                        "Report to security with the time and location.", use_case)
    if signal_class == "wifi" and row.get("hopping") is True:
        return _verdict(row, WHITE, "wifi-hopping", "Wi-Fi stays on a fixed channel, but this signal hops. It could be a drone link.",
                        "Check for a drone and watch the 5.8 GHz band.", "drone")
    confidence = row.get("class_confidence")
    if expected is not None and confidence is not None and confidence < site.min_confidence_for_blue:
        return _verdict(row, WHITE, "below-site-bar",
                        f"Confidence {confidence:.2f} is under this site's bar of {site.min_confidence_for_blue:.2f}.",
                        "Re-scan or review by hand.")
    if expected is not None:
        return _verdict(row, BLUE, f"expected-{signal_class}", expected.note or f"{plain.capitalize()} that this site expects.",
                        "No action.")
    return _verdict(row, WHITE, "not-in-profile", f"Looks like {plain}, which is not on this site's list, so it cannot be called expected.",
                    "Review it, and add it to the profile if it belongs.")
