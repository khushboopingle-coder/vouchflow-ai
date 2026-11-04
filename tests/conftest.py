"""
Shared test setup.

Database: tests ALWAYS use the local SQLite file, even when .env points DATABASE_URL at
the Neon PostgreSQL database. This runs before any backend module is imported, and an
environment variable beats the .env file. To test against another database on purpose,
set TEST_DATABASE_URL.

Before every test:
  - the real Gemini API is switched OFF (tests must never use real quota)
  - the explanation cache and the 'dead model' list are cleared,
    so one test can never leak its result into another test

A test that patches backend.agent.graph._call_llm_for_explanation still works,
because that patch replaces the whole function.
"""

import os

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or "sqlite:///./vouchflow.db"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_agent_llm(monkeypatch):
    monkeypatch.setenv("VOUCHFLOW_DISABLE_LLM", "1")
    try:
        from backend.agent import graph
        graph._EXPLANATION_CACHE.clear()
        graph._DEAD_MODELS.clear()
    except Exception:
        pass
    yield
    try:
        from backend.agent import graph
        graph._EXPLANATION_CACHE.clear()
        graph._DEAD_MODELS.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Phase 2: workspaces
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sample_ws_id():
    """Id of the shared "sample" workspace (holds the seeded invoices 1-120)."""
    from backend.database.db import SessionLocal, init_db
    from backend.services.workspace_service import ensure_sample_workspace

    init_db()
    db = SessionLocal()
    try:
        return ensure_sample_workspace(db)
    finally:
        db.close()


@pytest.fixture(scope="session")
def api_user():
    """A throw-away user with its OWN copy of the sample data and a login token
    (see tests/helpers.py). .ids maps sample invoice ids -> this user's ids (e.g. .ids[1]).
    Deleted after the test run."""
    from tests.helpers import temp_user

    with temp_user() as user:
        yield user
