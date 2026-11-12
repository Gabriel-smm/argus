"""
Argus data contract, v0.1.0 (DRAFT for team review).

One typed record per pipeline stage, so every teammate builds against the same shapes:

    Capture -> Detection -> Classification -> Verdict   (+ JammingAssessment)
                                  ^                ^
                           LibraryEntry        SiteProfile

Rules enforced in code (change them here, in one place):
  * Receive-only: Capture.passive_only is always True.
  * A Verdict can only be BLUE if confidence >= the site's blue threshold.
  * Every classification / verdict points at a real detection.
  * Verdict confidence equals the classification confidence it was based on.

Locations are where the SENSOR was, not where the emitter is (one sensor cannot localize).
Edit freely: search for "DECISION" to find choices the team still needs to make.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1.0"


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------------
class SignalClass(str, Enum):
    # DECISION: drone is its own class (not folded into "other").
    WIFI = "wifi"
    BLUETOOTH = "bluetooth"
    CELLULAR = "cellular"
    ISM_IOT = "ism_iot"
    PULSED_RADAR = "pulsed_radar"
    DRONE = "drone"
    OTHER = "other"
    UNKNOWN = "unknown"  # the "I don't know" answer


class BurstPattern(str, Enum):
    CONTINUOUS = "continuous"
    BURSTY = "bursty"
    HOPPING = "hopping"
    PULSED = "pulsed"
    UNKNOWN = "unknown"


class Disposition(str, Enum):
    BLUE = "blue"    # expected here
    WHITE = "white"  # unknown / not enough confidence
    RED = "red"      # not expected here


class Affiliation(str, Enum):
    # DECISION: the project summary says ours / civilian / possible threat,
    # the pitch deck says expected / unknown / hostile. Both are kept for now;
    # pick one vocabulary and delete the other.
    OURS = "ours"
    CIVILIAN = "civilian"
    POSSIBLE_THREAT = "possible_threat"
    UNKNOWN = "unknown"


class UseCase(str, Enum):
    DRONE = "drone"
    JAMMING = "jamming"
    SITE_BASELINE = "site_baseline"


class SourceType(str, Enum):
    LIVE_SDR = "live_sdr"
    IQ_FILE = "iq_file"
    SWEEP_FILE = "sweep_file"
    DATASET = "dataset"


class Method(str, Enum):
    ML = "ml"
    LOOKUP = "lookup"
    RULE = "rule"


class SiteType(str, Enum):
    CAMPUS = "campus"
    POWER_PLANT = "power_plant"
    FIELD_FORWARD = "field_forward"
    OTHER = "other"


class LocationSource(str, Enum):
    GPS = "gps"
    MANUAL = "manual"
    MAP_PIN = "map_pin"


# ----------------------------------------------------------------------------
# Small shared pieces
# ----------------------------------------------------------------------------
class FreqRange(Base):
    min_hz: float = Field(gt=0)
    max_hz: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self):
        if self.min_hz > self.max_hz:
            raise ValueError("min_hz must be <= max_hz")
        return self

    def contains(self, hz: float) -> bool:
        return self.min_hz <= hz <= self.max_hz


class GeoPoint(Base):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: Optional[float] = Field(default=None, ge=0)
    source: LocationSource = LocationSource.GPS


# ----------------------------------------------------------------------------
# Stage 1: Capture (one recording or sweep)
# ----------------------------------------------------------------------------
class Capture(Base):
    capture_id: str
    started_at: datetime
    source_type: SourceType
    device: Optional[str] = None            # e.g. "rtl-sdr-v4", "hackrf-one"
    sample_rate_hz: Optional[float] = Field(default=None, gt=0)
    freq_range: Optional[FreqRange] = None  # what the radio covered
    gain_db: Optional[float] = None
    file_name: Optional[str] = None
    site_id: Optional[str] = None
    sensor_location: Optional[GeoPoint] = None  # where the SENSOR was
    passive_only: Literal[True] = True          # receive-only, always
    notes: Optional[str] = None


# ----------------------------------------------------------------------------
# Stage 2: Detection (one signal found in a capture; output of the Python detector)
# ----------------------------------------------------------------------------
class Detection(Base):
    detection_id: str
    capture_id: str
    center_freq_hz: float = Field(gt=0)
    bandwidth_hz: float = Field(gt=0)
    peak_power_dbm: Optional[float] = None
    snr_db: Optional[float] = None
    noise_floor_dbm: Optional[float] = None
    duty_cycle: Optional[float] = Field(default=None, ge=0, le=1)
    burst_pattern: BurstPattern = BurstPattern.UNKNOWN
    hop_count: Optional[int] = Field(default=None, ge=0)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    sensor_location: Optional[GeoPoint] = None  # sensor position when heard


# ----------------------------------------------------------------------------
# Stage 3: Classification (output of the ML model or the lookup table)
# ----------------------------------------------------------------------------
class Candidate(Base):
    label: SignalClass
    confidence: float = Field(ge=0, le=1)


class Classification(Base):
    detection_id: str
    method: Method
    model_name: Optional[str] = None      # e.g. "lightgbm-6class" or "laya-rf-modes"
    model_version: Optional[str] = None
    label: SignalClass
    confidence: float = Field(ge=0, le=1)
    top3: list[Candidate] = Field(default_factory=list, max_length=3)
    reasons: list[str] = Field(default_factory=list)  # short, plain-English
    library_entry_id: Optional[str] = None            # set when lookup matched

    @model_validator(mode="after")
    def _top3_sorted(self):
        confs = [c.confidence for c in self.top3]
        if confs != sorted(confs, reverse=True):
            raise ValueError("top3 must be sorted by confidence, highest first")
        return self


# ----------------------------------------------------------------------------
# Reference data: the "field guide" (rare signals + plain-English text)
# ----------------------------------------------------------------------------
class LibraryEntry(Base):
    entry_id: str
    name: str
    signal_class: SignalClass
    typical_freq: Optional[FreqRange] = None
    typical_bandwidth_hz: Optional[FreqRange] = None  # min/max reuse FreqRange shape
    typical_pattern: BurstPattern = BurstPattern.UNKNOWN
    plain_english: str
    source: str                       # where the entry came from
    licence: str = "TBD"              # confirm before shipping


# ----------------------------------------------------------------------------
# Site profile (what is normal here). Policy lives here, not in code.
# ----------------------------------------------------------------------------
class ExpectedSignal(Base):
    label: SignalClass
    freq: FreqRange
    max_bandwidth_hz: Optional[float] = Field(default=None, gt=0)
    allowed_patterns: list[BurstPattern] = Field(default_factory=list)  # empty = any
    affiliation: Affiliation = Affiliation.CIVILIAN
    note: Optional[str] = None


class SiteProfile(Base):
    profile_id: str
    version: str
    name: str
    site_type: SiteType
    location: Optional[GeoPoint] = None
    expected: list[ExpectedSignal]
    # Classes that are RED when seen and not listed in `expected`.
    threat_classes: list[SignalClass] = Field(default_factory=lambda: [SignalClass.DRONE])
    # DECISION: confidence needed before a detection may be BLUE.
    blue_min_confidence: float = Field(default=0.80, ge=0, le=1)
    # Noise-floor rise (dB over baseline) that counts as possible jamming.
    jamming_noise_rise_db: float = Field(default=10.0, gt=0)
    baseline_noise_floor_dbm: dict[str, float] = Field(default_factory=dict)  # band name -> dBm
    # Governance fields (policy owner fills these in)
    owner: Optional[str] = None
    approved_by: Optional[str] = None
    approved_on: Optional[date] = None
    review_due: Optional[date] = None


# ----------------------------------------------------------------------------
# Stage 4: Verdict (output of the judging engine)
# ----------------------------------------------------------------------------
class Verdict(Base):
    detection_id: str
    disposition: Disposition
    affiliation: Affiliation = Affiliation.UNKNOWN
    reason: str                         # one line, plain English
    rule_id: Optional[str] = None       # which rule fired (auditability)
    profile_id: str
    profile_version: str
    confidence: float = Field(ge=0, le=1)
    blue_min_confidence: float = Field(ge=0, le=1)
    next_step: Optional[str] = None
    use_case: Optional[UseCase] = None

    @model_validator(mode="after")
    def _low_confidence_never_blue(self):
        if self.disposition == Disposition.BLUE and self.confidence < self.blue_min_confidence:
            raise ValueError(
                f"blue verdict needs confidence >= {self.blue_min_confidence}, got {self.confidence}"
            )
        return self


class JammingAssessment(Base):
    band: FreqRange
    baseline_noise_floor_dbm: float
    observed_noise_floor_dbm: float
    noise_rise_db: float
    expected_missing: list[str] = Field(default_factory=list)
    flagged: bool
    confidence: float = Field(ge=0, le=1)
    reason: str

    @model_validator(mode="after")
    def _rise_matches(self):
        expected = self.observed_noise_floor_dbm - self.baseline_noise_floor_dbm
        if abs(expected - self.noise_rise_db) > 0.5:
            raise ValueError("noise_rise_db must equal observed - baseline (within 0.5 dB)")
        return self


# ----------------------------------------------------------------------------
# Whole-run bundle: what the pipeline hands to the UI and the chat
# ----------------------------------------------------------------------------
class PipelineResult(Base):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    generated_at: datetime
    capture: Capture
    detections: list[Detection]
    classifications: list[Classification]
    verdicts: list[Verdict]
    jamming: Optional[JammingAssessment] = None

    @model_validator(mode="after")
    def _references_hold(self):
        ids = [d.detection_id for d in self.detections]
        if len(ids) != len(set(ids)):
            raise ValueError("detection_id values must be unique")
        known = set(ids)
        for d in self.detections:
            if d.capture_id != self.capture.capture_id:
                raise ValueError(f"{d.detection_id}: capture_id does not match capture")
        cls_by_id = {}
        for c in self.classifications:
            if c.detection_id not in known:
                raise ValueError(f"classification points at unknown detection {c.detection_id}")
            cls_by_id[c.detection_id] = c
        for v in self.verdicts:
            if v.detection_id not in known:
                raise ValueError(f"verdict points at unknown detection {v.detection_id}")
            c = cls_by_id.get(v.detection_id)
            if c is not None and abs(c.confidence - v.confidence) > 1e-9:
                raise ValueError(f"{v.detection_id}: verdict confidence differs from classification")
        return self
