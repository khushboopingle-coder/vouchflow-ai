"""
The demo story (README / n8n guide), end to end and offline:

    empty workspace -> import the 3 CSV templates from the "My data" page
    -> ingest data/samples/sample_invoice_clean.pdf           -> verified
    -> ingest data/samples/sample_invoice_price_mismatch.pdf  -> price mismatch

The reader (Gemini) is replaced by the exact values printed on the two PDFs, so this
proves the sample files, the templates and the checker agree with each other.
It also checks that the PDFs really contain those values (pdfplumber text).
"""

from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from backend.auth import rate_limit
from backend.database.db import SessionLocal
from backend.database.schemas import ExtractedInvoice, ExtractedItem
from backend.main import app
from backend.services import api_key_service, invoice_service, upload_service
from tests.helpers import temp_user

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"

EXPECTED = {
    "sample_invoice_clean.pdf": dict(number="INV-ACME-0001", chair_price=4500.0, subtotal=51000.0, gst=9180.0,
                                     total=60180.0),
    "sample_invoice_price_mismatch.pdf": dict(number="INV-ACME-0002", chair_price=4800.0, subtotal=54000.0,
                                              gst=9720.0, total=63720.0),
}


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.mark.parametrize("name", list(EXPECTED))
def test_pdf_contains_the_expected_numbers(name):
    with pdfplumber.open(SAMPLES / name) as pdf:
        text = pdf.pages[0].extract_text()
    e = EXPECTED[name]
    for needle in ("Acme Office Supplies", "PO-1001", e["number"], f"Rs. {e['chair_price']:,.2f}",
                   f"Rs. {e['total']:,.2f}"):
        assert needle in text, needle


def _reader_for(name):
    e = EXPECTED[name]

    def fake(path):
        assert Path(path).name.startswith("sample_invoice")  # the uploaded copy keeps its name
        return ExtractedInvoice(
            vendor="Acme Office Supplies", invoice_number=e["number"], invoice_date="2026-01-22",
            due_date="2026-02-21", po_reference="PO-1001", subtotal=e["subtotal"], gst_amount=e["gst"],
            grand_total=e["total"],
            items=[ExtractedItem(name="Ergonomic Office Chair", quantity=10, unit_price=e["chair_price"],
                                 total_price=10 * e["chair_price"]),
                   ExtractedItem(name="LED Desk Lamp", quantity=5, unit_price=1200.0, total_price=6000.0)],
            confidence=0.97, is_success=True, model_name="fake-reader",
        )
    return fake


def test_clean_verified_and_mismatch_flagged(db, monkeypatch):
    rate_limit.reset()
    with temp_user(load_sample=False) as user, TestClient(app) as client:
        ws, t = user.workspace_id, upload_service.TEMPLATES
        upload_service.import_purchase_orders(db, ws, t["purchase_orders.csv"].encode())
        upload_service.import_grns(db, ws, t["goods_received_notes.csv"].encode())
        upload_service.import_contract_prices(db, ws, t["contract_prices.csv"].encode())
        _, raw = api_key_service.create_api_key(db, ws, user.user_id, "sample test")
        headers = {"X-API-Key": raw}

        results = {}
        for name in EXPECTED:
            monkeypatch.setattr(invoice_service.reader, "read_invoice", _reader_for(name))
            data = (SAMPLES / name).read_bytes()
            r = client.post("/api/invoices/ingest", headers=headers, files={"file": (name, data, "application/pdf")})
            assert r.status_code == 200, r.text
            results[name] = r.json()

        clean = results["sample_invoice_clean.pdf"]
        assert clean["status"] == "verified" and clean["mistakes"] == []
        assert clean["recommended_action"] == "ready_for_human_approval"
        assert clean["supplier_name"] == "Acme Office Supplies" and clean["grand_total"] == 60180.0
        assert clean["human_approval_required"] is True and clean["text"].startswith("VERIFIED:")

        bad = results["sample_invoice_price_mismatch.pdf"]
        assert bad["status"] == "mismatch_detected"
        assert "price_mismatch" in bad["mistakes"]
        assert bad["difference_amount"] > 0
        assert bad["recommended_action"] != "ready_for_human_approval"
        assert "price mismatch" in bad["text"] and bad["text"].startswith("MISMATCH:")
