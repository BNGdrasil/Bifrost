# --------------------------------------------------------------------------
# The Module configures pytest env.
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import AsyncGenerator, Dict, Iterator
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from src.core.database import Base, SessionLocal, engine, get_db
from src.main import create_app
from src.models.service import Service  # noqa: F401 - register table metadata
from src.schemas.service import ServiceCreate

# Baseline services every test suite expects to be present.
BASELINE_SERVICES = (
    ("qshing-server", "Qshing Server", "http://qshing-server:8080"),
    ("hello", "Hello Service", "http://hello:8080"),
    ("test-service", "Test Service", "http://test-service:8080"),
)


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> Iterator[None]:
    """Create the schema once per session.

    The suite runs against SQLite in memory by default and against a
    disposable PostgreSQL database in CI. create_all is a no-op when the
    tables already exist.
    """
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(scope="session", autouse=True)
def baseline_services(database_schema: None) -> Iterator[None]:
    """Seed the baseline services used by the read-only assertions."""
    from src.crud.service import create_service, get_service_by_name

    with SessionLocal() as session:
        for name, display_name, url in BASELINE_SERVICES:
            if get_service_by_name(session, name) is None:
                create_service(
                    session,
                    ServiceCreate(
                        name=name,
                        display_name=display_name,
                        url=url,
                        description=f"{display_name} for testing",
                    ),
                )
    yield


@pytest.fixture(scope="function")
def db_session() -> Iterator[Session]:
    """Create a new database session for a test"""
    session: Session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def test_services(db_session: Session) -> Dict[str, object]:
    """Get test services from database"""
    from src.crud.service import get_services

    services = get_services(db_session, active_only=False)
    return {service.name: service for service in services}


@pytest_asyncio.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    """Create FastAPI app with a registry loaded from the test database"""
    from src.services.services import ServiceProxy, ServiceRegistry, create_http_client

    application = create_app()

    http_client = create_http_client()
    application.state.http_client = http_client
    registry = ServiceRegistry(http_client=http_client)
    application.state.service_registry = registry
    application.state.service_proxy = ServiceProxy(registry, http_client)
    await registry.initialize()

    def override_get_db() -> Iterator[Session]:
        with SessionLocal() as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db

    yield application

    await registry.cleanup()
    await http_client.aclose()
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_auth_admin() -> Iterator[object]:
    """Mock auth server to return admin user"""
    with patch("src.core.permissions.verify_role_with_auth_server") as mock:
        mock.return_value = {
            "user_id": 1,
            "username": "admin",
            "role": "admin",
            "email": "admin@example.com",
        }
        yield mock


@pytest.fixture
def mock_auth_user() -> Iterator[object]:
    """Mock auth server to return regular user"""
    with patch("src.core.permissions.verify_role_with_auth_server") as mock:
        mock.return_value = {
            "user_id": 2,
            "username": "user",
            "role": "user",
            "email": "user@example.com",
        }
        yield mock


@pytest.fixture
def mock_auth_super_admin() -> Iterator[object]:
    """Mock auth server to return super admin"""
    with patch("src.core.permissions.verify_role_with_auth_server") as mock:
        mock.return_value = {
            "user_id": 1,
            "username": "superadmin",
            "role": "super_admin",
            "email": "superadmin@example.com",
        }
        yield mock


@pytest.fixture
def mock_auth_forbidden() -> Iterator[object]:
    """Mock auth server rejecting a non privileged user"""
    from fastapi import HTTPException, status

    with patch("src.core.permissions.verify_role_with_auth_server") as mock:
        mock.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden - Insufficient permissions",
        )
        yield mock


@pytest.fixture
def echo_transport() -> httpx.MockTransport:
    """Placeholder transport hook used by the proxy contract tests."""
    return httpx.MockTransport(lambda request: httpx.Response(204))
