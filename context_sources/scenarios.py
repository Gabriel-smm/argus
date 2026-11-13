"""Turn Andrew's demo scenarios into scenes for the Scan button.

Andrew's files (data/contract/scenario_*.json, from his argus-pipeline.patch on the
new-files-for-argus branch) describe illustrative captures: detections with frequency,
width, duty cycle and burst pattern, plus a jamming assessment. They are not real
recordings. This keeps only what our rows use; his own classifications and verdicts
are left out, so Laya and our site check judge the signals themselves.

    python -m context_sources.scenarios

writes data/scenes/<name>.jsonl, and data/scenes/jamming-assessment.json for the
jamming scenario.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "contract"
SCENES = ROOT / "data" / "scenes"
NAMES = ("normal", "drone", "jamming")
JAMMING_FIELDS = ("band", "noise_rise_db", "expected_missing", "flagged", "confidence", "reason")


def detection_row(detection, source_name):
    """One of Andrew's detections as an observation row."""
    row = {
        "id": detection["detection_id"],
        "center_frequency_hz": detection["center_freq_hz"],
        "bandwidth_hz": detection["bandwidth_hz"],
        "modulation": "unknown",
    }
    pattern = detection.get("burst_pattern")
    if pattern == "hopping":
        row["hopping"] = True
    elif pattern == "continuous":
        row["hopping"] = False
    if "duty_cycle" in detection:
        row["duty_cycle"] = detection["duty_cycle"]
    row["note"] = f"From Andrew's {source_name}, detection {detection['detection_id']}; illustrative, not a real capture."
    return row


def convert(scenario, source_name):
    """Rows for every detection, and the jamming assessment if the scenario has one."""
    rows = [detection_row(detection, source_name) for detection in scenario["detections"]]
    jamming = scenario.get("jamming")
    if jamming:
        jamming = {key: jamming[key] for key in JAMMING_FIELDS if key in jamming}
        jamming["source"] = f"Andrew's {source_name}"
    return rows, jamming


def main():
    SCENES.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        source = SOURCE / f"scenario_{name}.json"
        rows, jamming = convert(json.loads(source.read_text(encoding="utf-8")), source.name)
        lines = "".join(json.dumps(row) + "\n" for row in rows)
        (SCENES / f"{name}.jsonl").write_text(lines, encoding="utf-8")
        print(f"{name}: {len(rows)} rows")
        if jamming:
            (SCENES / f"{name}-assessment.json").write_text(json.dumps(jamming, indent=2) + "\n", encoding="utf-8")
            print(f"{name}: jamming assessment, flagged={jamming.get('flagged')}")


if __name__ == "__main__":
    main()
