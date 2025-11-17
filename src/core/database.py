# --------------------------------------------------------------------------
# Database connection module for Bifrost Gateway
#
# @author bnbong bbbong9@gmail.com
# --------------------------------------------------------------------------
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.core.config import settings

DATABASE_URL = settings.DATABASE_URL

# Create sync engine
engine = create_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_pre_ping=True,
)

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
