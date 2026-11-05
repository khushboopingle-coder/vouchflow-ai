"""
Ingest for automation (Phase 4)
===============================
One call turns an invoice file into a checked, investigated invoice in ONE workspace:

    save the file -> extract (Gemini, if a key is configured) -> fill the invoice row
    -> 3-way match -> Investigation Agent (template explanation) -> JSON answer

It NEVER approves or pays anything: the answer always says a person must decide in the
dashboard. Extraction needs a Gemini key on the server; without one the invoice is still
saved, matched and investigated, but lands in "needs_review" (extraction incomplete).
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, NamedTuple, Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.models import (
    Invoice, InvoiceCheck, InvoiceInvestigation, InvoiceItem, PurchaseOrder, Supplier,
)
from backend.database.schemas import ExtractedInvoice, IngestResponse, InvoiceSummary
from backend.services import invoice_service, upload_service, workspace_service

logger = logging.getLogger("vouchflow.reader")
if not logger.handlers and not logging.getLogger().handlers:
    # no logging set up by the host program (e.g. Streamlit): print warnings to the terminal
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y")
HUMAN_APPROVAL_NOTE = "A person must review and approve this invoice in the dashboard. Nothing was approved or paid."

ACTION_TEXT = {
    "ready_for_human_approval": "Ready for human approval",
    "ask_supplier_for_clarification": "Ask the supplier for clarification",
    "reject_and_escalate": "Reject and escalate",
    "needs_human_review": "Needs human review",
}


def dashboard_link(invoice_id: int) -> str:
    return f"{settings.DASHBOARD_URL.rstrip('/')}/investigation?invoice={int(invoice_id)}"


def _money(value: Optional[float]) -> str:
    return f"Rs. {float(value or 0):,.2f}"


def _parse_date(text: Optional[str]) -> Optional[date]:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime((text or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def apply_extraction_to_invoice(db: Session, invoice: Invoice, data: ExtractedInvoice) -> None:
    """Fills the invoice row from a successful extraction (number, dates, totals, line items,
    supplier and PO when they already exist in THIS workspace). The status is never changed."""
    if data.invoice_number:
        invoice.invoice_number = data.invoice_number.strip()[:100]
    if parsed := _parse_date(data.invoice_date):
        invoice.invoice_date = parsed
    if parsed := _parse_date(data.due_date):
        invoice.due_date = parsed
    if data.subtotal is not None:
        invoice.subtotal = float(data.subtotal)
    if data.gst_amount is not None:
        invoice.tax_amount = float(data.gst_amount)
    if data.grand_total is not None:
        invoice.grand_total = float(data.grand_total)

    if data.vendor:
        wanted = " ".join(data.vendor.split()).lower()
        for sup in db.query(Supplier).filter(Supplier.workspace_id == invoice.workspace_id).all():
            name = sup.name.lower()
            if name == wanted or name in wanted or wanted in name:
                invoice.supplier_id = sup.id
                break
    if data.po_reference:
        po = (db.query(PurchaseOrder)
              .filter(PurchaseOrder.workspace_id == invoice.workspace_id,
                      PurchaseOrder.po_number == data.po_reference.strip())
              .first())
        if po is not None:
            invoice.po_id = po.id
            invoice.supplier_id = invoice.supplier_id or po.supplier_id

    if data.items:
        db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).delete(synchronize_session=False)
        for item in data.items:
            qty = max(1, int(item.quantity or 1))
            unit = float(item.unit_price or 0.0)
            db.add(InvoiceItem(invoice_id=invoice.id, item_name=(item.name or "Item")[:255], quantity=qty,
                               unit_price=unit,
                               total_price=float(item.total_price if item.total_price is not None else qty * unit)))
    db.commit()


def _mistakes(codes: List[str]) -> List[str]:
    return [c for c in (codes or []) if c and c != "none"]


def _pretty(code: str) -> str:
    return code.replace("_", " ")


def build_summary_text(invoice_number: str, supplier: Optional[str], grand_total: float, status: str,
                       mistakes: List[str], difference: float, action: Optional[str], link: str) -> str:
    """A short message for alerts (Telegram, email)."""
    who = f" from {supplier}" if supplier else ""
    head = f"Invoice {invoice_number}{who} - {_money(grand_total)}"
    if status == "verified":
        lines = [f"VERIFIED: {head}", "All checks passed."]
    else:
        label = "NEEDS REVIEW" if status == "needs_review" else "MISMATCH"
        lines = [f"{label}: {head}"]
        if mistakes:
            lines.append("Problems: " + ", ".join(_pretty(m) for m in mistakes)
                         + (f" (difference {_money(difference)})" if difference else ""))
    if action:
        lines.append("Recommended: " + ACTION_TEXT.get(action, action))
    lines.append("A person must approve it: " + link)
    return "\n".join(lines)


def _latest(db: Session, model, invoice_id: int):
    return (db.query(model).filter(model.invoice_id == invoice_id)
            .order_by(model.created_at.desc(), model.id.desc()).first())


def build_summary(db: Session, workspace_id: int, invoice_id: int) -> InvoiceSummary:
    """Short summary for alerts. 404 (via require_invoice) for an invoice of another workspace."""
    import json

    invoice = workspace_service.require_invoice(db, invoice_id, workspace_id)
    check = _latest(db, InvoiceCheck, invoice_id)
    report = _latest(db, InvoiceInvestigation, invoice_id)
    status = check.status if check else invoice.status
    mistakes = _mistakes(json.loads(check.mistake_types)) if check else []
    difference = float(check.difference_amount) if check else 0.0
    action = report.recommended_next_action if report else None
    link = dashboard_link(invoice.id)
    supplier = invoice.supplier.name if invoice.supplier else None
    return InvoiceSummary(
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        supplier_name=supplier,
        grand_total=float(invoice.grand_total or 0.0),
        status=status,
        mistakes=mistakes,
        difference_amount=difference,
        recommended_action=action,
        dashboard_link=link,
        human_approval_required=True,
        text=build_summary_text(invoice.invoice_number, supplier, float(invoice.grand_total or 0.0),
                                status, mistakes, difference, action, link),
    )


class ReadOutcome(NamedTuple):
    """Result of trying to read one saved invoice. `reason` explains a failure in plain words."""
    ok: bool
    confidence: float = 0.0
    reason: str = ""


def read_saved_invoice(db: Session, workspace_id: int, invoice_id: int, who: str = "api_user") -> ReadOutcome:
    """
    Reads a saved invoice with the AI reader and fills the invoice row. NEVER raises and NEVER
    changes the status (a failed read simply leaves the invoice in 'needs_review' for a person).
    On failure the reason is returned AND logged (terminal), so it is never silent.
    """
    try:
        extracted = invoice_service.extract_invoice_data(db=db, invoice_id=invoice_id,
                                                         workspace_id=workspace_id, who=who)
        if not extracted.is_success:
            reason = (extracted.error_message or "the reader returned no data").strip()
            logger.warning("Could not read invoice %s (workspace %s): %s", invoice_id, workspace_id, reason)
            return ReadOutcome(False, float(extracted.confidence or 0.0), reason)
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).one()
        apply_extraction_to_invoice(db, invoice, extracted)
        return ReadOutcome(True, float(extracted.confidence or 0.0))
    except Exception as exc:  # includes HTTPException (e.g. file missing)
        db.rollback()
        reason = str(getattr(exc, "detail", None) or exc) or type(exc).__name__
        logger.warning("Could not read invoice %s (workspace %s): %s: %s",
                       invoice_id, workspace_id, type(exc).__name__, reason)
        return ReadOutcome(False, 0.0, reason)


def ingest_invoice(db: Session, workspace_id: int, filename: str, data: bytes,
                   who: str = "api_key") -> IngestResponse:
    """The whole pipeline for one file. Raises upload_service.UploadError for a bad file."""
    saved = upload_service.save_invoice_file(db, workspace_id, filename, data, who=who)
    invoice_id = saved.invoice_id

    # extraction trouble must not stop the check: the matcher flags the invoice for review
    outcome = read_saved_invoice(db, workspace_id, invoice_id, who=who)
    extraction_ok, confidence = outcome.ok, outcome.confidence

    invoice_service.check_invoice_matching(db=db, invoice_id=invoice_id, workspace_id=workspace_id, who=who)
    invoice_service.investigate_invoice(db=db, invoice_id=invoice_id, workspace_id=workspace_id, who=who,
                                        use_ai=False)  # template explanation: automation never spends AI quota

    summary = build_summary(db, workspace_id, invoice_id)
    report = _latest(db, InvoiceInvestigation, invoice_id)
    return IngestResponse(
        invoice_id=summary.invoice_id,
        invoice_number=summary.invoice_number,
        supplier_name=summary.supplier_name,
        grand_total=summary.grand_total,
        status=summary.status,
        mistakes=summary.mistakes,
        difference_amount=summary.difference_amount,
        recommended_action=summary.recommended_action or "needs_human_review",
        extraction_ok=extraction_ok,
        extraction_confidence=confidence,
        extraction_error=None if extraction_ok else (outcome.reason or None),
        dashboard_link=summary.dashboard_link,
        human_approval_required=True,
        message=HUMAN_APPROVAL_NOTE,
        text=summary.text,
    )
