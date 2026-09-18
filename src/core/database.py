# --------------------------------------------------------------------------
# Database connection module for Bifrost Gateway
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import Any, Dict, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.config import settings

DATABASE_URL = settings.DATABASE_URL

_engine_kwargs: Dict[str, Any] = {
    "echo": settings.DEBUG,
    "future": True,
    "pool_pre_ping": True,
}

if DATABASE_URL.startswith("sqlite"):
    # SQLite is used by the test suite only. Sessions are handed to threadpool
    # workers, so cross-thread use must be allowed and writers need a busy
    # timeout.
    _engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    _engine_kwargs.pop("pool_pre_ping", None)
    if ":memory:" in DATABASE_URL or DATABASE_URL.endswith("sqlite://"):
        # An in-memory database only exists inside its own connection, so a
        # single shared connection is the only way to keep one database.
        # Concurrent writers are not supported in this mode.
        _engine_kwargs["poolclass"] = StaticPool

# Create sync engine
engine = create_engine(DATABASE_URL, **_engine_kwargs)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Create declarative base
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Get database session"""
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_database_connection() -> bool:
    """Run a trivial query to prove the database is reachable.

    This is a blocking call and must be dispatched through a threadpool when
    called from an async context.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True
