import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from nutrition_service.api import create_app
from nutrition_service.client import NutritionServiceClient
from nutrition_service.cli import cli


def test_health_endpoint_reports_ok():
    client = TestClient(create_app())

    response = client.get("/api/nutrition/v1/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_analyze_endpoint_returns_candidate_set():
    app = create_app()
    received_payloads = []

    def resolve_analysis(payload):
        received_payloads.append(payload)
        return {
            "candidate_set_id": "set-1",
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "title": "Protein bar",
                    "calories": 230,
                    "confidence": 0.91,
                    "reason_text": "matched wrapper text",
                }
            ],
        }

    app.state.resolve_analysis = resolve_analysis
    payload = {"session_id": "telegram:dm:1", "caption_text": "lunch", "image_paths": ["/tmp/photo.jpg"]}
    client = TestClient(app)

    response = client.post("/api/nutrition/v1/analyze", json=payload)

    assert response.status_code == 200
    assert response.json()["candidate_set_id"] == "set-1"
    assert received_payloads == [payload]


def test_analyze_endpoint_awaits_async_resolver():
    app = create_app()

    async def resolve_analysis(payload):
        return {
            "candidate_set_id": "set-async",
            "payload": payload,
        }

    app.state.resolve_analysis = resolve_analysis
    client = TestClient(app)

    response = client.post(
        "/api/nutrition/v1/analyze",
        json={"session_id": "telegram:dm:1", "caption_text": "lunch", "image_paths": ["/tmp/photo.jpg"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "candidate_set_id": "set-async",
        "payload": {"session_id": "telegram:dm:1", "caption_text": "lunch", "image_paths": ["/tmp/photo.jpg"]},
    }

def test_select_endpoint_logs_selection():
    client = TestClient(create_app())

    response = client.post("/api/nutrition/v1/select", json={"candidate_id": "cand-1"})

    assert response.status_code == 200
    assert response.json() == {"logged": True}


def test_correct_endpoint_logs_correction():
    client = TestClient(create_app())

    response = client.post("/api/nutrition/v1/correct", json={"candidate_id": "cand-1"})

    assert response.status_code == 200
    assert response.json() == {"logged": True}


def test_analyze_meal_posts_json_and_returns_response():
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return httpx.Response(200, json={"candidate_set_id": "set-1"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url="http://ignored.test", transport=transport)
    service_client = NutritionServiceClient(base_url="http://nutrition.test", client=client)

    response = service_client.analyze_meal(
        {
            "session_id": "telegram:dm:1",
            "caption_text": "lunch",
            "image_paths": ["/tmp/photo.jpg"],
        }
    )

    assert response == {"candidate_set_id": "set-1"}
    assert len(requests_seen) == 1
    assert requests_seen[0].method == "POST"
    assert str(requests_seen[0].url) == "http://nutrition.test/api/nutrition/v1/analyze"
    assert requests_seen[0].headers["content-type"].startswith("application/json")
    assert json.loads(requests_seen[0].content) == {
        "session_id": "telegram:dm:1",
        "caption_text": "lunch",
        "image_paths": ["/tmp/photo.jpg"],
    }


def test_analyze_meal_uses_injected_client_base_url_when_base_url_is_default():
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return httpx.Response(200, json={"candidate_set_id": "set-1"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url="http://nutrition.test", transport=transport)
    service_client = NutritionServiceClient(client=client)

    response = service_client.analyze_meal({"session_id": "telegram:dm:1"})

    assert response == {"candidate_set_id": "set-1"}
    assert len(requests_seen) == 1
    assert str(requests_seen[0].url) == "http://nutrition.test/api/nutrition/v1/analyze"


def test_serve_command_runs_uvicorn_with_settings(monkeypatch):
    app = object()
    captured = {}

    monkeypatch.setattr("nutrition_service.cli.create_app", lambda: app)
    monkeypatch.setattr(
        "nutrition_service.cli.NutritionSettings",
        lambda: SimpleNamespace(bind_host="0.0.0.0", bind_port=9999),
    )
    monkeypatch.setattr(
        "nutrition_service.cli.uvicorn.run",
        lambda *args, **kwargs: captured.update({"args": args, "kwargs": kwargs}),
    )

    result = cli.main(args=["serve"], standalone_mode=False)

    assert result is None
    assert captured["args"] == (app,)
    assert captured["kwargs"] == {"host": "0.0.0.0", "port": 9999}
