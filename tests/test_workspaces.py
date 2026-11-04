"""
Phase 2 tests: login and private workspaces.

PROVES:
- passwords are stored only as bcrypt hashes; a wrong password fails
- user A cannot read, change, check, investigate or approve user B's data,
  through the service layer (what the dashboard uses) AND through the API
- an edited token, or a token for a workspace the user does not own, is refused (401)
- the dashboard only shows the logged-in user's own workspace
- copied sample invoices are not flagged as duplicates of the sample workspace
- clearing / deleting a workspace works with foreign keys enforced (as on PostgreSQL)

All users and workspaces created here are deleted afterwards (tests/helpers.py).
"""

import base64
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.auth.passwords import verify_password
from backend.auth.tokens import create_token
from backend.database.db import Base, SessionLocal
from backend.database.models import (
    AuditLog, Contract, GoodsReceivedNote, GRNItem, Invoice, InvoiceCheck, InvoiceDecision,
    InvoiceExtraction, InvoiceInvestigation, InvoiceItem, POItem, PurchaseOrder, Supplier, User, Workspace,
)
from backend.database.schemas import DecisionCreate
from backend.main import app
from backend.services import approval_service, auth_service, invoice_service, workspace_service
from backend.tools.matcher import perform_three_way_match
from tests.helpers import TEST_PASSWORD, temp_user

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def user_a():
    with temp_user() as u:
        yield u


@pytest.fixture(scope="module")
def user_b():
    with temp_user() as u:
        yield u


@pytest.fixture(scope="module")
def b_investigated(db, user_b):
    """User B has a fresh investigation on their invoice 1 (so there is something to approve)."""
    invoice_service.investigate_invoice(db, invoice_id=user_b.ids[1], workspace_id=user_b.workspace_id, who="b")
    return user_b.ids[1]


# ---------------------------------------------------------------------
# Accounts and passwords
# ---------------------------------------------------------------------
def test_password_is_stored_only_as_bcrypt_hash(db, user_a):
    row = db.query(User).filter(User.id == user_a.user_id).one()
    assert row.password_hash != TEST_PASSWORD
    assert TEST_PASSWORD not in row.password_hash
    assert row.password_hash.startswith("$2")  # bcrypt
    assert verify_password(TEST_PASSWORD, row.password_hash)


def test_login_right_wrong_and_unknown(db, user_a):
    assert auth_service.login(db, user_a.email, TEST_PASSWORD).workspace_id == user_a.workspace_id
    assert auth_service.login(db, user_a.email.upper(), TEST_PASSWORD) is not None  # email case
    assert auth_service.login(db, user_a.email, "wrong-password-123") is None
    assert auth_service.login(db, "nobody-here@example.com", TEST_PASSWORD) is None


@pytest.mark.parametrize("email, password, message", [
    ("not-an-email", "long-enough-pw", "valid email"),
    ("short@example.com", "short", "at least 8"),
])
def test_signup_validation(db, email, password, message):
    with pytest.raises(auth_service.AuthError, match=message):
        auth_service.signup(db, email, password)


def test_duplicate_email_refused(db, user_a):
    with pytest.raises(auth_service.AuthError, match="already exists"):
        auth_service.signup(db, user_a.email.upper(), "another-password")


def test_signup_gets_own_workspace_with_sample_copy(db, user_a, sample_ws_id):
    ws = workspace_service.get_user_workspace(db, user_a.user_id)
    assert ws.id == user_a.workspace_id and not ws.is_sample and ws.id != sample_ws_id
    assert workspace_service.workspace_invoice_count(db, ws.id) == \
        workspace_service.workspace_invoice_count(db, sample_ws_id)


def test_api_login(client, user_a):
    bad = client.post("/auth/login", json={"email": user_a.email, "password": "wrong-password-123"})
    assert bad.status_code == 401
    good = client.post("/auth/login", json={"email": user_a.email, "password": TEST_PASSWORD})
    assert good.status_code == 200
    token = good.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["workspace_id"] == user_a.workspace_id and me["email"] == user_a.email


# ---------------------------------------------------------------------
# Isolation through the service layer (what the dashboard calls)
# ---------------------------------------------------------------------
def test_lists_never_mix_workspaces(db, user_a, user_b):
    a_ids = {i.id for i in invoice_service.list_invoices(db, workspace_id=user_a.workspace_id, limit=500)}
    b_ids = {i.id for i in invoice_service.list_invoices(db, workspace_id=user_b.workspace_id, limit=500)}
    assert a_ids == set(user_a.ids.values())
    assert a_ids.isdisjoint(b_ids)


@pytest.mark.parametrize("call", [
    lambda db, inv, ws: invoice_service.get_invoice_by_id(db, invoice_id=inv, workspace_id=ws),
    lambda db, inv, ws: invoice_service.get_invoice_extraction(db, invoice_id=inv, workspace_id=ws),
    lambda db, inv, ws: invoice_service.check_invoice_matching(db, invoice_id=inv, workspace_id=ws),
    lambda db, inv, ws: invoice_service.get_invoice_check(db, invoice_id=inv, workspace_id=ws),
    lambda db, inv, ws: invoice_service.investigate_invoice(db, invoice_id=inv, workspace_id=ws),
    lambda db, inv, ws: invoice_service.get_invoice_investigation(db, invoice_id=inv, workspace_id=ws),
    lambda db, inv, ws: approval_service.record_decision(
        db, invoice_id=inv, workspace_id=ws,
        payload=DecisionCreate(decision="approved", decided_by="Mallory Smith", note="taking over")),
], ids=["read", "extraction", "check", "saved-check", "investigate", "report", "approve"])
def test_service_refuses_other_workspace(db, user_a, user_b, b_investigated, call):
    with pytest.raises(HTTPException) as err:
        call(db, b_investigated, user_a.workspace_id)  # A uses B's invoice id
    assert err.value.status_code == 404


def test_b_invoice_untouched_by_a(db, user_b, b_investigated):
    db.expire_all()
    assert db.query(InvoiceDecision).filter(InvoiceDecision.invoice_id == b_investigated).count() == 0
    assert db.query(Invoice).filter(Invoice.id == b_investigated).one().workspace_id == user_b.workspace_id


def test_queues_and_history_are_private(db, user_a, user_b, b_investigated):
    a_queue = {q.invoice_id for q in approval_service.get_approval_queue(db, workspace_id=user_a.workspace_id)}
    assert b_investigated not in a_queue
    assert a_queue <= set(user_a.ids.values())
    a_history = approval_service.list_decisions(db, workspace_id=user_a.workspace_id, limit=200)
    assert all(h.invoice_id in user_a.ids.values() for h in a_history)


# ---------------------------------------------------------------------
# Isolation through the API
# ---------------------------------------------------------------------
@pytest.mark.parametrize("method, path, body", [
    ("get", "/invoices/{id}", None),
    ("get", "/invoices/{id}/extraction", None),
    ("post", "/invoices/{id}/check", None),
    ("get", "/invoices/{id}/check", None),
    ("post", "/invoices/{id}/investigate", None),
    ("get", "/invoices/{id}/investigation", None),
    ("post", "/invoices/{id}/decision", {"decision": "approved", "decided_by": "Mallory Smith", "note": "mine now"}),
])
def test_api_refuses_other_workspace(client, user_a, b_investigated, method, path, body):
    url = path.format(id=b_investigated)
    kwargs = {"headers": user_a.headers}
    if body is not None:
        kwargs["json"] = body
    response = getattr(client, method)(url, **kwargs)
    assert response.status_code == 404, (url, response.status_code)


def test_api_lists_only_own_workspace(client, user_a, user_b):
    ids = {i["id"] for i in client.get("/invoices", params={"limit": 500}, headers=user_a.headers).json()}
    assert ids == set(user_a.ids.values()) and ids.isdisjoint(set(user_b.ids.values()))
    logs = client.get("/audit-logs", params={"limit": 200}, headers=user_a.headers).json()
    assert logs and all(log["who"] != user_b.email for log in logs)


def test_edited_token_is_refused(client, user_a, user_b):
    body, signature = user_a.headers["Authorization"].split(" ", 1)[1].split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["ws"] = user_b.workspace_id  # try to point A's token at B's workspace
    forged_body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    r = client.get("/invoices", headers={"Authorization": f"Bearer {forged_body}.{signature}"})
    assert r.status_code == 401


def test_signed_token_for_someone_elses_workspace_is_refused(client, user_a, user_b):
    token = create_token(user_a.user_id, user_b.workspace_id)  # validly signed, wrong owner
    assert client.get("/invoices", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# ---------------------------------------------------------------------
# Dashboard shows only the logged-in workspace
# ---------------------------------------------------------------------
def test_dashboard_shows_only_own_workspace(user_a):
    from streamlit.testing.v1 import AppTest

    with temp_user(load_sample=False) as empty:
        at = AppTest.from_file(APP, default_timeout=180)
        at.session_state["auth"] = empty.session_auth
        at.run()
        assert not at.exception
        assert any("ledger is empty" in i.value for i in at.info)  # A's 120 invoices are invisible

        at2 = AppTest.from_file(APP, default_timeout=180)
        at2.session_state["auth"] = user_a.session_auth
        at2.run()
        records = [m.value for m in at2.main.markdown if 'class="records"' in m.value]
        assert records and f"<b>{len(user_a.ids)}</b> records" in records[0]


# ---------------------------------------------------------------------
# Matcher and agent stay inside the workspace
# ---------------------------------------------------------------------
def test_copied_invoice_is_not_a_duplicate_of_the_sample(db, user_a):
    result = perform_three_way_match(user_a.ids[1], db)  # sample invoice 1 is clean
    assert result.status == "verified" and "duplicate_invoice" not in result.mistake_types


def test_agent_audit_rows_belong_to_the_workspace(db, user_b, b_investigated):
    rows = (db.query(AuditLog).filter(AuditLog.action.like("agent_%"), AuditLog.who == "b").all())
    assert rows and all(r.workspace_id == user_b.workspace_id for r in rows)


# ---------------------------------------------------------------------
# Clearing / deleting with foreign keys ENFORCED (PostgreSQL behaves like this)
# ---------------------------------------------------------------------
def test_clear_and_delete_workspace_respect_foreign_keys(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'fk.db').as_posix()}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    sample = workspace_service.ensure_sample_workspace(s)
    sup = Supplier(name="S", workspace_id=sample); s.add(sup); s.flush()
    s.add(Contract(supplier_id=sup.id, item_name="Desk", agreed_unit_price=10, workspace_id=sample))
    po = PurchaseOrder(po_number="PO-1", supplier_id=sup.id, order_date=date.today(), workspace_id=sample)
    s.add(po); s.flush(); s.add(POItem(po_id=po.id, item_name="Desk", quantity=1, unit_price=10, total_price=10))
    grn = GoodsReceivedNote(grn_number="GRN-1", po_id=po.id, received_date=date.today(), workspace_id=sample)
    s.add(grn); s.flush(); s.add(GRNItem(grn_id=grn.id, item_name="Desk", quantity_received=1))
    inv = Invoice(invoice_number="INV-1", supplier_id=sup.id, po_id=po.id, workspace_id=sample)
    s.add(inv); s.flush()
    s.add(InvoiceItem(invoice_id=inv.id, item_name="Desk", quantity=1, unit_price=10, total_price=10))
    s.add(InvoiceExtraction(invoice_id=inv.id, extracted_json="{}", confidence=1, model_name="m"))
    s.add(InvoiceCheck(invoice_id=inv.id, status="verified", mistake_types="[]", findings_json="[]"))
    report = InvoiceInvestigation(invoice_id=inv.id, status="verified", recommended_next_action="ready_for_human_approval",
                                  confidence=1, report_json=json.dumps({"invoice_id": inv.id}))
    s.add(report); s.commit()

    owner = User(email="fk@example.com", password_hash="x", created_at=datetime.utcnow()); s.add(owner); s.flush()
    ws = Workspace(name="fk", owner_user_id=owner.id, is_sample=False); s.add(ws); s.commit()
    owner_id, ws_id = owner.id, ws.id  # keep the ids: the rows get deleted below
    maps = workspace_service.load_sample_data(s, ws.id)
    copied = maps["invoices"][inv.id]
    copied_report = s.query(InvoiceInvestigation).filter(InvoiceInvestigation.invoice_id == copied).one()
    assert json.loads(copied_report.report_json)["invoice_id"] == copied  # report points at the copy
    s.add(InvoiceDecision(invoice_id=copied, investigation_id=copied_report.id, decision="approved",
                          decided_by="Asha", agent_recommendation="x", workspace_id=ws.id))
    s.commit()

    workspace_service.load_sample_data(s, ws_id)          # reload = clear + copy, FK-safe
    workspace_service.delete_workspace(s, ws_id)          # everything of ws, then the owner
    assert s.query(Invoice).filter(Invoice.workspace_id == ws_id).count() == 0
    assert s.query(User).filter(User.id == owner_id).count() == 0
    assert s.query(Invoice).filter(Invoice.workspace_id == sample).count() == 1  # sample untouched
    with pytest.raises(ValueError):
        workspace_service.delete_workspace(s, sample)
    s.close()
