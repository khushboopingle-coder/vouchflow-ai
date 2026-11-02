"""
Unit Tests for 3-Way Matching Engine (Phase 3 & Hard Stress-Test Fixes)
========================================================================
Tests the deterministic 3-way matching checker across:
1. Clean match (verified)
2. Price mismatch (mismatch_detected)
3. Quantity mismatch (mismatch_detected)
4. Wrong total / calculation error (mismatch_detected)
5. Duplicate invoice by number, date+amount, and file hash (mismatch_detected)
6. Missing Purchase Order (needs_review)
7. Failed or low-confidence extraction (needs_review)
8. API endpoints: POST /invoices/{id}/check and GET /invoices/{id}/check
9. Price verification against BOTH PO and Contract (INV_056, INV_058)
10. Over-delivery exceeding PO quantity even when GRN matches (INV_061)
11. Duplicate detection scoped strictly to same supplier (cross-supplier valid) (INV_080, INV_082)
12. Commercial rounding tolerance (differences <= Rs. 1.00 accepted, > Rs. 1.00 rejected)
13. Compound mistake priority ordering (missing_po > duplicate > price > qty > total)
14. Policy: missing PO forces status 'needs_review' even with arithmetic discrepancies
"""

import os
import json
import tempfile
from pathlib import Path
from datetime import date
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings
from backend.database.db import SessionLocal
from backend.database.models import (
    Invoice,
    InvoiceItem,
    InvoiceExtraction,
    PurchaseOrder,
    POItem,
    GoodsReceivedNote,
    GRNItem,
    Contract,
    Supplier,
    InvoiceCheck,
    AuditLog
)
from backend.database.schemas import ExtractedInvoice, ExtractedItem
from backend.tools.matcher import perform_three_way_match, compute_file_hash


@pytest.fixture(scope="module")
def db_session():
    """Provides a database session for test execution."""
    session = SessionLocal()
    yield session
    session.close()


def test_matcher_clean_invoice(db_session):
    """Verifies that a perfectly matching invoice returns status 'verified' with no mistakes."""
    res = perform_three_way_match(1, db_session)

    assert res.status == "verified"
    assert res.mistake_types == ["none"]
    assert res.difference_amount == 0.0
    assert len(res.findings) > 0

    # Ensure all primary check findings passed
    for f in res.findings:
        assert f.status in ("pass", "info")


def test_matcher_price_mismatch(db_session):
    """Verifies that an invoice with inflated unit price is detected as price_mismatch."""
    res = perform_three_way_match(19, db_session)

    assert res.status == "mismatch_detected"
    assert "price_mismatch" in res.mistake_types
    assert res.difference_amount > 0.0

    price_findings = [f for f in res.findings if f.check_name == "price" and f.status == "fail"]
    assert len(price_findings) > 0
    assert "Price mismatch" in price_findings[0].message


def test_matcher_quantity_mismatch(db_session):
    """Verifies that an invoice billing for more than physical warehouse GRN is detected."""
    res = perform_three_way_match(15, db_session)

    assert res.status == "mismatch_detected"
    assert "quantity_mismatch" in res.mistake_types
    assert res.difference_amount > 0.0

    qty_findings = [f for f in res.findings if f.check_name == "quantity" and f.status == "fail"]
    assert len(qty_findings) > 0
    assert "Quantity mismatch" in qty_findings[0].message


def test_matcher_wrong_total(db_session):
    """Verifies that mathematical calculation errors on line items or taxes are detected."""
    res = perform_three_way_match(21, db_session)

    assert res.status == "mismatch_detected"
    assert "wrong_total" in res.mistake_types
    assert res.difference_amount > 0.0

    tot_findings = [f for f in res.findings if f.check_name == "totals" and f.status == "fail"]
    assert len(tot_findings) > 0
    assert "Mathematical calculation error" in tot_findings[0].message


def test_matcher_duplicate_invoice(db_session):
    """Verifies that duplicate invoice submissions from the same supplier are detected."""
    res = perform_three_way_match(6, db_session)

    assert res.status == "mismatch_detected"
    assert "duplicate_invoice" in res.mistake_types

    dup_findings = [f for f in res.findings if f.check_name == "duplicate_invoice" and f.status == "fail"]
    assert len(dup_findings) > 0
    assert "Duplicate invoice detected" in dup_findings[0].message


def test_matcher_missing_po(db_session):
    """Verifies that invoices without a valid PO are flagged as needs_review with missing_po."""
    res = perform_three_way_match(24, db_session)

    assert res.status == "needs_review"
    assert "missing_po" in res.mistake_types

    po_findings = [f for f in res.findings if f.check_name == "missing_po" and f.status == "fail"]
    assert len(po_findings) > 0
    assert "Missing Purchase Order" in po_findings[0].message


def test_matcher_failed_or_low_confidence_extraction(db_session):
    """
    Verifies rule: If extraction failed or confidence is low (< 0.70),
    status must be 'needs_review', NEVER 'verified'.
    """
    # Low confidence extraction
    low_conf_extracted = ExtractedInvoice(
        vendor="Sharma Traders",
        invoice_number="INV-TEST",
        items=[],
        confidence=0.45,
        is_success=True
    )
    res_low = perform_three_way_match(1, db_session, extracted_override=low_conf_extracted)
    assert res_low.status == "needs_review"
    assert res_low.status != "verified"

    # Failed extraction
    failed_extracted = ExtractedInvoice(
        is_success=False,
        error_message="OCR unreadable",
        confidence=0.0
    )
    res_failed = perform_three_way_match(1, db_session, extracted_override=failed_extracted)
    assert res_failed.status == "needs_review"
    assert res_failed.status != "verified"


def test_api_check_endpoints():
    """
    Tests POST /invoices/{id}/check and GET /invoices/{id}/check
    via FastAPI TestClient.
    """
    client = TestClient(app)

    # 1. Clean up check record for invoice 1
    db = SessionLocal()
    db.query(InvoiceCheck).filter(InvoiceCheck.invoice_id == 1).delete()
    db.commit()
    db.close()

    # 2. Run POST check
    resp_post = client.post("/invoices/1/check")
    assert resp_post.status_code == 200
    data = resp_post.json()
    assert data["invoice_id"] == 1
    assert data["status"] == "verified"
    assert data["mistake_types"] == ["none"]
    assert len(data["findings"]) > 0

    # 3. Verify record was saved in invoice_checks table
    db = SessionLocal()
    saved = db.query(InvoiceCheck).filter(InvoiceCheck.invoice_id == 1).first()
    audit = db.query(AuditLog).filter(
        AuditLog.action == "invoice_check",
        AuditLog.details.like("%Invoice ID 1%")
    ).first()

    assert saved is not None
    assert saved.status == "verified"
    assert audit is not None
    db.close()

    # 4. Run GET check
    resp_get = client.get("/invoices/1/check")
    assert resp_get.status_code == 200
    get_data = resp_get.json()
    assert get_data["id"] == saved.id
    assert get_data["status"] == "verified"
    assert len(get_data["findings"]) > 0


# =============================================================================
# Stress-Test Fixes Verification Tests
# =============================================================================

def test_matcher_price_differs_from_po_or_contract(db_session):
    """
    Fix 1: Compare invoice unit price with BOTH PO price and Contract price.
    If either differs beyond tolerance, flag price_mismatch and state which one differed.
    """
    # Test invoice 56: Invoiced price matches Contract (Rs. 1100) but differs from PO (Rs. 1250)
    res_56 = perform_three_way_match(56, db_session)
    assert res_56.status == "mismatch_detected"
    assert "price_mismatch" in res_56.mistake_types
    fail_findings_56 = [f for f in res_56.findings if f.check_name == "price" and f.status == "fail"]
    assert len(fail_findings_56) > 0
    assert "PO" in fail_findings_56[0].message

    # Test invoice 58: Invoiced price matches Contract (Rs. 4200) but differs from PO (Rs. 3900)
    res_58 = perform_three_way_match(58, db_session)
    assert res_58.status == "mismatch_detected"
    assert "price_mismatch" in res_58.mistake_types


def test_matcher_overdelivery_exceeding_po_quantity(db_session):
    """
    Fix 2: If invoiced quantity is greater than PO quantity, flag quantity_mismatch,
    even if the GRN matches the invoice (INV_061).
    """
    res_61 = perform_three_way_match(61, db_session)
    assert res_61.status == "mismatch_detected"
    assert "quantity_mismatch" in res_61.mistake_types
    qty_findings = [f for f in res_61.findings if f.check_name == "quantity" and f.status == "fail"]
    assert len(qty_findings) > 0
    assert "exceeds PO authorized limit" in qty_findings[0].message or "over-delivery" in qty_findings[0].message


def test_matcher_duplicate_only_same_supplier(db_session):
    """
    Fix 3: The same invoice number is a duplicate ONLY if the supplier is also the same.
    Same number from a different supplier is NOT a duplicate (INV_080, INV_082).
    """
    # Invoice 80 shares INV-SHARED-9901 with Invoice 79, but they are from different suppliers
    res_80 = perform_three_way_match(80, db_session)
    assert "duplicate_invoice" not in res_80.mistake_types
    assert res_80.status == "verified"

    # Invoice 82 shares BILL-COMMON-X1 with Invoice 81, but they are from different suppliers
    res_82 = perform_three_way_match(82, db_session)
    assert "duplicate_invoice" not in res_82.mistake_types
    assert res_82.status == "verified"


def test_matcher_rounding_tolerance_accepted_vs_exceeded(db_session):
    """
    Fix 4: Total differences up to ROUNDING_TOLERANCE_RS (default 1.00) count as OK,
    and finding says 'rounding difference accepted'. Differences above it are wrong_total.
    """
    # Invoices 67, 68, 69, 70 have rounding diffs between Rs. 0.25 and Rs. 0.80 (all <= 1.00)
    for inv_id in [67, 68, 69, 70]:
        res = perform_three_way_match(inv_id, db_session)
        assert res.status == "verified"
        assert res.mistake_types == ["none"]
        pass_findings = [f for f in res.findings if f.check_name == "totals" and f.status == "pass"]
        assert len(pass_findings) > 0
        assert "rounding difference accepted" in pass_findings[0].message

    # Test override with diff > 1.00 (e.g. Rs. 2.50)
    base_inv = db_session.query(Invoice).filter(Invoice.id == 1).first()
    bad_math_extracted = ExtractedInvoice(
        vendor=base_inv.supplier.name,
        invoice_number="INV-ROUND-TEST",
        invoice_date=str(base_inv.invoice_date),
        po_reference=base_inv.purchase_order.po_number,
        items=[ExtractedItem(name="Ergonomic Office Chair", quantity=2, unit_price=4500.0, total_price=9000.0)],
        subtotal=9000.0,
        gst_amount=1620.0,
        grand_total=10620.0 + 2.50,  # exceeds Rs. 1.00 tolerance
        confidence=1.0,
        is_success=True
    )
    res_bad = perform_three_way_match(1, db_session, extracted_override=bad_math_extracted)
    assert res_bad.status == "mismatch_detected"
    assert "wrong_total" in res_bad.mistake_types


def test_matcher_compound_mistakes_priority_order(db_session):
    """
    Fix 5: Priority order for compound mistakes:
    missing_po > duplicate_invoice > price_mismatch > quantity_mismatch > wrong_total.
    """
    # Invoice 88 has both price mismatch and wrong total -> primary is price_mismatch
    res_88 = perform_three_way_match(88, db_session)
    assert res_88.mistake_types[0] == "price_mismatch"
    assert "wrong_total" in res_88.mistake_types

    # Invoice 89 has both quantity mismatch and wrong total -> primary is quantity_mismatch
    res_89 = perform_three_way_match(89, db_session)
    assert res_89.mistake_types[0] == "quantity_mismatch"
    assert "wrong_total" in res_89.mistake_types


def test_matcher_missing_po_forces_needs_review(db_session):
    """
    Fix 6: Policy: If a PO is missing, the status is needs_review,
    even if other errors (like wrong_total) exist (INV_090).
    """
    res_90 = perform_three_way_match(90, db_session)
    assert res_90.status == "needs_review"
    assert res_90.mistake_types[0] == "missing_po"
