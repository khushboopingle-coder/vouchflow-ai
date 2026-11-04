"""
Alembic environment for VouchFlow AI.

The database link comes from DATABASE_URL in .env (backend/config.py), never from
alembic.ini, so it is never written to a file in the repository.
Works for SQLite (local / tests) and PostgreSQL (Neon).
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings  # noqa: E402
from backend.database.db import Base, engine  # noqa: E402
from backend.database import models  # noqa: E402,F401  (registers every table on Base)

config = context.config

# Logging from alembic.ini; keep the app's own loggers working when the app runs this.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Write the SQL to the screen instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=settings.is_sqlite,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations against the real database."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most columns; "batch" mode rebuilds the table instead
            render_as_batch=settings.is_sqlite,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
