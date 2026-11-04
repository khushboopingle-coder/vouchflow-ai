"""
Phase 8 tests: human approvals + dashboard pages.

Checks:
- software names (agent, system, n8n...) can never approve or reject
- an invoice must be investigated before a decision
- rejecting needs a note; approving against the agent's advice needs a note
- one decision per investigation report
- decisions are audit-logged and leave invoices.status unchanged
- the queue and history endpoints work
- the three new dashboard pages load without errors

Every row this file creates (investigations + decisions) is deleted afterwards.
Gemini is switched off by tests/conftest.py.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.database.db import SessionLocal, init_db
from backend.database.models import AuditLog, Invoice, InvoiceDecision, InvoiceInvestigation
from backend.main import app
from backend.services.invoice_service import investigate_invoice

TESTER = "Test Approver Asha"
DASHBOARD_PAGES = Path(__file__).resolve().parent.parent / "dashboard" / "pages"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def db():
    init_db()
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def investigated(db):
    """Fresh investigations for a clean invoice (1) and a mismatch invoice (56)."""
    before = {row[0] for row in db.query(InvoiceInvestigation.id).all()}
    clean = investigate_invoice(db, invoice_id=1, who="approval_tester")
    mismatch = investigate_invoice(db, invoice_id=56, who="approval_tester")
    yield {"clean": clean, "mismatch": mismatch}

    # Clean up everything this module created
    created = [
        row[0] for row in db.query(InvoiceInvestigation.id).all() if row[0] not in before
    ]
    db.query(InvoiceDecision).filter(InvoiceDecision.investigation_id.in_(created)).delete(
        synchronize_session=False
    )
    db.query(InvoiceInvestigation).filter(InvoiceInvestigation.id.in_(created)).delete(
        synchronize_session=False
    )
    db.commit()


def _decide(client, invoice_id, decision, decided_by=TESTER, note=None):
    return client.post(
        f"/invoices/{invoice_id}/decision",
        json={"decision": decision, "decided_by": decided_by, "note": note},
    )


# ---------------------------------------------------------------------
# Humans only
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "name", ["investigation_agent", "Agent", "system", "n8n workflow", "api_user", "ApprovalBot", "LLM"]
)
def test_software_names_are_blocked(client, investigated, name):
    response = _decide(client, 1, "approved", decided_by=name, note="looks fine to me")
    assert response.status_code == 403
    assert "software account" in response.json()["detail"]


def test_blocked_attempt_is_audit_logged(client, db, investigated):
    _decide(client, 1, "approved", decided_by="investigation_agent")
    db.expire_all()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "decision_blocked_non_human", AuditLog.who == "investigation_agent")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None


def test_empty_name_rejected(client, investigated):
    assert _decide(client, 1, "approved", decided_by="  ").status_code == 422


def test_invalid_decision_value_rejected(client, investigated):
    assert _decide(client, 1, "paid").status_code == 422


# ---------------------------------------------------------------------
# Investigation required
# ---------------------------------------------------------------------
def test_unknown_invoice_404(client):
    assert _decide(client, 999999, "approved").status_code == 404


def test_uninvestigated_invoice_409(client, db):
    investigated_ids = {row[0] for row in db.query(InvoiceInvestigation.invoice_id).distinct().all()}
    candidate = db.query(Invoice).filter(~Invoice.id.in_(investigated_ids)).first()
    if candidate is None:
        pytest.skip("Every invoice has been investigated; nothing to test.")
    response = _decide(client, candidate.id, "approved")
    assert response.status_code == 409
    assert "not been investigated" in response.json()["detail"]


# ---------------------------------------------------------------------
# Notes, queue, decision, audit, history
# ---------------------------------------------------------------------
def test_reject_needs_note(client, investigated):
    response = _decide(client, 1, "rejected", note="")
    assert response.status_code == 422
    assert "reason" in response.json()["detail"]


def test_clean_invoice_in_queue(client, investigated):
    response = client.get("/approvals/queue")
    assert response.status_code == 200
    item = next(q for q in response.json() if q["invoice_id"] == 1)
    assert item["recommended_next_action"] == investigated["clean"].recommended_next_action


def test_approve_clean_invoice_full_flow(client, db, investigated):
    assert investigated["clean"].recommended_next_action == "ready_for_human_approval"
    status_before = db.query(Invoice).filter(Invoice.id == 1).first().status

    response = _decide(client, 1, "approved", decided_by=f"  {TESTER}  ")
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "approved"
    assert body["decided_by"] == TESTER  # spaces trimmed
    assert body["agent_recommendation"] == "ready_for_human_approval"

    # audit log written
    db.expire_all()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "human_decision_approved", AuditLog.who == TESTER)
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None and '"invoice_id": 1' in log.details

    # invoice status unchanged
    assert db.query(Invoice).filter(Invoice.id == 1).first().status == status_before

    # gone from the queue, present in history
    assert all(q["invoice_id"] != 1 for q in client.get("/approvals/queue").json())
    history = client.get("/approvals/decisions", params={"limit": 200}).json()
    assert any(h["id"] == body["id"] and h["invoice_number"] for h in history)

    # cannot decide the same report twice
    again = _decide(client, 1, "rejected", note="changed my mind")
    assert again.status_code == 409


def test_override_agent_needs_note(client, investigated):
    action = investigated["mismatch"].recommended_next_action
    if action == "ready_for_human_approval":
        pytest.skip("Invoice 56 was not flagged; override rule not testable here.")

    no_note = _decide(client, 56, "approved")
    assert no_note.status_code == 422
    assert action in no_note.json()["detail"]

    with_note = _decide(client, 56, "approved", note="Supplier credit note received by email")
    assert with_note.status_code == 200
    assert with_note.json()["agent_recommendation"] == action


# ---------------------------------------------------------------------
# Dashboard pages load
# ---------------------------------------------------------------------
@pytest.mark.parametrize("page", ["1_Investigation.py", "2_Approvals.py", "3_Evals.py"])
def test_dashboard_page_loads(page):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(DASHBOARD_PAGES / page), default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.title) == 1
