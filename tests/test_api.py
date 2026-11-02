"""
API Automated Tests for VouchFlow AI
====================================
Tests:
- GET /health endpoint
- GET /invoices listing endpoint
- GET /invoices/{id} single invoice retrieval (and 404 handling)
- POST /invoices/upload file upload and audit log creation
- File type validation for uploads
"""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.db import SessionLocal
from backend.database.models import Invoice, AuditLog


@pytest.fixture(scope="module")
def client():
    """Provides a FastAPI test client instance."""
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client):
    """Verifies that GET /health returns 200 OK and status 'ok'."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_invoices_endpoint(client):
    """Verifies that GET /invoices returns a list of invoices."""
    response = client.get("/invoices")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        first = data[0]
        assert "id" in first
        assert "invoice_number" in first
        assert "status" in first
        assert "grand_total" in first


def test_get_single_invoice_success(client):
    """Verifies that GET /invoices/{id} returns details and line items for an existing invoice."""
    # Query invoice with ID 1
    response = client.get("/invoices/1")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 1
    assert "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) > 0


def test_get_single_invoice_not_found(client):
    """Verifies that GET /invoices/{id} returns 404 for a non-existent ID."""
    response = client.get("/invoices/999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_upload_invoice_endpoint(client):
    """
    Verifies that POST /invoices/upload:
    1. Saves the uploaded file into data/invoices/
    2. Creates an invoice row with status 'needs_review'
    3. Creates an audit_logs entry for the upload action
    """
    test_filename = "pytest_upload_invoice.pdf"
    fake_pdf_content = b"%PDF-1.4 test sample invoice for pytest"

    db = SessionLocal()
    initial_audit_count = db.query(AuditLog).count()
    db.close()

    response = client.post(
        "/invoices/upload",
        files={"file": (test_filename, fake_pdf_content, "application/pdf")}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "needs_review"
    assert "invoice_id" in data
    created_id = data["invoice_id"]

    # Verify database record
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == created_id).first()
        assert inv is not None
        assert inv.status == "needs_review"

        # Verify audit log was recorded
        audit = db.query(AuditLog).filter(AuditLog.details.like(f"%{test_filename}%")).first()
        assert audit is not None
        assert audit.action == "invoice_upload"

        # Clean up test database row and audit log
        db.delete(inv)
        db.delete(audit)
        db.commit()
    finally:
        db.close()

    # Clean up uploaded test file
    uploaded_file_path = Path("data/invoices") / data["file_name"]
    if uploaded_file_path.exists():
        uploaded_file_path.unlink()


def test_upload_invalid_file_type(client):
    """Verifies that POST /invoices/upload rejects unsupported file extensions."""
    response = client.post(
        "/invoices/upload",
        files={"file": ("unsupported_script.py", b"print('malicious')", "text/plain")}
    )
    assert response.status_code == 400
    assert "invalid file type" in response.json()["detail"].lower()
