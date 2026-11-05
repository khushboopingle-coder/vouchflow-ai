"""
Shared test setup.

SAFETY RULES for the whole test suite
-------------------------------------
1. Database: tests ALWAYS use the local SQLite file, even when .env points DATABASE_URL at
   the Neon PostgreSQL database (an environment variable beats the .env file, and this runs
   before any backend module is imported). To test against another database on purpose,
   set TEST_DATABASE_URL.
2. Gemini: tests NEVER call the real Gemini API. The real key from .env is blanked here
   (before anything is imported), and any attempt to create a real Gemini client raises an
   error that says so. Tests that need a reader use a fake (see tests/test_reader.py,
   tests/test_ingest_api.py) or patch backend.agent.graph._call_llm_for_explanation.
3. Speed: no waiting on retries; per-workspace contract indexes use a tiny fake embedding
   instead of the ONNX model (the shared sample index keeps the real one, so the contract
   search evaluation tests still test the real thing). The whole suite should finish in
   under 2 minutes; pytest.ini sets a timeout per test so a hang is reported, not endless.

Before every test the explanation cache and the 'dead model' list are cleared, so one test
can never leak its result into another test.
"""

import os

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or "sqlite:///./vouchflow.db"
os.environ["GEMINI_API_KEY"] = ""          # never the real key in tests
os.environ["VOUCHFLOW_DISABLE_LLM"] = "1"  # the agent writes the template explanation

import pytest  # noqa: E402


# ---------------------------------------------------------------------------
# Fast fake embedding (per-workspace contract indexes only)
# ---------------------------------------------------------------------------
# Patched ONCE, here, at import time: module-scoped fixtures run BEFORE function-scoped ones,
# so a per-test patch would come too late for them (they would load the slow ONNX model).
from tests.fake_embeddings import FakeEmbeddings  # noqa: E402
from backend.tools import contract_finder  # noqa: E402

contract_finder._workspace_embedding = lambda: FakeEmbeddings()

# bcrypt is deliberately slow (12 rounds ~ 0.25 s per password); every test user would pay that.
# Tests use the minimum (4 rounds) - production keeps 12. The hash format and checks are identical.
from backend.auth import passwords as _passwords  # noqa: E402

_passwords.BCRYPT_ROUNDS = 4


@pytest.fixture(autouse=True)
def _fresh_workspace_indexes():
    """Every test starts and ends without cached per-workspace indexes (ids are reused between tests)."""
    contract_finder._WS_STORES.clear()
    yield
    contract_finder._WS_STORES.clear()


# ---------------------------------------------------------------------------
# Gemini: never real, never slow
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_real_gemini(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(
            "A test tried to create a REAL Gemini client. Tests must never call Gemini: "
            "pass a fake client/reader instead (see tests/conftest.py)."
        )

    try:
        from google import genai

        monkeypatch.setattr(genai, "Client", refuse)
    except Exception:
        pass

    from backend.tools import invoice_reader

    r = invoice_reader.reader
    saved = (r.client, r.retry_delays, list(r.models), r.current_model_idx)
    r.client = None                   # no key -> extraction reports "client not initialised", instantly
    r.retry_delays = (0.0, 0.0)       # never sleep between retries
    yield
    r.client, r.retry_delays, r.models, r.current_model_idx = saved[0], saved[1], saved[2], saved[3]


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


# ---------------------------------------------------------------------------
# Housekeeping: a run that was cut off (Ctrl+C, timeout, crash) cannot run its cleanup code and
# leaves throw-away "pytest-...@example.com" accounts (each with a copy of the sample data) behind.
# They pile up and slow every later run, so each run starts by removing the stale ones.
# Only ever touches accounts with that exact test e-mail pattern, and only in a SQLite file.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _remove_stale_test_accounts():
    from backend.config import settings

    if not settings.is_sqlite:
        yield
        return
    from backend.database.db import SessionLocal, init_db
    from backend.database.models import User
    from backend.services import workspace_service

    init_db()
    db = SessionLocal()
    try:
        for user in db.query(User).filter(User.email.like("pytest-%@example.com")).all():
            ws = workspace_service.get_user_workspace(db, user.id)
            if ws is not None:
                workspace_service.delete_workspace(db, ws.id)
            else:
                db.delete(user)
                db.commit()
    finally:
        db.close()
    yield
