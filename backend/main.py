"""
VouchFlow AI - FastAPI Backend API
==================================
Endpoints:
- GET /health                    : Health check endpoint
- GET /invoices                  : Lists all invoices with statuses and supplier details
- GET /invoices/{id}             : Retrieves a single invoice with its line items
- POST /invoices/upload          : Uploads invoice PDF/image, creates record ('needs_review') & audit log
- POST /invoices/{id}/extract    : Runs AI/OCR extraction and saves to invoice_extractions
- GET /invoices/{id}/extraction  : Returns the saved extraction record
- GET /audit-logs                : Lists recent audit log records
"""

from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.database.db import get_db, init_db
from backend.database import schemas
from backend.database.models import AuditLog
from backend.services import invoice_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes tables on server startup."""
    init_db()
    yield


app = FastAPI(
    title="VouchFlow AI API",
    description="Intelligent Accounts Payable & 3-Way Matching Foundation API",
    version="1.1.0",
    lifespan=lifespan
)

# Enable CORS for local development and dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/health",
    response_model=schemas.HealthResponse,
    summary="Health check",
    tags=["System"]
)
def health_check():
    """Returns system operational health status."""
    return {"status": "ok"}


@app.get(
    "/invoices",
    response_model=List[schemas.InvoiceRead],
    summary="List all invoices",
    tags=["Invoices"]
)
def list_invoices(
    status: Optional[str] = Query(
        None,
        description="Filter by invoice status: verified, needs_review, mismatch_detected, pending_approval"
    ),
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(100, ge=1, le=500, description="Number of invoices to return"),
    db: Session = Depends(get_db)
):
    """
    Returns a list of all invoices with supplier name, PO number,
    totals, and verification status.
    """
    return invoice_service.list_invoices(
        db=db,
        status_filter=status,
        skip=skip,
        limit=limit
    )


@app.get(
    "/invoices/{invoice_id}",
    response_model=schemas.InvoiceDetail,
    summary="Get single invoice details",
    tags=["Invoices"]
)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """
    Returns full details of an invoice including line items,
    vendor information, and linked purchase order.
    """
    return invoice_service.get_invoice_by_id(db=db, invoice_id=invoice_id)


@app.post(
    "/invoices/upload",
    response_model=schemas.UploadResponse,
    summary="Upload an invoice file (PDF/Image)",
    tags=["Invoices"]
)
def upload_invoice(
    file: UploadFile = File(..., description="Invoice document (PDF, PNG, JPG)"),
    db: Session = Depends(get_db)
):
    """
    Receives an uploaded invoice file, saves it to data/invoices/,
    creates a new invoice entry with status 'needs_review',
    and logs an audit entry.
    """
    return invoice_service.save_uploaded_invoice(db=db, file=file, who="portal_user")


@app.post(
    "/invoices/{invoice_id}/extract",
    response_model=schemas.ExtractedInvoice,
    summary="Extract structured data from an invoice document using AI/OCR",
    tags=["Extraction"]
)
def extract_invoice(
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """
    Runs the Invoice Reader (pdfplumber + Gemini AI) on the invoice file.
    Saves the extracted JSON in the invoice_extractions table and writes an audit log.
    NOTE: Invoice status is NOT modified.
    """
    return invoice_service.extract_invoice_data(db=db, invoice_id=invoice_id, who="api_user")


@app.get(
    "/invoices/{invoice_id}/extraction",
    response_model=schemas.InvoiceExtractionDetail,
    summary="Get saved extraction for an invoice",
    tags=["Extraction"]
)
def get_extraction(
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """
    Retrieves the most recent extraction record for an invoice.
    """
    return invoice_service.get_invoice_extraction(db=db, invoice_id=invoice_id)


@app.post(
    "/invoices/{invoice_id}/check",
    response_model=schemas.InvoiceCheckDetail,
    summary="Run 3-way matching check on an invoice",
    tags=["Matching"]
)
def check_invoice(
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """
    Executes automated 3-way matching comparing the invoice with PO, GRN, and Contract.
    Flags price, quantity, totals, duplicate, and missing PO discrepancies.
    Persists result in invoice_checks table and writes an audit log.
    NOTE: Invoice status is NOT modified.
    """
    return invoice_service.check_invoice_matching(db=db, invoice_id=invoice_id, who="api_user")


@app.get(
    "/invoices/{invoice_id}/check",
    response_model=schemas.InvoiceCheckDetail,
    summary="Get saved 3-way matching check for an invoice",
    tags=["Matching"]
)
def get_invoice_check(
    invoice_id: int,
    db: Session = Depends(get_db)
):
    """
    Retrieves the most recent 3-way matching check result for an invoice.
    """
    return invoice_service.get_invoice_check(db=db, invoice_id=invoice_id)


@app.get(
    "/audit-logs",
    response_model=List[schemas.AuditLogRead],
    summary="List recent audit log entries",
    tags=["Audit"]
)
def list_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Returns recent system audit log events."""
    return db.query(AuditLog).order_by(AuditLog.time.desc()).limit(limit).all()
