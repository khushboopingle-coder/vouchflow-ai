"""
Phase 3 tests: fair AI limits.

- the default explanation is the template (llm_used=False) and nothing is counted
- with use_ai, a user gets at most 5 real AI explanations per day; the 6th is the template
- a Gemini failure falls back to the template silently and is NOT counted
- without a key, AI is never used
Gemini is never really called: _call_llm_for_explanation is replaced by a fake.
"""

import pytest

from backend.agent import graph
from backend.config import settings
from backend.database.db import SessionLocal
from backend.services import ai_usage_service, invoice_service
from tests.helpers import temp_user

FAKE_TEXT = "The invoice was compared with its purchase order, goods received note and contract."


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def fake_gemini(monkeypatch):
    calls = []

    def fake(prompt_text):
        calls.append(prompt_text)
        return FAKE_TEXT

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(graph, "_call_llm_for_explanation", fake)
    graph._EXPLANATION_CACHE.clear()
    return calls


def _investigate(db, user, use_ai):
    return invoice_service.investigate_invoice(db, invoice_id=user.ids[1], workspace_id=user.workspace_id,
                                               who="ai-limit-test", use_ai=use_ai, user_id=user.user_id)


def test_default_is_template_and_not_counted(db, fake_gemini):
    with temp_user() as user:
        report = _investigate(db, user, use_ai=False)
        assert report.llm_used is False
        assert fake_gemini == []
        assert ai_usage_service.used_today(db, user.user_id) == 0
        assert ai_usage_service.remaining_today(db, user.user_id) == ai_usage_service.DAILY_AI_LIMIT


def test_five_ai_explanations_then_template(db, fake_gemini):
    with temp_user() as user:
        for n in range(1, ai_usage_service.DAILY_AI_LIMIT + 1):
            graph._EXPLANATION_CACHE.clear()
            assert _investigate(db, user, use_ai=True).llm_used is True
            assert ai_usage_service.used_today(db, user.user_id) == n
        assert ai_usage_service.remaining_today(db, user.user_id) == 0

        graph._EXPLANATION_CACHE.clear()
        sixth = _investigate(db, user, use_ai=True)
        assert sixth.llm_used is False                       # limit reached -> template
        assert ai_usage_service.used_today(db, user.user_id) == ai_usage_service.DAILY_AI_LIMIT
        assert len(fake_gemini) == ai_usage_service.DAILY_AI_LIMIT


def test_gemini_failure_falls_back_silently(db, monkeypatch, fake_gemini):
    def broken(prompt_text):
        raise RuntimeError("quota exceeded")

    monkeypatch.setattr(graph, "_call_llm_for_explanation", broken)
    with temp_user() as user:
        report = _investigate(db, user, use_ai=True)
        assert report.llm_used is False and report.explanation  # template, no error for the user
        assert ai_usage_service.used_today(db, user.user_id) == 0


def test_no_key_means_no_ai(db, monkeypatch, fake_gemini):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with temp_user() as user:
        assert ai_usage_service.may_use_ai(db, user.user_id) is False
        assert _investigate(db, user, use_ai=True).llm_used is False
        assert fake_gemini == []


def test_limits_are_per_user(db, fake_gemini):
    with temp_user() as a, temp_user() as b:
        for _ in range(ai_usage_service.DAILY_AI_LIMIT):
            ai_usage_service.record_ai_use(db, a.user_id)
        assert ai_usage_service.remaining_today(db, a.user_id) == 0
        assert ai_usage_service.remaining_today(db, b.user_id) == ai_usage_service.DAILY_AI_LIMIT
