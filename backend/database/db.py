"""
Database Connection & Session Management (SQLAlchemy 2.x)
Works with SQLite (local default, tests, Streamlit Cloud demo) and PostgreSQL (Neon).
The database is chosen by DATABASE_URL in .env — see backend/config.py.
"""

import threading
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from backend.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

# SQLite needs 'check_same_thread: False' for multi-threaded FastAPI / Streamlit workers.
connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    # Neon closes idle connections: test each pooled connection before using it
    pool_pre_ping=not settings.is_sqlite,
    echo=False,  # never True: logs could expose the database link
)

# Session factory for generating database sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class for all ORM models
Base = declarative_base()

_migrated = False
_migrate_lock = threading.Lock()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session per request
    and automatically closes it when the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def upgrade_database() -> None:
    """Runs the Alembic migrations up to the newest version (same as
    `python -m alembic upgrade head`)."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ALEMBIC_INI)), "head")


def init_db() -> None:
    """
    Makes sure all tables exist.
    - SQLite: create any missing tables directly (fast; used by tests and the cloud demo).
    - PostgreSQL: run the Alembic migrations once per process.
    """
    global _migrated
    # Import all models to ensure they are registered with Base.metadata
    from backend.database import models  # noqa: F401

    if settings.is_sqlite:
        Base.metadata.create_all(bind=engine)
        return
    if _migrated:
        return
    with _migrate_lock:
        if not _migrated:
            upgrade_database()
            _migrated = True
