"""
Invoice Service Layer for VouchFlow AI
======================================
Handles business logic:
- Querying invoice lists with optional filtering
- Retrieving single invoice details with line items
- Handling uploaded invoice PDFs/images and creating audit logs
- Running Phase 1 AI/OCR extraction and storing extractions
"""

import os
import json
import shutil
from pathlib import Path
from datetime import date, datetime
from typing import List, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from backend.config import settings
from backend.database.models import (
    Invoice,
    InvoiceItem,
    AuditLog,
    Supplier,
    PurchaseOrder,
    InvoiceExtraction,
    InvoiceCheck,
    InvoiceInvestigation
)
from backend.database.schemas import (
    InvoiceRead,
    InvoiceDetail,
    UploadResponse,
    ExtractedInvoice,
    InvoiceExtractionDetail,
    MatchFinding,
    InvoiceCheckResult,
    InvoiceCheckDetail
)
from backend.agent.state import InvestigationReport
from backend.agent.graph import run_investigation
from backend.tools.invoice_reader import reader
from backend.tools.matcher import perform_three_way_match


def list_invoices(
    db: Session,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
) -> List[InvoiceRead]:
    """
    Retrieves a list of invoices with supplier name and PO number.
    Optionally filters by status (e.g. 'verified', 'needs_review', 'mismatch_detected').
    """
    query = (
        db.query(Invoice)
        .options(
            joinedload(Invoice.supplier),
            joinedload(Invoice.purchase_order)
        )
    )

    if status_filter:
        query = query.filter(Invoice.status == status_filter)

    invoices = query.order_by(Invoice.id.desc()).offset(skip).limit(limit).all()

    results = []
    for inv in invoices:
        results.append(
            InvoiceRead(
                id=inv.id,
                invoice_number=inv.invoice_number,
                supplier_id=inv.supplier_id,
                supplier_name=inv.supplier.name if inv.supplier else "Unknown Supplier",
                po_id=inv.po_id,
                po_number=inv.purchase_order.po_number if inv.purchase_order else "N/A",
                invoice_date=inv.invoice_date,
                due_date=inv.due_date,
                subtotal=inv.subtotal,
                tax_amount=inv.tax_amount,
                grand_total=inv.grand_total,
                file_path=inv.file_path,
                status=inv.status,
                created_at=inv.created_at
            )
        )

    return results


def get_invoice_by_id(db: Session, invoice_id: int) -> InvoiceDetail:
    """
    Retrieves full details for a single invoice including line items,
    supplier details, and purchase order info.
    Raises HTTP 404 if the invoice does not exist.
    """
    inv = (
        db.query(Invoice)
        .options(
            joinedload(Invoice.items),
            joinedload(Invoice.supplier),
            joinedload(Invoice.purchase_order)
        )
        .filter(Invoice.id == invoice_id)
        .first()
    )

    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice with ID {invoice_id} not found."
        )

    return InvoiceDetail(
        id=inv.id,
        invoice_number=inv.invoice_number,
        supplier_id=inv.supplier_id,
        supplier_name=inv.supplier.name if inv.supplier else "Unknown Supplier",
        po_id=inv.po_id,
        po_number=inv.purchase_order.po_number if inv.purchase_order else "N/A",
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        subtotal=inv.subtotal,
        tax_amount=inv.tax_amount,
        grand_total=inv.grand_total,
        file_path=inv.file_path,
        status=inv.status,
        created_at=inv.created_at,
        items=inv.items,
        supplier=inv.supplier,
        purchase_order=inv.purchase_order
    )


def save_uploaded_invoice(
    db: Session,
    file: UploadFile,
    who: str = "web_user"
) -> UploadResponse:
    """
    Saves an uploaded invoice PDF or image into data/invoices/, creates a new
    invoice row with status 'needs_review', and records an entry in audit_logs.
    """
    # Validate file extension
    allowed_extensions = {".pdf", ".png", ".jpg", ".jpeg"}
    original_filename = file.filename or "uploaded_invoice.pdf"
    file_ext = Path(original_filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{file_ext}'. Allowed types: {', '.join(allowed_extensions)}"
        )

    # Destination directory: data/invoices/
    invoices_dir = settings.data_path / "invoices"
    invoices_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize and prepare destination file path
    safe_basename = Path(original_filename).stem.replace(" ", "_")
    target_filename = f"{safe_basename}{file_ext}"
    target_path = invoices_dir / target_filename

    # If file with this name already exists, add an incremental index
    counter = 1
    while target_path.exists():
        target_filename = f"{safe_basename}_{counter}{file_ext}"
        target_path = invoices_dir / target_filename
        counter += 1

    # Save file to disk
    try:
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file to disk: {str(e)}"
        )

    # Relative path stored in database
    relative_file_path = f"data/invoices/{target_filename}"

    # Create new Invoice record with status 'needs_review'
    new_invoice = Invoice(
        invoice_number=safe_basename.upper(),
        supplier_id=None,
        po_id=None,
        invoice_date=date.today(),
        subtotal=0.0,
        tax_amount=0.0,
        grand_total=0.0,
        file_path=relative_file_path,
        status="needs_review"  # New uploads default to 'needs_review'
    )
    db.add(new_invoice)
    db.flush()  # Acquire generated primary key id

    # Create Audit Log entry for this upload
    audit_entry = AuditLog(
        who=who,
        action="invoice_upload",
        details=f"Uploaded file '{original_filename}' saved to '{relative_file_path}'. Created Invoice ID {new_invoice.id} with status 'needs_review'."
    )
    db.add(audit_entry)
    db.commit()
    db.refresh(new_invoice)

    return UploadResponse(
        message="Invoice uploaded successfully and queued for review.",
        invoice_id=new_invoice.id,
        file_name=target_filename,
        status=new_invoice.status,
        file_path=relative_file_path
    )


def extract_invoice_data(
    db: Session,
    invoice_id: int,
    who: str = "api_user"
) -> ExtractedInvoice:
    """
    Runs the InvoiceReader on the document associated with invoice_id,
    persists the extraction in the invoice_extractions table, and
    records an audit_logs entry.

    CRITICAL INSTRUCTION: Extraction does NOT alter invoice status.
    """
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice with ID {invoice_id} not found."
        )

    if not inv.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice ID {invoice_id} has no associated file path."
        )

    # Resolve document path
    file_path = Path(inv.file_path)
    if not file_path.is_absolute():
        file_path = settings.data_path.parent / inv.file_path

    if not file_path.exists():
        # Also check directly under data/invoices
        alt_path = settings.data_path / "invoices" / Path(inv.file_path).name
        if alt_path.exists():
            file_path = alt_path
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Physical file for invoice not found at {file_path}."
            )

    # Run AI/OCR extraction
    result: ExtractedInvoice = reader.read_invoice(str(file_path))

    # Save extraction record in database
    used_model = result.model_name or reader.model_name or "unknown"
    extraction_record = InvoiceExtraction(
        invoice_id=inv.id,
        extracted_json=result.model_dump_json(),
        confidence=result.confidence,
        model_name=used_model
    )
    db.add(extraction_record)

    # Record audit log entry
    audit_entry = AuditLog(
        who=who,
        action="invoice_extraction",
        details=(
            f"Extracted invoice data for ID {inv.id} ({inv.invoice_number}) "
            f"using model '{used_model}'. Confidence: {result.confidence}. "
            f"Success: {result.is_success}."
        )
    )
    db.add(audit_entry)

    # Commit extraction and audit log (Invoice status is NOT modified)
    db.commit()

    return result


def get_invoice_extraction(
    db: Session,
    invoice_id: int
) -> InvoiceExtractionDetail:
    """
    Retrieves the most recent extraction record for an invoice.
    Raises 404 if no extraction has been performed yet.
    """
    extraction_record = (
        db.query(InvoiceExtraction)
        .filter(InvoiceExtraction.invoice_id == invoice_id)
        .order_by(InvoiceExtraction.created_at.desc())
        .first()
    )

    if not extraction_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No extraction found for invoice ID {invoice_id}. Run POST /invoices/{invoice_id}/extract first."
        )

    try:
        parsed_data = json.loads(extraction_record.extracted_json)
        extracted_invoice = ExtractedInvoice(**parsed_data)
    except Exception as e:
        extracted_invoice = ExtractedInvoice(
            is_success=False,
            error_message=f"Could not deserialize stored extraction JSON: {e}",
            confidence=extraction_record.confidence
        )

    return InvoiceExtractionDetail(
        id=extraction_record.id,
        invoice_id=extraction_record.invoice_id,
        model_name=extraction_record.model_name,
        confidence=extraction_record.confidence,
        created_at=extraction_record.created_at,
        data=extracted_invoice
    )


def check_invoice_matching(
    db: Session,
    invoice_id: int,
    who: str = "api_user"
) -> InvoiceCheckDetail:
    """
    Executes automated 3-way matching on the invoice, persists the result in
    the invoice_checks table, and writes an audit_logs entry.
    CRITICAL: Does NOT overwrite the existing invoice status yet.
    """
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice with ID {invoice_id} not found."
        )

    # Execute matching
    check_result: InvoiceCheckResult = perform_three_way_match(invoice_id, db)

    # Persist in invoice_checks table
    check_record = InvoiceCheck(
        invoice_id=inv.id,
        status=check_result.status,
        mistake_types=json.dumps(check_result.mistake_types),
        findings_json=json.dumps([f.model_dump() for f in check_result.findings]),
        difference_amount=check_result.difference_amount
    )
    db.add(check_record)

    # Create Audit Log entry
    audit_entry = AuditLog(
        who=who,
        action="invoice_check",
        details=(
            f"3-way matching check on Invoice ID {inv.id} ({inv.invoice_number}): "
            f"Status={check_result.status}, Mistakes={check_result.mistake_types}, "
            f"Difference=Rs. {check_result.difference_amount:,.2f}."
        )
    )
    db.add(audit_entry)

    # Commit check and audit log (Invoice status is NOT modified)
    db.commit()
    db.refresh(check_record)

    return InvoiceCheckDetail(
        id=check_record.id,
        invoice_id=check_record.invoice_id,
        status=check_record.status,
        mistake_types=check_result.mistake_types,
        difference_amount=check_record.difference_amount,
        findings=check_result.findings,
        created_at=check_record.created_at
    )


def get_invoice_check(
    db: Session,
    invoice_id: int
) -> InvoiceCheckDetail:
    """
    Retrieves the most recent 3-way matching check record for an invoice.
    Raises 404 if no check has been performed yet.
    """
    check_record = (
        db.query(InvoiceCheck)
        .filter(InvoiceCheck.invoice_id == invoice_id)
        .order_by(InvoiceCheck.created_at.desc())
        .first()
    )

    if not check_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No 3-way matching check found for invoice ID {invoice_id}. Run POST /invoices/{invoice_id}/check first."
        )

    try:
        raw_findings = json.loads(check_record.findings_json)
        findings = [MatchFinding(**f) for f in raw_findings]
        mistakes = json.loads(check_record.mistake_types)
    except Exception:
        findings = []
        mistakes = [check_record.mistake_types]

    return InvoiceCheckDetail(
        id=check_record.id,
        invoice_id=check_record.invoice_id,
        status=check_record.status,
        mistake_types=mistakes,
        difference_amount=check_record.difference_amount,
        findings=findings,
        created_at=check_record.created_at
    )


def investigate_invoice(
    db: Session,
    invoice_id: int,
    who: str = "api_user"
) -> InvestigationReport:
    """
    Executes the Investigation Agent LangGraph workflow for an invoice.
    Persists the report in invoice_investigations table.
    NOTE: Invoice status is NOT modified; the agent never decides to approve or pay.
    """
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice with ID {invoice_id} not found."
        )

    # Run LangGraph workflow
    report = run_investigation(invoice_id=invoice_id, db=db, who=who)

    # Persist report in invoice_investigations table
    investigation_record = InvoiceInvestigation(
        invoice_id=invoice_id,
        status=report.status,
        recommended_next_action=report.recommended_next_action,
        confidence=report.confidence,
        report_json=report.model_dump_json(),
        created_at=datetime.utcnow()
    )
    db.add(investigation_record)
    db.commit()
    db.refresh(investigation_record)

    return report


def get_invoice_investigation(
    db: Session,
    invoice_id: int
) -> InvestigationReport:
    """
    Retrieves the most recent Investigation Agent report for an invoice.
    Raises 404 if no investigation has been performed yet.
    """
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice with ID {invoice_id} not found."
        )

    investigation_record = (
        db.query(InvoiceInvestigation)
        .filter(InvoiceInvestigation.invoice_id == invoice_id)
        .order_by(InvoiceInvestigation.created_at.desc())
        .first()
    )

    if not investigation_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No investigation found for invoice ID {invoice_id}. Run POST /invoices/{invoice_id}/investigate first."
        )

    try:
        data = json.loads(investigation_record.report_json)
        return InvestigationReport(**data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse stored investigation report: {str(e)}"
        )

