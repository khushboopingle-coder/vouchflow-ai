"""
Phase 4 tests: ingest API for automation (n8n) with workspace API keys.

PROVES:
- wrong, missing or revoked key -> 401; a login token does not work on /api and an API key
  does not work on the dashboard routes
- only the SHA-256 hash of a key is stored (the key itself never is)
- a key reaches ONLY its own workspace (another workspace's summary -> 404)
- ingest returns the expected JSON, fills the invoice, runs match + agent, and NEVER
  approves (no decision, human_approval_required is always true)
- bad files -> 400; the per-key rate limit -> 429
- the Settings page creates (shown once) and revokes keys
Gemini is never called: extraction is replaced by a fake reader.
"""

import hashlib

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.auth import rate_limit
from backend.config import settings
from backend.database.db import SessionLocal
from backend.database.models import APIKey, Invoice, InvoiceDecision, InvoiceInvestigation
from backend.database.schemas import ExtractedInvoice, ExtractedItem
from backend.main import app
from backend.services import api_key_service, invoice_service, upload_service
from pathlib import Path

from tests.helpers import temp_user

PDF = b"%PDF-1.4\n% ingest test invoice\n"
SETTINGS_PAGE = str(Path(__file__).resolve().parent.parent / "dashboard" / "views" / "settings.py")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture()
def fake_reader(monkeypatch):
    """Gemini replaced by a fixed, successful extraction."""
    def fake(path):
        return ExtractedInvoice(
            vendor="Acme Office Supplies", invoice_number="INV-API-001", invoice_date="2026-02-01",
            po_reference="PO-NOT-IN-WORKSPACE", subtotal=1000.0, gst_amount=180.0, grand_total=1180.0,
            items=[ExtractedItem(name="Desk Lamp", quantity=2, unit_price=500.0, total_price=1000.0)],
            confidence=0.95, is_success=True, model_name="fake-reader",
        )
    monkeypatch.setattr(invoice_service.reader, "read_invoice", fake)


def _key(db, user, name="n8n test"):
    record, raw = api_key_service.create_api_key(db, user.workspace_id, user.user_id, name, who=user.email)
    return record, raw, {"X-API-Key": raw}


# ---------------------------------------------------------------------
# Keys: storage, 401s, revoke
# ---------------------------------------------------------------------
def test_only_the_hash_is_stored(db):
    with temp_user(load_sample=False) as user:
        record, raw, _ = _key(db, user)
        assert raw.startswith("vf_") and len(raw) > 40
        row = db.query(APIKey).filter(APIKey.id == record.id).one()
        assert row.key_hash == hashlib.sha256(raw.encode()).hexdigest()
        assert raw not in (row.key_hash, row.key_prefix, row.name)
        assert row.key_prefix == raw[:10] and len(row.key_prefix) < len(raw)


@pytest.mark.parametrize("headers", [
    {}, {"X-API-Key": ""}, {"X-API-Key": "vf_not-a-real-key"}, {"X-API-Key": "garbage"},
], ids=["missing", "empty", "unknown", "wrong-shape"])
def test_bad_keys_get_401(client, headers):
    assert client.post("/api/invoices/ingest", headers=headers,
                       files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 401
    assert client.get("/api/invoices/1/summary", headers=headers).status_code == 401


def test_revoked_key_is_refused(client, db):
    with temp_user(load_sample=False) as user:
        record, raw, headers = _key(db, user)
        assert client.get("/api/invoices/1/summary", headers=headers).status_code == 404  # key works (no such invoice)
        assert api_key_service.revoke_api_key(db, user.workspace_id, record.id) is True
        assert client.get("/api/invoices/1/summary", headers=headers).status_code == 401
        assert api_key_service.revoke_api_key(db, user.workspace_id, record.id) is False  # already revoked


def test_cannot_revoke_another_workspaces_key(db):
    with temp_user(load_sample=False) as a, temp_user(load_sample=False) as b:
        record, _, _ = _key(db, b)
        assert api_key_service.revoke_api_key(db, a.workspace_id, record.id) is False
        db.expire_all()
        assert db.query(APIKey).filter(APIKey.id == record.id).one().revoked_at is None


def test_key_name_and_limit_rules(db):
    with temp_user(load_sample=False) as user:
        with pytest.raises(api_key_service.APIKeyError, match="name"):
            api_key_service.create_api_key(db, user.workspace_id, user.user_id, "   ")
        for i in range(api_key_service.MAX_ACTIVE_KEYS_PER_WORKSPACE):
            api_key_service.create_api_key(db, user.workspace_id, user.user_id, f"key {i}")
        with pytest.raises(api_key_service.APIKeyError, match="Revoke one"):
            api_key_service.create_api_key(db, user.workspace_id, user.user_id, "one too many")


def test_login_token_and_api_key_are_not_interchangeable(client, db):
    with temp_user(load_sample=False) as user:
        _, _, key_headers = _key(db, user)
        assert client.get("/api/invoices/1/summary", headers=user.headers).status_code == 401   # token on /api
        assert client.get("/invoices", headers=key_headers).status_code == 401                  # key on dashboard API


def test_deleting_the_workspace_removes_its_keys(db):
    from backend.services import workspace_service

    with temp_user(load_sample=False) as user:
        record, _, _ = _key(db, user)
        key_id = record.id
        workspace_service.delete_workspace(db, user.workspace_id)
        assert db.query(APIKey).filter(APIKey.id == key_id).count() == 0


# ---------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------
def test_ingest_returns_expected_json_and_never_approves(client, db, fake_reader):
    with temp_user(load_sample=False) as user:
        _, _, headers = _key(db, user)
        r = client.post("/api/invoices/ingest", headers=headers,
                        files={"file": ("supplier bill.pdf", PDF, "application/pdf")})
        assert r.status_code == 200, r.text
        body = r.json()

        # the documented answer
        for field in ("invoice_id", "status", "mistakes", "recommended_action", "dashboard_link", "text"):
            assert field in body
        assert body["status"] in ("verified", "mismatch_detected", "needs_review")
        assert body["status"] != "verified"                         # PO is not in the workspace
        assert "missing_po" in body["mistakes"]
        assert body["recommended_action"] in ("ask_supplier_for_clarification", "needs_human_review",
                                              "reject_and_escalate")
        assert body["extraction_ok"] is True and body["extraction_confidence"] == 0.95
        assert body["dashboard_link"].endswith(f"/investigation?invoice={body['invoice_id']}")
        assert body["invoice_number"] == "INV-API-001" and body["grand_total"] == 1180.0
        assert body["human_approval_required"] is True
        assert "approve" in body["message"].lower() and "link" not in body["text"].lower()
        assert body["dashboard_link"] in body["text"]

        # the invoice and its report are in the key's workspace; nothing was approved
        invoice = db.query(Invoice).filter(Invoice.id == body["invoice_id"]).one()
        assert invoice.workspace_id == user.workspace_id
        assert invoice.invoice_number == "INV-API-001" and len(invoice.items) == 1
        report = db.query(InvoiceInvestigation).filter(InvoiceInvestigation.invoice_id == invoice.id).one()
        assert '"llm_used":false' in report.report_json.replace(" ", "")      # template, no AI quota used
        assert db.query(InvoiceDecision).filter(InvoiceDecision.invoice_id == invoice.id).count() == 0


def test_ingest_without_a_reader_key_still_checks_and_flags_for_review(client, db, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with temp_user(load_sample=False) as user:
        _, _, headers = _key(db, user)
        body = client.post("/api/invoices/ingest", headers=headers,
                           files={"file": ("bill.pdf", PDF, "application/pdf")}).json()
        assert body["extraction_ok"] is False
        assert body["status"] == "needs_review" and body["human_approval_required"] is True


@pytest.mark.parametrize("name, data, message", [
    ("virus.exe", b"MZ..", "Invalid file type"),
    ("bill.pdf", b"not really a pdf", "real PDF"),
    ("bill.pdf", b"", "empty"),
])
def test_bad_files_get_400(client, db, name, data, message):
    with temp_user(load_sample=False) as user:
        _, _, headers = _key(db, user)
        r = client.post("/api/invoices/ingest", headers=headers, files={"file": (name, data, "application/pdf")})
        assert r.status_code == 400 and message in r.json()["detail"]
        assert db.query(Invoice).filter(Invoice.workspace_id == user.workspace_id).count() == 0


def test_rate_limit_per_key(client, db, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_RATE_LIMIT_PER_MINUTE", 2)
    with temp_user(load_sample=False) as a, temp_user(load_sample=False) as b:
        _, _, ha = _key(db, a)
        _, _, hb = _key(db, b)
        bad = {"file": ("x.exe", b"nope", "text/plain")}      # refused with 400, but still counted
        assert client.post("/api/invoices/ingest", headers=ha, files=bad).status_code == 400
        assert client.post("/api/invoices/ingest", headers=ha, files=bad).status_code == 400
        third = client.post("/api/invoices/ingest", headers=ha, files=bad)
        assert third.status_code == 429 and "Retry-After" in third.headers
        assert client.post("/api/invoices/ingest", headers=hb, files=bad).status_code == 400  # other key unaffected


# ---------------------------------------------------------------------
# Summary and isolation
# ---------------------------------------------------------------------
def test_summary_for_own_invoice_and_isolation(client, db, fake_reader):
    with temp_user(load_sample=False) as a, temp_user(load_sample=False) as b:
        _, _, ha = _key(db, a)
        _, _, hb = _key(db, b)
        invoice_id = client.post("/api/invoices/ingest", headers=ha,
                                 files={"file": ("a.pdf", PDF, "application/pdf")}).json()["invoice_id"]

        mine = client.get(f"/api/invoices/{invoice_id}/summary", headers=ha)
        assert mine.status_code == 200
        summary = mine.json()
        assert summary["invoice_id"] == invoice_id and summary["human_approval_required"] is True
        assert "Recommended:" in summary["text"] and summary["dashboard_link"] in summary["text"]

        # B's key can neither read it ...
        assert client.get(f"/api/invoices/{invoice_id}/summary", headers=hb).status_code == 404
        # ... nor does it show up for B anywhere
        assert db.query(Invoice).filter(Invoice.workspace_id == b.workspace_id).count() == 0


def test_summary_text_wording():
    from backend.services.ingest_service import build_summary_text

    good = build_summary_text("INV-1", "Acme", 1180.0, "verified", [], 0.0, "ready_for_human_approval", "http://x/y")
    assert good.startswith("VERIFIED: Invoice INV-1 from Acme - Rs. 1,180.00") and "http://x/y" in good
    bad = build_summary_text("INV-2", None, 500.0, "mismatch_detected", ["price_mismatch"], 90.0,
                             "ask_supplier_for_clarification", "http://x/y")
    assert "MISMATCH" in bad and "price mismatch (difference Rs. 90.00)" in bad
    assert "Ask the supplier for clarification" in bad and "A person must approve it" in bad


# ---------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------
def test_settings_page_creates_shows_once_and_revokes(db):
    with temp_user(load_sample=False) as user:
        at = AppTest.from_file(SETTINGS_PAGE, default_timeout=120)
        at.session_state["auth"] = user.session_auth
        at.run()
        assert not at.exception

        at.text_input(key="api_key_name").set_value("n8n Gmail")
        at.button[0].click().run()                                  # "Create key"
        assert not at.exception
        shown = [c.value for c in at.code if c.value.startswith("vf_")]
        assert len(shown) == 1                                      # the key is displayed ...
        raw = shown[0]
        assert db.query(APIKey).filter(APIKey.workspace_id == user.workspace_id).one().key_hash == \
            hashlib.sha256(raw.encode()).hexdigest()

        at.run()                                                    # ... exactly once
        assert not [c.value for c in at.code if c.value.startswith("vf_")]

        revoke = next(b for b in at.button if b.label == "Revoke")
        revoke.click().run()
        assert api_key_service.authenticate_api_key(db, raw) is None


def test_settings_page_needs_login():
    at = AppTest.from_file(SETTINGS_PAGE, default_timeout=120)
    at.run()
    assert not at.exception and len(at.title) == 0
