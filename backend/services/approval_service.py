"""
Approval Service for VouchFlow AI (Phase 8)
===========================================
Records HUMAN approve / reject decisions on investigated invoices.

Safety rules (enforced here, so the API, dashboard and n8n all follow them):
1. Only a named human may decide. Agent / system / automation names are refused.
2. An invoice must have an investigation report before anyone can decide.
3. A rejection always needs a note.
4. Approving needs a note when the agent did NOT recommend
   'ready_for_human_approval' (the human is overriding the agent's advice).
5. Each investigation report can be decided only once. Re-investigate to decide again.
6. Every decision is written to audit_logs.

The original invoices.status column is NOT changed by a decision.
"""

import json
from datetime import datetime
from typing import List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.database.models import AuditLog, Invoice, InvoiceDecision, InvoiceInvestigation
from backend.database.schemas import ApprovalQueueItem, DecisionCreate, DecisionRead

# Names that belong to software, not people. Checked case-insensitively.
BLOCKED_DECIDER_NAMES = {
    "investigation_agent",
    "agent",
    "system",
    "api_user",
    "portal_user",
    "n8n",
    "automation",
    "bot",
    "llm",
    "gemini",
}
# Any name containing one of these words is also refused.
BLOCKED_DECIDER_WORDS = ("agent", "bot", "n8n", "automation", "system", "llm")

MIN_NOTE_LENGTH = 5


def _is_blocked_name(name: str) -> bool:
    lowered = name.strip().lower()
    if lowered in BLOCKED_DECIDER_NAMES:
        return True
    return any(word in lowered for word in BLOCKED_DECIDER_WORDS)


def _latest_investigation(db: Session, invoice_id: int):
    return (
        db.query(InvoiceInvestigation)
        .filter(InvoiceInvestigation.invoice_id == invoice_id)
        .order_by(InvoiceInvestigation.created_at.desc(), InvoiceInvestigation.id.desc())
        .first()
    )


def _to_read(decision: InvoiceDecision, invoice_number: str = None) -> DecisionRead:
    return DecisionRead(
        id=decision.id,
        invoice_id=decision.invoice_id,
        investigation_id=decision.investigation_id,
        decision=decision.decision,
        decided_by=decision.decided_by,
        note=decision.note,
        agent_recommendation=decision.agent_recommendation,
        created_at=decision.created_at,
        invoice_number=invoice_number,
    )


def record_decision(db: Session, invoice_id: int, payload: DecisionCreate) -> DecisionRead:
    """Validates and saves a human decision, then writes an audit log."""
    decided_by = payload.decided_by.strip()
    note = (payload.note or "").strip()

    # Rule 1: humans only
    if len(decided_by) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please enter your full name.")
    if _is_blocked_name(decided_by):
        db.add(AuditLog(
            who=decided_by,
            action="decision_blocked_non_human",
            details=json.dumps({"invoice_id": invoice_id, "decision": payload.decision}),
        ))
        db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"'{decided_by}' looks like a software account. Only a named finance person may approve or reject invoices.",
        )

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Invoice with ID {invoice_id} not found.")

    # Rule 2: must be investigated first
    investigation = _latest_investigation(db, invoice_id)
    if not investigation:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Invoice {invoice_id} has not been investigated yet. Run POST /invoices/{invoice_id}/investigate first.",
        )

    # Rule 5: one decision per investigation report
    already = (
        db.query(InvoiceDecision)
        .filter(InvoiceDecision.investigation_id == investigation.id)
        .first()
    )
    if already:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This investigation was already {already.decision} by {already.decided_by}. "
            "Run a new investigation if the invoice needs a fresh decision.",
        )

    # Rules 3 and 4: notes
    agent_recommendation = investigation.recommended_next_action
    if payload.decision == "rejected" and len(note) < MIN_NOTE_LENGTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Please write a short reason when rejecting an invoice.",
        )
    if (
        payload.decision == "approved"
        and agent_recommendation != "ready_for_human_approval"
        and len(note) < MIN_NOTE_LENGTH
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"The agent recommended '{agent_recommendation}'. Please write a note explaining why you are approving anyway.",
        )

    decision = InvoiceDecision(
        invoice_id=invoice_id,
        investigation_id=investigation.id,
        decision=payload.decision,
        decided_by=decided_by,
        note=note or None,
        agent_recommendation=agent_recommendation,
        created_at=datetime.utcnow(),
    )
    db.add(decision)

    # Rule 6: audit trail
    db.add(AuditLog(
        who=decided_by,
        action=f"human_decision_{payload.decision}",
        details=json.dumps({
            "invoice_id": invoice_id,
            "invoice_number": invoice.invoice_number,
            "investigation_id": investigation.id,
            "agent_recommendation": agent_recommendation,
            "note": note or None,
        }),
    ))
    db.commit()
    db.refresh(decision)
    return _to_read(decision, invoice.invoice_number)


def get_approval_queue(db: Session) -> List[ApprovalQueueItem]:
    """Invoices whose latest investigation report has no human decision yet."""
    investigations = (
        db.query(InvoiceInvestigation)
        .order_by(InvoiceInvestigation.created_at.desc(), InvoiceInvestigation.id.desc())
        .all()
    )
    latest_by_invoice = {}
    for inv_record in investigations:
        latest_by_invoice.setdefault(inv_record.invoice_id, inv_record)

    decided_ids = {row[0] for row in db.query(InvoiceDecision.investigation_id).all()}

    queue: List[ApprovalQueueItem] = []
    for invoice_id, record in latest_by_invoice.items():
        if record.id in decided_ids:
            continue
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            continue
        queue.append(ApprovalQueueItem(
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            supplier_name=invoice.supplier.name if invoice.supplier else None,
            grand_total=invoice.grand_total,
            investigation_id=record.id,
            investigation_status=record.status,
            recommended_next_action=record.recommended_next_action,
            confidence=record.confidence,
            investigated_at=record.created_at,
        ))
    queue.sort(key=lambda item: item.investigated_at)  # oldest first
    return queue


def list_decisions(db: Session, limit: int = 50) -> List[DecisionRead]:
    """Most recent human decisions, newest first."""
    rows = (
        db.query(InvoiceDecision, Invoice.invoice_number)
        .join(Invoice, Invoice.id == InvoiceDecision.invoice_id)
        .order_by(InvoiceDecision.created_at.desc(), InvoiceDecision.id.desc())
        .limit(limit)
        .all()
    )
    return [_to_read(decision, number) for decision, number in rows]
