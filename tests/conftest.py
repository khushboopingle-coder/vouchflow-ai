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
