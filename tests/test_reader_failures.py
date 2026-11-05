"""
When the AI reader fails, the invoice must NOT be lost and the reason must NOT be hidden.

PROVES (Gemini is always fake):
- read_saved_invoice never raises: a failed read gives ok=False + a readable reason, and logs it
- a successful read fills the invoice row and returns ok=True
- the reader reports its REAL last error (e.g. 503), not always "daily limit"
- the ingest API shows `extraction_error` when reading failed
- the dashboard upload helper saves first, then reads, and keeps the invoice when reading fails
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.database.db import SessionLocal
from backend.database.models import Invoice
from backend.database.schemas import ExtractedInvoice, ExtractedItem
from backend.services import ingest_service, invoice_service, upload_service
from backend.tools.invoice_reader import InvoiceReader, ModelStateTracker
from tests.helpers import temp_user

PDF = b"%PDF-1.4\n% reader failure test\n"


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


def _save(db, user, name="bill.pdf"):
    return upload_service.save_invoice_file(db, user.workspace_id, name, PDF, who="test").invoice_id


def test_failed_read_returns_reason_logs_it_and_keeps_the_invoice(db, monkeypatch, caplog):
    monkeypatch.setattr(invoice_service.reader, "read_invoice", lambda p: ExtractedInvoice(
        is_success=False, error_message="503 UNAVAILABLE: high demand", confidence=0.0))
    with temp_user(load_sample=False) as user:
        invoice_id = _save(db, user)
        with caplog.at_level(logging.WARNING, logger="vouchflow.reader"):
            outcome = ingest_service.read_saved_invoice(db, user.workspace_id, invoice_id)
        assert outcome.ok is False and "503" in outcome.reason
        assert any("503" in r.getMessage() for r in caplog.records)           # logged for the terminal
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).one()
        assert invoice.status == "needs_review" and invoice.grand_total == 0   # kept, untouched


def test_read_that_crashes_is_caught(db, monkeypatch):
    def boom(path):
        raise RuntimeError("network down")

    monkeypatch.setattr(invoice_service.reader, "read_invoice", boom)
    with temp_user(load_sample=False) as user:
        invoice_id = _save(db, user)
        outcome = ingest_service.read_saved_invoice(db, user.workspace_id, invoice_id)
        assert outcome.ok is False and "network down" in outcome.reason


def test_unknown_invoice_is_a_failed_read_not_a_crash(db):
    with temp_user(load_sample=False) as user:
        outcome = ingest_service.read_saved_invoice(db, user.workspace_id, 99999999)
        assert outcome.ok is False and outcome.reason


def test_successful_read_fills_the_invoice(db, monkeypatch):
    monkeypatch.setattr(invoice_service.reader, "read_invoice", lambda p: ExtractedInvoice(
        vendor="Sharma Office Supplies", invoice_number="INV-READ-1", invoice_date="2026-02-01",
        subtotal=1000.0, gst_amount=180.0, grand_total=1180.0,
        items=[ExtractedItem(name="Pen", quantity=2, unit_price=500.0, total_price=1000.0)],
        confidence=0.9, is_success=True, model_name="fake"))
    with temp_user(load_sample=False) as user:
        invoice_id = _save(db, user)
        outcome = ingest_service.read_saved_invoice(db, user.workspace_id, invoice_id)
        assert outcome.ok is True and outcome.reason == ""
        db.expire_all()
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).one()
        assert invoice.invoice_number == "INV-READ-1" and invoice.grand_total == 1180.0


def test_reader_reports_the_real_last_error_not_always_daily_limit(tmp_path):
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("400 INVALID_ARGUMENT: bad request")
    reader = InvoiceReader(models=["m1", "m2"], client=client, retry_delays=(),
                           state_tracker=ModelStateTracker(state_file=tmp_path / "state.json"))
    sample = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_invoice_clean.pdf"
    result = reader.read_invoice(str(sample), rate_limit_delay=0)
    assert result.is_success is False
    assert "INVALID_ARGUMENT" in result.error_message
    assert "daily limit" not in result.error_message


def test_ingest_api_shows_why_reading_failed(db, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services import api_key_service

    monkeypatch.setattr(invoice_service.reader, "read_invoice", lambda p: ExtractedInvoice(
        is_success=False, error_message="model overloaded", confidence=0.0))
    with temp_user(load_sample=False) as user, TestClient(app) as client:
        _, raw = api_key_service.create_api_key(db, user.workspace_id, user.user_id, "t", who=user.email)
        body = client.post("/api/invoices/ingest", headers={"X-API-Key": raw},
                           files={"file": ("a.pdf", PDF, "application/pdf")}).json()
        assert body["extraction_ok"] is False and body["extraction_error"] == "model overloaded"
        assert body["human_approval_required"] is True


def test_dashboard_upload_helper_saves_then_reads_and_survives_failure(db, monkeypatch):
    """Runs the same two steps the Home page runs (save, then read) with a failing reader."""
    monkeypatch.setattr(invoice_service.reader, "read_invoice", lambda p: ExtractedInvoice(
        is_success=False, error_message="no key", confidence=0.0))
    with temp_user(load_sample=False) as user:
        before = db.query(Invoice).filter(Invoice.workspace_id == user.workspace_id).count()
        invoice_id = _save(db, user)
        outcome = ingest_service.read_saved_invoice(db, user.workspace_id, invoice_id)
        after = db.query(Invoice).filter(Invoice.workspace_id == user.workspace_id).count()
        assert after == before + 1 and outcome.ok is False and outcome.reason == "no key"
