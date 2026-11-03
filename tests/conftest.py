"""
Shared test setup.

Before every test:
  - the real Gemini API is switched OFF (tests must never use real quota)
  - the explanation cache and the 'dead model' list are cleared,
    so one test can never leak its result into another test

A test that patches backend.agent.graph._call_llm_for_explanation still works,
because that patch replaces the whole function.
"""

import pytest


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