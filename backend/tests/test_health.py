"""
Tests for the operational endpoints: /health and /version.

These are the first tests in the suite — they verify the app starts
and the VersionedResponse contract is met from the very first endpoint.
"""

from datetime import date

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_returns_versioned_response() -> None:
    response = client.get("/version")
    assert response.status_code == 200

    body = response.json()

    # All four required fields must be present (VersionedResponse contract)
    assert "data_version" in body
    assert "rule_version" in body
    assert "calculation_version" in body
    assert "as_of_date" in body


def test_version_as_of_date_is_today() -> None:
    response = client.get("/version")
    body = response.json()
    assert body["as_of_date"] == date.today().isoformat()


def test_version_fields_are_strings() -> None:
    response = client.get("/version")
    body = response.json()
    assert isinstance(body["data_version"], str)
    assert isinstance(body["rule_version"], str)
    assert isinstance(body["calculation_version"], str)
