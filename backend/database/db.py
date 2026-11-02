"""
Database Connection & Session Management
Using SQLAlchemy 2.x.
Easily switch between SQLite and PostgreSQL by modifying DATABASE_URL in .env.
"""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from backend.config import settings

# Configure connection arguments based on database engine
# SQLite requires 'check_same_thread: False' for multi-threaded FastAPI workers.
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Create the SQLAlchemy engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False  # Set to True if you want to inspect raw SQL queries
)

# Session factory for generating database sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class for all ORM models
Base = declarative_base()


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


def init_db() -> None:
    """
    Initializes the database by creating all declared tables
    if they do not already exist.
    """
    # Import all models to ensure they are registered with Base.metadata
    from backend.database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
