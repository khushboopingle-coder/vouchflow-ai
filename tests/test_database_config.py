"""
Database configuration tests (SQLite + PostgreSQL support).

- DATABASE_URL links are converted for the psycopg (v3) driver; SQLite is the fallback
- the test run itself uses SQLite (tests/conftest.py), whatever .env says
- the Alembic migration builds every table on an empty database and matches the models
- (clearing a workspace in foreign-key order is tested in tests/test_workspaces.py)
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from backend.config import DEFAULT_SQLITE_URL, Settings, normalize_database_url, settings
from backend.database.db import Base
from backend.database import models  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("postgresql://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require",
         "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require"),
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///./vouchflow.db", "sqlite:///./vouchflow.db"),
        ('  "postgresql://u:p@host/db"  ', "postgresql+psycopg://u:p@host/db"),
        ("", DEFAULT_SQLITE_URL),
    ],
)
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected


def test_missing_database_url_falls_back_to_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.database_url == DEFAULT_SQLITE_URL
    assert fresh.is_sqlite and fresh.database_kind == "sqlite"


def test_postgres_kind_is_reported_without_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@host/db")
    fresh = Settings(_env_file=None)
    assert fresh.database_kind == "postgresql"
    assert not fresh.is_sqlite
    assert "secret" not in fresh.database_kind


def test_test_run_uses_sqlite():
    assert settings.is_sqlite, "tests must never run against the real PostgreSQL database"


def test_migration_builds_all_tables_and_matches_models(tmp_path):
    db_path = tmp_path / "migrated.db"
    # upgrade AND check in one subprocess (Python's slow start-up is paid once).
    # command.check fails if a model changed without a new migration.
    snippet = ("from alembic import command; from alembic.config import Config; "
               "cfg = Config('alembic.ini'); command.upgrade(cfg, 'head'); command.check(cfg); print('MIGRATION_OK')")
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db_path.as_posix()}")
    run = subprocess.run([sys.executable, "-c", snippet], cwd=str(BASE_DIR), env=env,
                         capture_output=True, text=True, timeout=180)
    assert run.returncode == 0 and "MIGRATION_OK" in run.stdout, run.stdout[-1500:] + run.stderr[-1500:]

    con = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        version = con.execute("select version_num from alembic_version").fetchone()[0]
    finally:
        con.close()
    assert {t.name for t in Base.metadata.sorted_tables} | {"alembic_version"} == tables
    assert version == "0004"
