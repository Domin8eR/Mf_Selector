"""Tests for /auth/login and /auth/me endpoints."""

from fastapi.testclient import TestClient

from app.models.user import User


def test_login_success(client: TestClient, test_admin: User) -> None:
    response = client.post(
        "/auth/login",
        data={"username": test_admin.email, "password": "testpass123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_login_wrong_password(client: TestClient, test_admin: User) -> None:
    response = client.post(
        "/auth/login",
        data={"username": test_admin.email, "password": "wrong"},
    )
    assert response.status_code == 401


def test_login_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        data={"username": "nobody@example.com", "password": "anything"},
    )
    assert response.status_code == 401


def test_get_me_returns_current_user(client: TestClient, test_admin: User, admin_token: str) -> None:
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == test_admin.email
    assert body["role"] == test_admin.role.value
    assert body["is_active"] is True


def test_get_me_without_token(client: TestClient) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_get_me_with_bad_token(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer totally.invalid.token"})
    assert response.status_code == 401
