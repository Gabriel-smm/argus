import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipeline import analysis, lookup, server
from pipeline.inputs import InputError

ROOT = Path(__file__).resolve().parents[1]

QUESTIONS = {
    "mode": {
        "type": "choice",
        "instructions": "Which signal type is this most likely?",
        "criteria": {"morse": "Morse code; OOK", "other": "any other signal"},
    }
}
ROWS = [
    {"id": 0, "center_frequency_hz": 7030000, "bandwidth_hz": 100, "modulation": "OOK"},
    {"id": 1, "center_frequency_hz": 14230000, "bandwidth_hz": 2700, "modulation": "FM"},
]


def fake_run(questions, observations):
    # Row 0 gets the first answer (Morse), every other row gets "other".
    first = next(iter(questions["mode"]["criteria"]))
    return [
        {
            "id": observation["id"],
            "state": f"state of {observation['id']}.",
            "answers": {"mode": (first if observation["id"] == 0 else "other", 0.9)},
        }
        for observation in observations
    ]


def body(knowledge=None, data=None):
    return {
        "knowledge": {
            "name": "questions.json",
            "text": json.dumps(QUESTIONS) if knowledge is None else knowledge,
        },
        "data": {
            "name": "observations.json",
            "text": json.dumps(ROWS) if data is None else data,
        },
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(analysis, "run", fake_run)
    monkeypatch.setattr(server, "_active", None)
    monkeypatch.setattr(server, "_source", None)
    return TestClient(server.app)


def many_rows(count):
    return json.dumps([{**ROWS[0], "id": index} for index in range(count)])


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_no_context_before_a_run(client):
    assert client.get("/context").json() == {"active": False, "running": False}


def test_classify_returns_a_summary_and_activates_the_context(client):
    response = client.post("/classify", json=body())
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["observations"] == 2
    assert summary["questions"][0]["counts"] == {"morse": 1, "other": 1}

    context = client.get("/context").json()
    assert context["active"] is True
    assert context["summary"] == summary
    assert "- morse (1): 0" in context["context"]


def test_classify_accepts_several_files(client):
    questions = json.loads((ROOT / "data" / "data-full.json").read_text())
    response = client.post(
        "/classify",
        json={
            "knowledge": [
                {"name": "data_1.json", "text": (ROOT / "data" / "data_1.json").read_text()},
                {"name": "data_2.json", "text": (ROOT / "data" / "data_2.json").read_text()},
            ],
            "data": [
                {"name": "a.json", "text": json.dumps([ROWS[0]])},
                {"name": "b.json", "text": json.dumps([ROWS[1]])},
            ],
        },
    )
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["knowledge_name"] == "data_1.json, data_2.json"
    assert summary["data_name"] == "a.json, b.json"
    assert summary["observations"] == 2
    assert summary["questions"][0]["counts"] == {
        option: 1 if option in ("enemy", "other") else 0
        for option in questions["mode"]["criteria"]
    }


def test_criteria_only_knowledge_is_a_400(client):
    response = client.post(
        "/classify",
        json=body(knowledge=(ROOT / "data" / "data_2.json").read_text()),
    )
    assert response.status_code == 400
    assert response.json()["field"] == "knowledge"
    assert "instructions" in response.json()["error"]


def test_clearing_the_context(client):
    client.post("/classify", json=body())
    assert client.delete("/context").json() == {"active": False, "running": False}
    assert client.get("/context").json()["active"] is False
    refused = client.post("/reclassify", json={"count": 1})
    assert refused.status_code == 400
    assert "Library" in refused.json()["error"]


def test_reclassify_remaining_replaces_the_window(client):
    first = client.post("/classify", json=body(data=many_rows(105)))
    assert first.status_code == 200
    assert first.json()["summary"]["observations"] == 100
    assert first.json()["summary"]["row_offset"] == 0

    response = client.post("/reclassify", json={"remaining": True})
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["observations"] == 5
    assert summary["row_offset"] == 100
    context = client.get("/context").json()
    assert context["summary"] == summary
    assert "rows 101\u2013105 of 105" in context["context"]
    assert "Rows 1\u2013100 are not part of this result." in context["context"]


def test_reclassify_count_starts_from_the_first_row(client):
    client.post("/classify", json=body(data=many_rows(10)))
    response = client.post("/reclassify", json={"count": 3})
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["observations"] == 3
    assert summary["row_offset"] == 0
    assert "first 3 of 10" in client.get("/context").json()["context"]
    assert "7 rows have not been classified." in client.get("/context").json()["context"]


def test_reclassify_remaining_count_is_the_next_batch(client):
    client.post("/classify", json=body(data=many_rows(105)))
    response = client.post("/reclassify", json={"remaining": True, "count": 3})
    summary = response.json()["summary"]
    assert summary["row_offset"] == 100
    assert summary["observations"] == 3


def test_reclassify_clamps_a_count_past_the_end(client):
    client.post("/classify", json=body())
    response = client.post("/reclassify", json={"count": 50})
    assert response.status_code == 200
    assert response.json()["summary"]["observations"] == 2


def test_reclassify_without_a_run_is_a_400(client):
    response = client.post("/reclassify", json={"remaining": True})
    assert response.status_code == 400
    assert "Library" in response.json()["error"]


def test_reclassify_remaining_when_nothing_is_left_is_a_400(client):
    client.post("/classify", json=body())
    response = client.post("/reclassify", json={"remaining": True})
    assert response.status_code == 400
    assert "already been classified" in response.json()["error"]
    assert client.get("/context").json()["summary"]["observations"] == 2


def test_reclassify_rejects_a_non_positive_count(client):
    client.post("/classify", json=body())
    response = client.post("/reclassify", json={"count": 0})
    assert response.status_code == 400
    assert "at least 1" in response.json()["error"]


def test_reclassify_while_one_is_going_is_a_409(client):
    client.post("/classify", json=body(data=many_rows(105)))
    assert server._lock.acquire(blocking=False)
    try:
        response = client.post("/reclassify", json={"remaining": True})
        assert response.status_code == 409
        assert client.get("/context").json()["running"] is True
    finally:
        server._lock.release()


def test_malformed_knowledge_is_a_400_on_that_field(client):
    response = client.post("/classify", json=body(knowledge="{nope"))
    assert response.status_code == 400
    assert response.json()["field"] == "knowledge"
    assert "line 1" in response.json()["error"]


def test_bad_data_is_a_400_on_that_field(client):
    response = client.post("/classify", json=body(data=json.dumps([{"id": 1}])))
    assert response.status_code == 400
    assert response.json()["field"] == "data"
    assert "Row 1" in response.json()["error"]


def test_missing_file_is_a_400(client):
    response = client.post("/classify", json={"knowledge": body()["knowledge"]})
    assert response.status_code == 400
    assert "error" in response.json()


def test_a_failed_run_keeps_the_previous_context(client, monkeypatch):
    client.post("/classify", json=body())
    monkeypatch.setattr(analysis, "run", lambda *_: (_ for _ in ()).throw(RuntimeError("out of memory")))
    response = client.post("/classify", json=body())
    assert response.status_code == 500
    assert "out of memory" in response.json()["error"]
    assert client.get("/context").json()["active"] is True


def test_ollama_down_is_a_502(client, monkeypatch):
    def unreachable(*_):
        raise analysis.OllamaError("Ollama is not reachable at http://127.0.0.1:11434: refused")

    monkeypatch.setattr(analysis, "run", unreachable)
    response = client.post("/classify", json=body())
    assert response.status_code == 502
    assert "Ollama is not reachable" in response.json()["error"]


def test_a_question_laya_cannot_fit_is_a_400_on_knowledge(client, monkeypatch):
    def too_long(*_):
        raise InputError("knowledge", "Question 'mode' does not fit in HEAD_MAX_LEN=448.")

    monkeypatch.setattr(analysis, "run", too_long)
    response = client.post("/classify", json=body())
    assert response.status_code == 400
    assert response.json()["field"] == "knowledge"


def test_a_second_run_while_one_is_going_is_a_409(client):
    assert server._lock.acquire(blocking=False)
    try:
        response = client.post("/classify", json=body())
        assert response.status_code == 409
        assert client.get("/context").json()["running"] is True
    finally:
        server._lock.release()


def test_scene_lists_the_demo_signals_without_running_laya(client):
    res = client.get("/scene")
    assert res.status_code == 200
    scene = res.json()
    assert scene["title"] == "Notre Dame campus"
    assert "not a live radio" in scene["badge"]
    assert len(scene["signals"]) == scene["total"] > 0
    assert client.get("/context").json()["active"] is False


def test_scan_runs_the_built_in_scene_and_labels_it_as_a_demo(client):
    res = client.post("/scan", json={})
    assert res.status_code == 200
    summary = res.json()["summary"]
    assert summary["scene"]["badge"].startswith("Demo mode")
    assert client.get("/context").json()["summary"]["scene"] == summary["scene"]


def test_unknown_scene_is_refused(client):
    assert client.post("/scan", json={"scene": "moon"}).status_code == 404
    assert client.get("/scene", params={"name": "moon"}).status_code == 404


def test_scene_signals_carry_their_site_check(client):
    signals = client.get("/scene").json()["signals"]
    for signal in signals:
        assert signal["triage"] in lookup.GROUPS
        assert signal["kind"] and signal["title"]
    # The demo file says which group each signal should land in; /scene must agree.
    rows = [
        json.loads(line)
        for line in (ROOT / "data" / "observations-site-demo.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    wanted = {str(row["id"]): row["expected_triage"] for row in rows}
    assert {signal["id"]: signal["triage"] for signal in signals} == wanted
    by_title = {signal["title"] for signal in signals}
    assert {"Something on GPS", "Possible drone", "Normal here"} <= by_title


def test_scene_gives_the_sensor_location_from_the_site_profile(client):
    location = client.get("/scene").json()["location"]
    assert location == {
        "name": "Notre Dame campus (demo site)",
        "latitude": 41.703,
        "longitude": -86.239,
        "source": "site_profile",
    }


def test_scene_location_is_null_when_the_site_profile_cannot_be_read(client, monkeypatch):
    monkeypatch.setenv("ARGUS_SITE", "data/context/no-such-site.json")
    res = client.get("/scene")
    assert res.status_code == 200
    assert res.json()["location"] is None


def test_a_result_says_which_site_and_files_it_used(client):
    summary = client.post("/scan", json={}).json()["summary"]
    found = summary["provenance"]
    assert found["site"]["name"].startswith("Notre Dame")
    assert isinstance(found["site"]["latitude"], float) and isinstance(found["site"]["longitude"], float)
    assert found["versions"]["band_table"].startswith("bands.csv sha256:")
    assert found["versions"]["site_profile"].startswith("site.json sha256:")
    assert found["versions"]["model"]
    assert client.get("/context").json()["summary"]["provenance"] == found


def test_a_result_stands_when_the_site_profile_cannot_be_read(client, monkeypatch):
    monkeypatch.setenv("ARGUS_SITE", "data/context/no-such-site.json")
    res = client.post("/scan", json={})
    assert res.status_code == 200
    assert res.json()["summary"]["provenance"] is None


def test_scene_still_plays_when_the_site_check_cannot_load(client, monkeypatch):
    def broken(_observations):
        raise FileNotFoundError("no site file")

    monkeypatch.setattr(server, "check_all", broken)
    res = client.get("/scene")
    assert res.status_code == 200
    signals = res.json()["signals"]
    assert signals and all("triage" not in signal for signal in signals)
