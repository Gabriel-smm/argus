"""Turn Laya's rows into the Argus data contract (pipeline/schema.py)."""

from datetime import datetime, timezone

from pipeline import judge
from pipeline.schema import (
    BurstPattern,
    Candidate,
    Capture,
    Classification,
    Detection,
    Method,
    PipelineResult,
    SignalClass,
    SourceType,
)

# Which Laya question names the signal type.
QUESTION = "mode"
# Laya answer -> contract label. Update this when the model's classes change
# (for example when the 6-class model replaces the shortwave one).
LABEL_MAP = {
    **{c.value: c for c in SignalClass},
    **dict.fromkeys(
        ("morse", "psk", "rtty", "olivia", "dominoex", "mt63", "navtex", "weather_fax"),
        SignalClass.OTHER,
    ),
}


def _label(answer):
    return LABEL_MAP.get(answer, SignalClass.UNKNOWN)


def _detection(observation, capture_id):
    optional = {
        key: observation[key]
        for key in ("snr_db", "duty_cycle", "peak_power_dbm", "noise_floor_dbm", "hop_count")
        if observation.get(key) is not None
    }
    pattern = observation.get("burst_pattern")
    if pattern in {p.value for p in BurstPattern}:
        optional["burst_pattern"] = pattern
    return Detection(
        detection_id=str(observation["id"]),
        capture_id=capture_id,
        center_freq_hz=max(observation["center_frequency_hz"], 1),
        bandwidth_hz=max(observation["bandwidth_hz"], 1),
        **optional,
    )


def build_result(rows, observations, names, profile, question=QUESTION):
    """rows are analysis.run() output; observations are the rows Laya was given."""
    capture = Capture(
        capture_id=names["data"] or "upload",
        started_at=datetime.now(timezone.utc),
        source_type=SourceType.DATASET,
        site_id=profile.profile_id,
    )
    detections = [_detection(o, capture.capture_id) for o in observations]
    classifications = []
    for row in rows:
        choice, confidence = row["answers"][question]
        classifications.append(
            Classification(
                detection_id=str(row["id"]),
                method=Method.ML,
                model_name="laya",
                label=_label(choice),
                confidence=confidence,
                top3=[Candidate(label=_label(choice), confidence=confidence)],
                reasons=[row["state"]],
            )
        )
    by_id = {d.detection_id: d for d in detections}
    verdicts = [judge.judge(by_id[c.detection_id], c, profile) for c in classifications]
    return PipelineResult(
        generated_at=datetime.now(timezone.utc),
        capture=capture,
        detections=detections,
        classifications=classifications,
        verdicts=verdicts,
    )
