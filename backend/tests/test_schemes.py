"""Tests for GET /schemes and GET /schemes/{id}."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.benchmark import Benchmark
from app.models.scheme import Scheme


def _make_scheme(db: Session, scheme_id: str, category: str = "Large Cap") -> Scheme:
    bm_id = f"NIFTY50-TRI-{uuid.uuid4().hex[:6]}"
    bm = Benchmark(id=bm_id, name="Nifty 50 TRI", index_type="TRI")
    db.add(bm)
    scheme = Scheme(
        id=scheme_id,
        name=f"Test Scheme {scheme_id}",
        amc_name="Test AMC",
        category=category,
        benchmark_id=bm_id,
    )
    db.add(scheme)
    db.flush()
    return scheme


def test_list_schemes_empty(client: TestClient) -> None:
    response = client.get("/schemes")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1


def test_list_schemes_returns_active_schemes(client: TestClient, db: Session) -> None:
    _make_scheme(db, "HDFC-LC-001", category="Large Cap")
    _make_scheme(db, "SBI-BC-001", category="Large Cap")

    response = client.get("/schemes")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_schemes_filter_by_category(client: TestClient, db: Session) -> None:
    _make_scheme(db, "HDFC-MC-001", category="Mid Cap")
    _make_scheme(db, "SBI-LC-002", category="Large Cap")

    response = client.get("/schemes?category=Mid+Cap")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["category"] == "Mid Cap"


def test_get_scheme_found(client: TestClient, db: Session) -> None:
    _make_scheme(db, "AXIS-BC-DIRECT")

    response = client.get("/schemes/AXIS-BC-DIRECT")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "AXIS-BC-DIRECT"
    assert body["plan_type"] == "growth"
    assert body["option_type"] == "direct"


def test_get_scheme_not_found(client: TestClient) -> None:
    response = client.get("/schemes/DOES-NOT-EXIST")
    assert response.status_code == 404
