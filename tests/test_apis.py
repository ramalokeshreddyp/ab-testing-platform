from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from config_api.main import app as config_app
from event_api.main import app as event_app
from decision_engine.main import app as decision_app


def test_config_api_validation_errors():
    client = TestClient(config_app)

    invalid_payload_99 = {
        "name": "exp_invalid_99",
        "description": "Invalid test",
        "config": {
            "variants": [
                {"name": "control", "weight": 50},
                {"name": "treatment", "weight": 49}
            ],
            "targeting_rules": []
        }
    }
    response = client.post("/experiments", json=invalid_payload_99)
    assert response.status_code == 422

    invalid_payload_101 = {
        "name": "exp_invalid_101",
        "description": "Invalid test",
        "config": {
            "variants": [
                {"name": "control", "weight": 50},
                {"name": "treatment", "weight": 51}
            ],
            "targeting_rules": []
        }
    }
    response = client.post("/experiments", json=invalid_payload_101)
    assert response.status_code == 422


def test_event_api_validation():
    client = TestClient(event_app)

    invalid_event = {
        "event_type": "assignment",
        "payload": {
            "experiment_id": 1,
            "variant_name": "control"
        }
    }
    response = client.post("/events", json=invalid_event)
    assert response.status_code == 422

    invalid_event_2 = {
        "payload": {
            "user_id": "user_123",
            "experiment_id": 1,
            "variant_name": "control"
        }
    }
    response = client.post("/events", json=invalid_event_2)
    assert response.status_code == 422


def test_event_api_success_with_mock():
    with patch("event_api.main.channel") as mock_channel:
        mock_channel.is_closed = False
        mock_channel.default_exchange.publish = AsyncMock()

        client = TestClient(event_app)
        valid_event = {
            "event_type": "assignment",
            "payload": {
                "user_id": "user_123",
                "experiment_id": 1,
                "variant_name": "control"
            }
        }
        response = client.post("/events", json=valid_event)
        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "detail": "Event queued for processing."}


def test_health_endpoints():
    with TestClient(config_app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    with TestClient(decision_app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    with TestClient(event_app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"
