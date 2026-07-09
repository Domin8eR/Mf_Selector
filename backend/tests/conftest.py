"""
Shared pytest fixtures.

Requires Docker Compose to be running (postgres must be reachable).
Each test wraps its DB operations in a transaction that is rolled back
after the test, so tests are fully isolated without re-creating tables.

Test database: altstreet_test (created automatically on first run).
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import get_password_hash
from app.main import app
from app.models import Base
from app.models.firm import Firm
from app.models.user import User, UserRole

# Use a dedicated test database to avoid touching dev data
TEST_DB_URL = settings.database_url.replace(
    f"/{settings.database_url.rsplit('/', 1)[-1]}",
    "/altstreet_test",
)

_engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
_TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(scope="session", autouse=True)
def _create_test_db() -> None:
    """Create all tables once per test session; drop them at the end."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def db() -> Session:
    """
    Yield a DB session wrapped in a savepoint.
    The outer transaction is rolled back after each test so rows never persist.
    """
    connection = _engine.connect()
    outer_tx = connection.begin()
    session = _TestingSession(bind=connection)
    # Nested savepoint allows the router code to call session.commit()
    # without actually committing to the DB.
    connection.begin_nested()

    yield session

    session.close()
    outer_tx.rollback()
    connection.close()


@pytest.fixture()
def client(db: Session) -> TestClient:
    """FastAPI TestClient with the get_db dependency overridden to use the test session."""
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---- Seed helpers -----------------------------------------------------------

@pytest.fixture()
def test_firm(db: Session) -> Firm:
    firm = Firm(id=uuid.uuid4(), name="AltStreet Test", slug="altstreet-test")
    db.add(firm)
    db.flush()
    return firm


@pytest.fixture()
def test_admin(db: Session, test_firm: Firm) -> User:
    user = User(
        id=uuid.uuid4(),
        firm_id=test_firm.id,
        email="admin@altstreet.test",
        hashed_password=get_password_hash("testpass123"),
        full_name="Test Admin",
        role=UserRole.admin,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def admin_token(client: TestClient, test_admin: User) -> str:
    """Return a valid JWT for the test admin user."""
    response = client.post(
        "/auth/login",
        data={"username": test_admin.email, "password": "testpass123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]
