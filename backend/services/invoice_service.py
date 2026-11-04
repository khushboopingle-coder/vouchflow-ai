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
from backend.services import workspace_service, ai_usage_service


def list_invoices(
    db: Session,
    workspace_id: int,
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

    query = query.filter(Invoice.workspace_id == workspace_id)  # only this workspace
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


def get_invoice_by_id(db: Session, invoice_id: int, workspace_id: int) -> InvoiceDetail:
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
        .filter(Invoice.id == invoice_id, Invoice.workspace_id == workspace_id)
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
    workspace_id: int,
    who: str = "web_user"
) -> UploadResponse:
    """
    Saves an uploaded invoice PDF or image into the workspace's own folder
    (data/workspaces/<id>/invoices/), creates a new invoice row with status 'needs_review'
    and records an audit entry. The checks (type, size, real file signature) live in
    backend/services/upload_service.py; a bad file answers 400 with a clear message.
    """
    from backend.services import upload_service

    data = file.file.read() if hasattr(file.file, "read") else bytes(file.file)
    try:
        return upload_service.save_invoice_file(db, workspace_id, file.filename or "uploaded_invoice.pdf",
                                                data, who=who)
    except upload_service.UploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def extract_invoice_data(
    db: Session,
    invoice_id: int,
    workspace_id: int,
    who: str = "api_user"
) -> ExtractedInvoice:
    """
    Runs the InvoiceReader on the document associated with invoice_id,
    persists the extraction in the invoice_extractions table, and
    records an audit_logs entry.

    CRITICAL INSTRUCTION: Extraction does NOT alter invoice status.
    """
    inv = workspace_service.require_invoice(db, invoice_id, workspace_id)  # 404 if not ours

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
        workspace_id=workspace_id,
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
    invoice_id: int,
    workspace_id: int
) -> InvoiceExtractionDetail:
    """
    Retrieves the most recent extraction record for an invoice.
    Raises 404 if no extraction has been performed yet.
    """
    workspace_service.require_invoice(db, invoice_id, workspace_id)  # 404 if not ours
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
    workspace_id: int,
    who: str = "api_user"
) -> InvoiceCheckDetail:
    """
    Executes automated 3-way matching on the invoice, persists the result in
    the invoice_checks table, and writes an audit_logs entry.
    CRITICAL: Does NOT overwrite the existing invoice status yet.
    """
    inv = workspace_service.require_invoice(db, invoice_id, workspace_id)  # 404 if not ours

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
        workspace_id=workspace_id,
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
    invoice_id: int,
    workspace_id: int
) -> InvoiceCheckDetail:
    """
    Retrieves the most recent 3-way matching check record for an invoice.
    Raises 404 if no check has been performed yet.
    """
    workspace_service.require_invoice(db, invoice_id, workspace_id)  # 404 if not ours
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
    workspace_id: int,
    who: str = "api_user",
    use_ai: bool = False,
    user_id: Optional[int] = None,
) -> InvestigationReport:
    """
    Executes the Investigation Agent LangGraph workflow for an invoice.
    Persists the report in invoice_investigations table.
    Phase 3: the explanation is the template unless use_ai=True AND the user still has
    AI explanations left today (5/day); then Gemini may write it (template on any failure).
    NOTE: Invoice status is NOT modified; the agent never decides to approve or pay.
    """
    inv = workspace_service.require_invoice(db, invoice_id, workspace_id)  # 404 if not ours

    allow_llm = bool(use_ai and user_id is not None and ai_usage_service.may_use_ai(db, user_id))
    report = run_investigation(invoice_id=invoice_id, db=db, who=who, allow_llm=allow_llm)
    if allow_llm and report.llm_used:
        ai_usage_service.record_ai_use(db, user_id)  # count only real AI explanations

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
    invoice_id: int,
    workspace_id: int
) -> InvestigationReport:
    """
    Retrieves the most recent Investigation Agent report for an invoice.
    Raises 404 if no investigation has been performed yet.
    """
    inv = workspace_service.require_invoice(db, invoice_id, workspace_id)  # 404 if not ours

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

