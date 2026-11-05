"""
The demo story (README / n8n guide), end to end and offline. Two families of sample invoices:

A. Match the SAMPLE DATA (a workspace with "sample data"): they reuse the real sample order
   Patel Enterprises / PO-2026-0002, so the PO, goods received note and contract prices exist.
       sample_invoice_clean.pdf           -> verified
       sample_invoice_price_mismatch.pdf  -> price_mismatch (and NOT missing_po)
B. Match the CSV TEMPLATES of the "My data" page (an empty workspace + the 3 templates):
       template_invoice_clean.pdf / template_invoice_price_mismatch.pdf

The reader (Gemini) is replaced by the exact values the generator printed on each PDF, so this
proves the sample files, the sample data/templates and the checker agree with each other.
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
from scripts import make_sample_invoices as gen
from tests.helpers import temp_user

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


def _expected(name):
    """(supplier, invoice number, date, due, po number, items) printed on a sample PDF."""
    if name in gen.SAMPLE_DATA_CASES:
        inv = gen.sample_data_invoice(name)
        return inv["supplier"]["name"], inv["invoice_number"], inv["invoice_date"], inv["due_date"], \
            inv["po_number"], inv["items"]
    case = gen.TEMPLATE_CASES[name]
    return gen.TEMPLATE_SUPPLIER["name"], case["number"], case["date"], case["due"], "PO-1001", case["items"]


def _fake_reader(name):
    supplier, number, date, due, po, items = _expected(name)
    t = gen.totals(items)

    def fake(path):
        assert Path(path).name.endswith(".pdf")
        return ExtractedInvoice(
            vendor=supplier, invoice_number=number, invoice_date=date, due_date=due, po_reference=po,
            subtotal=t["subtotal"], gst_amount=t["gst"], grand_total=t["total"],
            items=[ExtractedItem(name=n, quantity=q, unit_price=p, total_price=round(q * p, 2)) for n, q, p in items],
            confidence=0.97, is_success=True, model_name="fake-reader",
        )
    return fake


ALL_FILES = list(gen.SAMPLE_DATA_CASES) + list(gen.TEMPLATE_CASES)


@pytest.mark.parametrize("name", ALL_FILES)
def test_pdf_contains_the_expected_numbers(name):
    with pdfplumber.open(SAMPLES / name) as pdf:
        text = pdf.pages[0].extract_text()
    supplier, number, _, _, po, items = _expected(name)
    t = gen.totals(items)
    for needle in (supplier, number, po, f"Rs. {t['total']:,.2f}") + tuple(n for n, _, _ in items):
        assert needle in text, needle


def test_sample_pdfs_are_in_sync_with_the_generator(tmp_path):
    """The committed PDFs are what the script produces today (they cannot drift from the sample data)."""
    for name in gen.SAMPLE_DATA_CASES:
        inv = gen.sample_data_invoice(name)
        out = tmp_path / name
        gen.render_invoice_pdf(out, inv["supplier"], inv["invoice_number"], inv["invoice_date"], inv["due_date"],
                               inv["po_number"], inv["items"])
        with pdfplumber.open(out) as fresh, pdfplumber.open(SAMPLES / name) as committed:
            assert fresh.pages[0].extract_text() == committed.pages[0].extract_text(), name


def _ingest(client, headers, monkeypatch, name):
    monkeypatch.setattr(invoice_service.reader, "read_invoice", _fake_reader(name))
    r = client.post("/api/invoices/ingest", headers=headers,
                    files={"file": (name, (SAMPLES / name).read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def test_sample_data_family_verified_and_price_mismatch(db, monkeypatch):
    """In a workspace that holds the sample data: clean -> verified; mismatch -> price_mismatch, not missing_po."""
    rate_limit.reset()
    with temp_user(load_sample=True) as user, TestClient(app) as client:
        _, raw = api_key_service.create_api_key(db, user.workspace_id, user.user_id, "sample test")
        headers = {"X-API-Key": raw}

        clean = _ingest(client, headers, monkeypatch, "sample_invoice_clean.pdf")
        assert clean["status"] == "verified" and clean["mistakes"] == []
        assert clean["recommended_action"] == "ready_for_human_approval"
        assert clean["supplier_name"] == "Patel Enterprises" and clean["grand_total"] == 267270.0
        assert clean["human_approval_required"] is True and clean["text"].startswith("VERIFIED:")

        bad = _ingest(client, headers, monkeypatch, "sample_invoice_price_mismatch.pdf")
        assert bad["status"] == "mismatch_detected"
        assert "price_mismatch" in bad["mistakes"]
        assert "missing_po" not in bad["mistakes"]            # the PO exists in the sample data
        assert "duplicate_invoice" not in bad["mistakes"]     # new number, new date, new total
        assert bad["supplier_name"] == "Patel Enterprises"
        # 11 desks x Rs. 600 over the contract price, plus the 18% GST on that amount
        assert bad["difference_amount"] == pytest.approx(11 * 600.0 * 1.18)
        assert bad["recommended_action"] != "ready_for_human_approval"
        assert "price mismatch" in bad["text"] and bad["text"].startswith("MISMATCH:")


def test_template_family_verified_and_price_mismatch(db, monkeypatch):
    rate_limit.reset()
    with temp_user(load_sample=False) as user, TestClient(app) as client:
        ws, t = user.workspace_id, upload_service.TEMPLATES
        upload_service.import_purchase_orders(db, ws, t["purchase_orders.csv"].encode())
        upload_service.import_grns(db, ws, t["goods_received_notes.csv"].encode())
        upload_service.import_contract_prices(db, ws, t["contract_prices.csv"].encode())
        _, raw = api_key_service.create_api_key(db, ws, user.user_id, "template test")
        headers = {"X-API-Key": raw}

        clean = _ingest(client, headers, monkeypatch, "template_invoice_clean.pdf")
        assert clean["status"] == "verified" and clean["mistakes"] == []
        assert clean["supplier_name"] == "Acme Office Supplies" and clean["grand_total"] == 60180.0

        bad = _ingest(client, headers, monkeypatch, "template_invoice_price_mismatch.pdf")
        assert bad["status"] == "mismatch_detected" and "price_mismatch" in bad["mistakes"]
        assert "missing_po" not in bad["mistakes"]
        assert bad["difference_amount"] == pytest.approx(10 * 300.0 * 1.18)  # incl. 18% GST
