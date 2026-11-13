"""HTTP service the dashboard uses to run Laya and read back what it found."""

import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pipeline import analysis, checkpoint
from pipeline.context import build_context, build_summary
from pipeline.inputs import MAX_OBSERVATIONS, InputError, combine_observations, merge_knowledge
from pipeline.lookup import check_all, load_site, provenance

app = FastAPI(title="Laya pipeline")

# One operator, one GPU: a single run at a time, and a single result kept.
# The last upload stays too, so a later run can classify a different slice.
_lock = threading.Lock()
_active = None
_source = None


class Upload(BaseModel):
    name: str
    text: str


class ClassifyRequest(BaseModel):
    knowledge: Upload | list[Upload]
    data: Upload | list[Upload]


class ScanRequest(BaseModel):
    scene: str = "campus"


# Built-in scenes for the Scan button: files shipped in data/, so a demo needs no uploads.
# The badge says plainly what is being shown; it is not a live radio.
ROOT = Path(__file__).resolve().parent.parent
SCENES = {
    "campus": {
        "title": "Notre Dame campus",
        "badge": "Demo mode: sample campus signals, not a live radio",
        "knowledge": ROOT / "data" / "data-full.json",
        "data": ROOT / "data" / "observations-site-demo.jsonl",
    },
}


class ReclassifyRequest(BaseModel):
    count: int | None = None
    remaining: bool = False


def _uploads(value):
    return value if isinstance(value, list) else [value]


def _error(status, message, field=None):
    return JSONResponse({"error": message, "field": field}, status_code=status)


def _state():
    state = {"active": _active is not None, "running": _lock.locked()}
    return {**state, **_active} if _active else state


@app.exception_handler(RequestValidationError)
def _incomplete_request(request, exc):
    if request.url.path.rstrip("/").endswith("/reclassify"):
        return _error(400, "Say how many rows to classify, as a whole number.")
    return _error(400, "Both a knowledge file and a data file are required.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/context")
def context():
    """The current classification, as the chat model reads it."""
    return _state()


@app.delete("/context")
def clear():
    global _active, _source
    _active = None
    _source = None
    return _state()


def _names(knowledge, data):
    return {
        "knowledge": ", ".join(name for name, _text in knowledge),
        "data": ", ".join(name for name, _text in data),
    }


def _provenance():
    """Site, coordinates and file versions behind a result, so a packet can say what it used.

    None if the site profile or band table cannot be read; the result itself still stands.
    """
    try:
        found = provenance()
    except (OSError, ValueError, KeyError):
        return None
    found["versions"]["model"] = checkpoint.label()
    return found


def _location():
    """Where the sensor is, from the site profile. Never from a GPS fix or the browser.

    None if the site profile cannot be read.
    """
    try:
        site = load_site()
    except (OSError, ValueError, KeyError):
        return None
    location = {"name": site.get("name", "this site"), "source": "site_profile"}
    for key in ("latitude", "longitude"):
        if isinstance(site.get(key), (int, float)):
            location[key] = site[key]
    return location


def _execute(questions, observations, names, total, offset, knowledge, data):
    """Classify one slice and, only if that succeeds, make it the current result."""
    global _active, _source
    if not _lock.acquire(blocking=False):
        return _error(409, "Laya is already classifying. Wait for it to finish.")
    try:
        started = time.perf_counter()
        rows = analysis.run(questions, observations)
        seconds = time.perf_counter() - started
    except InputError as exc:
        return _error(400, str(exc), exc.field)
    except analysis.OllamaError as exc:
        return _error(502, str(exc))
    except Exception as exc:
        return _error(500, f"Laya failed: {exc}")
    finally:
        _lock.release()
    summary = build_summary(names, questions, rows, total, seconds, offset)
    summary["provenance"] = _provenance()
    _active = {
        "summary": summary,
        "context": build_context(names, questions, rows, total, offset),
        "offset": offset,
        "count": len(rows),
    }
    _source = {"knowledge": knowledge, "data": data, "names": names}
    return {"summary": summary}


@app.post("/classify")
def classify(request: ClassifyRequest):
    """Run Laya on the first 100 rows and make the result the current one."""
    knowledge = _uploads(request.knowledge)
    data = _uploads(request.data)
    if not knowledge or not data:
        return _error(400, "Both a knowledge file and a data file are required.")
    knowledge_parts = [(item.name, item.text) for item in knowledge]
    data_parts = [(item.name, item.text) for item in data]
    try:
        questions = merge_knowledge(knowledge_parts)
        observations, total = combine_observations(data_parts)
    except InputError as exc:
        return _error(400, str(exc), exc.field)
    return _execute(
        questions,
        observations,
        _names(knowledge_parts, data_parts),
        total,
        0,
        knowledge_parts,
        data_parts,
    )


def _scene(name):
    scene = SCENES.get(name)
    if scene is None:
        return None, _error(404, f"Unknown scene {name!r}. Known scenes: {', '.join(SCENES)}.")
    return scene, None


@app.get("/scene")
def scene(name: str = "campus"):
    """What the Scan button will play: title, badge and each signal, for the animation.

    Each signal carries its site-check result (kind, title, triage) so the sweep can color
    and name dots before Laya finishes. The site check is plain rules, so this is instant.
    """
    found, error = _scene(name)
    if error:
        return error
    try:
        observations, total = combine_observations(
            [(found["data"].name, found["data"].read_text(encoding="utf-8"))]
        )
    except (OSError, InputError) as exc:
        return _error(500, f"The demo scene could not be read: {exc}")
    try:
        lookups = check_all(observations)
    except (OSError, ValueError, KeyError):
        # A broken band table or site file should not stop the animation; dots stay uncolored.
        lookups = [None] * len(observations)
    signals = []
    for row, lookup in zip(observations, lookups):
        signal = {"id": str(row["id"]), "frequency_hz": row["center_frequency_hz"]}
        if lookup:
            signal.update(kind=lookup["kind"], title=lookup["title"], triage=lookup["triage"])
        signals.append(signal)
    return {
        "name": name,
        "title": found["title"],
        "badge": found["badge"],
        "total": total,
        "signals": signals,
        "location": _location(),
    }


@app.post("/scan")
def scan(request: ScanRequest):
    """Run a built-in scene through Laya and the site check, as if the radio had just heard it."""
    found, error = _scene(request.scene)
    if error:
        return error
    try:
        knowledge_parts = [(found["knowledge"].name, found["knowledge"].read_text(encoding="utf-8"))]
        data_parts = [(found["data"].name, found["data"].read_text(encoding="utf-8"))]
        questions = merge_knowledge(knowledge_parts)
        observations, total = combine_observations(data_parts)
    except OSError as exc:
        return _error(500, f"The demo scene could not be read: {exc}")
    except InputError as exc:
        return _error(400, str(exc), exc.field)
    response = _execute(
        questions,
        observations,
        _names(knowledge_parts, data_parts),
        total,
        0,
        knowledge_parts,
        data_parts,
    )
    if isinstance(response, dict) and _active:
        badge = {"title": found["title"], "badge": found["badge"]}
        _active["summary"]["scene"] = badge
        response["summary"]["scene"] = badge
    return response


@app.post("/reclassify")
def reclassify(request: ReclassifyRequest):
    """Classify another slice of the files from the last Library run."""
    if _source is None or _active is None:
        return _error(400, "Run Laya from the Library first.")
    if request.count is not None and request.count < 1:
        return _error(400, "The number of rows must be at least 1.")
    total = _active["summary"]["total_rows"]
    if request.remaining:
        offset = _active["offset"] + _active["count"]
        available = total - offset
        if available < 1:
            return _error(400, "Every row has already been classified.")
        limit = available if request.count is None else min(request.count, available)
    else:
        if total < 1:
            return _error(400, "The file has no observations.")
        limit = min(MAX_OBSERVATIONS if request.count is None else request.count, total)
        offset = 0
    try:
        questions = merge_knowledge(_source["knowledge"])
        observations, total = combine_observations(_source["data"], limit=limit, offset=offset)
    except InputError as exc:
        return _error(400, str(exc), exc.field)
    if not observations:
        return _error(400, "There are no rows in that range.")
    return _execute(
        questions,
        observations,
        _source["names"],
        total,
        offset,
        _source["knowledge"],
        _source["data"],
    )
