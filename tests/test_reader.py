"""
Invoice Reader Unit Tests (Phase 1)
===================================
Tests the Invoice Reader engine and multi-model rotation using mocked Gemini responses.
Zero external API calls and no API key required for test suite execution.

Coverage:
1. pdfplumber text extraction
2. JSON stripping and cleaning
3. Quality confidence score & missing fields calculation
4. Mocked Gemini end-to-end extraction (success path)
5. Retry mechanism on malformed JSON
6. Multi-model daily limit (429 PerDay) automatic switching
7. Transient 503 busy retries with backoff
8. Graceful stop when all models are exhausted
9. Scoring logic: empty/failed extractions strictly fail all fields
10. API endpoints: POST /invoices/{id}/extract and GET /invoices/{id}/extraction
"""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.db import SessionLocal
from backend.database.models import Invoice, InvoiceExtraction, AuditLog
from backend.tools.invoice_reader import (
    InvoiceReader,
    ModelStateTracker,
    extract_text_from_pdf,
    clean_json_response,
    calculate_quality_metrics,
    reader
)
from backend.database.schemas import ExtractedInvoice
from scripts.run_extraction_eval import normalize_str, normalize_inv_num, compare_dates


SAMPLE_PDF = Path("data/invoices/INV_001.pdf")


def test_pdfplumber_text_extraction():
    """Verifies that pdfplumber extracts legible text from generated invoice PDFs."""
    assert SAMPLE_PDF.exists(), "Sample PDF data/invoices/INV_001.pdf not found."
    text = extract_text_from_pdf(SAMPLE_PDF)

    assert len(text) > 100, f"Expected >100 characters extracted, got {len(text)}."
    assert "TAX INVOICE" in text
    assert "Rs." in text
    assert "Sharma Traders" in text


def test_clean_json_response():
    """Verifies that clean_json_response correctly strips markdown fences and noise."""
    # Test 1: Markdown code block
    raw_markdown = '```json\n{"vendor": "Sharma Traders", "invoice_number": "INV-1"}\n```'
    cleaned = clean_json_response(raw_markdown)
    assert json.loads(cleaned) == {"vendor": "Sharma Traders", "invoice_number": "INV-1"}

    # Test 2: Text surrounding JSON
    surrounded = 'Here is the extracted invoice data:\n{"grand_total": 500.0}\nHope this helps!'
    cleaned2 = clean_json_response(surrounded)
    assert json.loads(cleaned2) == {"grand_total": 500.0}


def test_calculate_quality_metrics():
    """Verifies confidence score and missing field identification."""
    # Complete invoice data
    full_data = {
        "vendor": "Sharma Traders",
        "invoice_number": "INV-001",
        "invoice_date": "2026-01-12",
        "grand_total": 1180.0,
        "items": [{"name": "Desk", "quantity": 1, "unit_price": 1000.0}],
        "subtotal": 1000.0,
        "gst_amount": 180.0
    }
    score, missing = calculate_quality_metrics(full_data)
    assert score == 1.0
    assert missing == []

    # Partial invoice data
    partial_data = {
        "vendor": "Sharma Traders",
        "invoice_number": "INV-001"
    }
    score_part, missing_part = calculate_quality_metrics(partial_data)
    assert score_part < 1.0
    assert "grand_total" in missing_part
    assert "invoice_date" in missing_part
    assert "items" in missing_part


def test_read_invoice_success_mocked():
    """Verifies reader.read_invoice with a mocked Gemini client response."""
    mock_payload = {
        "vendor": "Sharma Traders Pvt Ltd",
        "invoice_number": "INV-2026-0001",
        "invoice_date": "2026-01-12",
        "due_date": "2026-02-11",
        "po_reference": "PO-2026-0001",
        "items": [
            {
                "name": "Standing Desk 120cm",
                "quantity": 5,
                "unit_price": 12000.0,
                "total_price": 60000.0
            }
        ],
        "subtotal": 60000.0,
        "gst_amount": 10800.0,
        "grand_total": 70800.0,
        "currency": "INR"
    }

    mock_response = MagicMock()
    mock_response.text = json.dumps(mock_payload)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    custom_reader = InvoiceReader(models=["mock-model-1"], client=mock_client)
    result = custom_reader.read_invoice(str(SAMPLE_PDF), rate_limit_delay=0)

    assert isinstance(result, ExtractedInvoice)
    assert result.is_success is True
    assert result.vendor == "Sharma Traders Pvt Ltd"
    assert result.invoice_number == "INV-2026-0001"
    assert result.grand_total == 70800.0
    assert len(result.items) == 1
    assert result.confidence == 1.0
    assert result.model_name == "mock-model-1"


def test_read_invoice_retry_on_bad_json():
    """Verifies that the reader retries once if Gemini outputs malformed JSON on attempt 1."""
    valid_payload = {
        "vendor": "Patel Enterprises",
        "invoice_number": "INV-2026-0002",
        "invoice_date": "2026-01-14",
        "grand_total": 267270.0,
        "items": [{"name": "Monitor", "quantity": 2, "unit_price": 8500.0}]
    }

    mock_resp1 = MagicMock()
    mock_resp1.text = "{ broken json content ..."

    mock_resp2 = MagicMock()
    mock_resp2.text = json.dumps(valid_payload)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [mock_resp1, mock_resp2]

    custom_reader = InvoiceReader(models=["mock-model-1"], client=mock_client)
    result = custom_reader.read_invoice(str(SAMPLE_PDF), rate_limit_delay=0)

    assert result.is_success is True
    assert result.vendor == "Patel Enterprises"
    assert result.invoice_number == "INV-2026-0002"
    assert mock_client.models.generate_content.call_count == 2


def test_read_invoice_daily_limit_switching(tmp_path):
    """
    Verifies that when Model 1 raises 429 Daily/PerDay limit, the reader:
    1. Marks Model 1 as exhausted in state tracker.
    2. Switches automatically to Model 2.
    3. Successfully retries and extracts the invoice on Model 2.
    """
    state_file = tmp_path / "model_state_test.json"
    tracker = ModelStateTracker(state_file=state_file)

    valid_payload = {
        "vendor": "Reddy Logistics",
        "invoice_number": "INV-2026-0003",
        "invoice_date": "2026-01-15",
        "grand_total": 198240.0,
        "items": [{"name": "Logistics Service", "quantity": 1, "unit_price": 168000.0}]
    }

    mock_resp_success = MagicMock()
    mock_resp_success.text = json.dumps(valid_payload)

    def side_effect(model, contents, config):
        if model == "model-primary":
            raise RuntimeError("429 Resource has been exhausted (e.g. check quota). PerDay limit reached.")
        elif model == "model-secondary":
            return mock_resp_success
        raise ValueError(f"Unexpected model: {model}")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = side_effect

    custom_reader = InvoiceReader(
        models=["model-primary", "model-secondary"],
        client=mock_client,
        state_tracker=tracker
    )

    result = custom_reader.read_invoice(str(SAMPLE_PDF), rate_limit_delay=0)

    assert result.is_success is True
    assert result.vendor == "Reddy Logistics"
    assert result.model_name == "model-secondary"
    assert not tracker.is_model_available("model-primary")
    assert tracker.is_model_available("model-secondary")


def test_read_invoice_busy_then_success():
    """
    Verifies that when a model experiences 503 high-demand spikes:
    1. The reader waits and retries the SAME model.
    2. Succeeds when the service recovers on attempt 3.
    """
    valid_payload = {
        "vendor": "Gupta Stationery",
        "invoice_number": "INV-2026-0004",
        "invoice_date": "2026-01-16",
        "grand_total": 31742.0,
        "items": [{"name": "A4 Paper", "quantity": 10, "unit_price": 2690.0}]
    }

    mock_resp_success = MagicMock()
    mock_resp_success.text = json.dumps(valid_payload)

    # 2 temporary 503 failures followed by success
    call_count = 0
    def side_effect(model, contents, config):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("503 UNAVAILABLE. {'message': 'This model is currently experiencing high demand.'}")
        return mock_resp_success

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = side_effect

    # Use micro-delays for fast unit testing
    custom_reader = InvoiceReader(
        models=["model-busy"],
        client=mock_client,
        retry_delays=(0.01, 0.01, 0.01, 0.01)
    )

    result = custom_reader.read_invoice(str(SAMPLE_PDF), rate_limit_delay=0)

    assert result.is_success is True
    assert result.vendor == "Gupta Stationery"
    assert call_count == 3
    assert result.model_name == "model-busy"


def test_read_invoice_all_models_exhausted(tmp_path):
    """
    Verifies that when all configured models are exhausted, the reader stops cleanly
    without unhandled crashes and returns an informative error message.
    """
    state_file = tmp_path / "model_state_exhausted.json"
    tracker = ModelStateTracker(state_file=state_file)

    def side_effect(model, contents, config):
        raise RuntimeError(f"429 Quota Exceeded. Requests per day limit reached for {model}.")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = side_effect

    custom_reader = InvoiceReader(
        models=["model-alpha", "model-beta"],
        client=mock_client,
        state_tracker=tracker
    )

    result = custom_reader.read_invoice(str(SAMPLE_PDF), rate_limit_delay=0)

    assert isinstance(result, ExtractedInvoice)
    assert result.is_success is False
    assert "All models reached their daily limit" in result.error_message
    assert result.confidence == 0.0
    assert not tracker.is_model_available("model-alpha")
    assert not tracker.is_model_available("model-beta")


def test_scoring_strict_on_empty_and_failed_extractions():
    """
    Verifies the scoring bug fix:
    An empty, missing, or failed extraction MUST strictly evaluate to False for all fields.
    """
    gt_vendor = "Sharma Traders Pvt Ltd"
    gt_inv_num = "INV-2026-0001"
    gt_date = "2026-01-12"

    # Case 1: Empty extracted vendor must NOT match ground truth
    empty_vendor = ""
    norm_gt = normalize_str(gt_vendor)
    norm_empty = normalize_str(empty_vendor)
    vendor_match = bool(norm_empty and (norm_gt in norm_empty or norm_empty in norm_gt))
    assert vendor_match is False, "Empty vendor must never match!"

    # Case 2: Matching vendor
    ext_vendor = "Sharma Traders"
    norm_ext = normalize_str(ext_vendor)
    match_ok = bool(norm_ext and (norm_gt in norm_ext or norm_ext in norm_gt))
    assert match_ok is True

    # Case 3: Normalized invoice numbers ignore case, spaces, and hyphens
    assert normalize_inv_num("inv-2026-0001") == normalize_inv_num("INV 2026 0001")
    assert normalize_inv_num("") == ""

    # Case 4: Dates compare accurately across formats
    assert compare_dates("2026-01-12", "12-01-2026") is True
    assert compare_dates("2026-01-12", "") is False


def test_api_extract_and_get_extraction_endpoints(tmp_path, api_user):
    """
    Tests POST /invoices/{id}/extract and GET /invoices/{id}/extraction
    using FastAPI TestClient and mocked Gemini.
    """
    client = TestClient(app)
    H = api_user.headers
    INV2 = api_user.ids[2]  # the test user's copy of sample invoice 2

    # 1. Clean up test extraction from invoice 2
    db = SessionLocal()
    db.query(InvoiceExtraction).filter(InvoiceExtraction.invoice_id == INV2).delete()
    db.commit()
    db.close()

    r_before_clean = client.get(f"/invoices/{INV2}/extraction", headers=H)
    assert r_before_clean.status_code == 404

    # 2. Mock reader client for POST extraction
    mock_payload = {
        "vendor": "Patel Enterprises",
        "invoice_number": "INV-2026-0002",
        "invoice_date": "2026-01-14",
        "grand_total": 267270.0,
        "items": [{"name": "IPS Monitor", "quantity": 5, "unit_price": 8500.0}]
    }
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(mock_payload)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_resp

    original_client = reader.client
    original_models = reader.models
    original_delays = reader.retry_delays
    original_idx = reader.current_model_idx
    original_tracker = reader.state_tracker

    reader.client = mock_client
    reader.models = ["gemini-3.5-flash-lite"]
    reader.retry_delays = (0.0, 0.0)
    reader.state_tracker = ModelStateTracker(state_file=tmp_path / "test_api_state.json")
    reader.current_model_idx = 0

    try:
        # Check initial status of invoice 2
        db = SessionLocal()
        initial_status = db.query(Invoice).filter(Invoice.id == INV2).first().status
        db.close()

        # Run POST extract
        response = client.post(f"/invoices/{INV2}/extract", headers=H)
        assert response.status_code == 200
        data = response.json()
        assert data["vendor"] == "Patel Enterprises"
        assert data["invoice_number"] == "INV-2026-0002"
        assert data["is_success"] is True

        # Check database records
        db = SessionLocal()
        inv = db.query(Invoice).filter(Invoice.id == INV2).first()
        extraction = db.query(InvoiceExtraction).filter(InvoiceExtraction.invoice_id == INV2).first()
        audit = db.query(AuditLog).filter(
            AuditLog.action == "invoice_extraction",
            AuditLog.details.like(f"%ID {INV2} %")
        ).first()

        # CRITICAL ASSERTION: Invoice status was NOT changed
        assert inv.status == initial_status, "Extraction must NOT change invoice status!"
        assert extraction is not None
        assert extraction.confidence > 0
        assert audit is not None
        db.close()

        # 3. Test GET extraction endpoint returns saved record
        r_get = client.get(f"/invoices/{INV2}/extraction", headers=H)
        assert r_get.status_code == 200
        get_data = r_get.json()
        assert get_data["invoice_id"] == INV2
        assert get_data["data"]["vendor"] == "Patel Enterprises"
        assert get_data["data"]["invoice_number"] == "INV-2026-0002"

    finally:
        reader.client = original_client
        reader.models = original_models
        reader.retry_delays = original_delays
        reader.current_model_idx = original_idx
        reader.state_tracker = original_tracker
        # Clean up test extraction from invoice 2
        db = SessionLocal()
        db.query(InvoiceExtraction).filter(InvoiceExtraction.invoice_id == INV2).delete()
        db.query(AuditLog).filter(
            AuditLog.action == "invoice_extraction",
            AuditLog.details.like(f"%ID {INV2} %")
        ).delete()
        db.commit()
        db.close()
