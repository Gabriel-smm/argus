import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipeline import analysis, judge, server
from pipeline.schema import PipelineResult

from test_server import body, fake_run

DEMO = Path(__file__).resolve().parents[1] / "data" / "contract"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(analysis, "run", fake_run)
    for name in ("_active", "_source", "_result"):
        monkeypatch.setattr(server, name, None)
    monkeypatch.setattr(server, "_profile", judge.load_profile())
    return TestClient(server.app)


@pytest.mark.parametrize("scenario", ["drone", "jamming", "normal"])
def test_demo_scenarios_follow_the_contract(client, scenario):
    response = client.get(f"/demo/{scenario}")
    assert response.status_code == 200
    PipelineResult.model_validate(response.json())


def test_unknown_demo_scenario_is_404(client):
    assert client.get("/demo/nope").status_code == 404


def test_no_result_before_a_run(client):
    assert client.get("/result").status_code == 404


def test_a_run_produces_a_judged_result(client):
    assert client.post("/classify", json=body()).status_code == 200
    result = PipelineResult.model_validate(client.get("/result").json())
    assert [v.detection_id for v in result.verdicts] == ["0", "1"]
    assert "Site verdicts" in client.get("/context").json()["context"]


def test_clearing_drops_the_result(client):
    client.post("/classify", json=body())
    client.delete("/context")
    assert client.get("/result").status_code == 404


def test_the_site_profile_can_be_replaced(client):
    profile = json.loads((DEMO / "site_profile_campus.json").read_text())
    profile["blue_min_confidence"] = 0.95
    assert client.put("/site-profile", json=profile).status_code == 200
    assert client.get("/site-profile").json()["blue_min_confidence"] == 0.95
