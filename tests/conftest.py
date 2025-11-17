# --------------------------------------------------------------------------
# The Module configures pytest env.
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
import asyncio
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.database import get_db
from src.main import create_app

# Configure test environment
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://testuser:testpass@localhost:5433/bifrost_test"
)

# Create sync engine and session factory for tests
test_engine = create_engine(TEST_DATABASE_URL, future=True)
TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
def db_session() -> Session:
    """Create a new database session for a test with transaction rollback"""
    session: Session = TestSessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def test_services(db_session: Session):
    """Get test services from database"""
    from src.crud.service import get_services

    services = get_services(db_session, active_only=False)
    return {service.name: service for service in services}


@pytest_asyncio.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    """Create FastAPI app with overridden dependencies"""
    from src.services.services import ServiceRegistry

    app = create_app()

    # Initialize service registry with real database data
    app.state.service_registry = ServiceRegistry()
    with TestSessionLocal() as session:
        await app.state.service_registry.initialize(db_session=session)

    # Override database dependency
    def override_get_db():
        with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    yield app

    # Clean up
    await app.state.service_registry.cleanup()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_auth_admin():
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
def mock_auth_user():
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
def mock_auth_super_admin():
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
def mock_httpx_get():
    """Mock httpx.AsyncClient.get for external service calls"""
    with patch("httpx.AsyncClient.get") as mock:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}
        mock.return_value = mock_response
        yield mock


@pytest.fixture
def mock_httpx_post():
    """Mock httpx.AsyncClient.post for external service calls"""
    with patch("httpx.AsyncClient.post") as mock:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock.return_value = mock_response
        yield mock
