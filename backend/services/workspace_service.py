"""
Workspace Service for VouchFlow AI (Phase 2)
============================================
Every user owns one private workspace. All business rows carry a workspace_id
(suppliers, contracts, purchase orders, GRNs, invoices, decisions, audit logs);
child rows (line items, extractions, checks, investigations) follow their parent.

- ensure_sample_workspace(): the shared "sample" workspace with the demo data
- load_sample_data(): copy the sample data into a user's workspace (new ids, links kept)
- clear_workspace_data() / delete_workspace(): remove a workspace's data / the workspace
- require_invoice(): the single gate every service uses before touching an invoice
- Phase 3: workspace_dir() for uploaded files (git-ignored), is_demo() for the
  "Demo data" vs "Live workspace" label, mark_user_data() after any upload
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from backend.config import settings

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import (
    AIUsage,
    APIKey,
    AuditLog,
    Contract,
    GoodsReceivedNote,
    GRNItem,
    Invoice,
    InvoiceCheck,
    InvoiceDecision,
    InvoiceExtraction,
    InvoiceInvestigation,
    InvoiceItem,
    POItem,
    PurchaseOrder,
    Supplier,
    User,
    Workspace,
)

SAMPLE_WORKSPACE_NAME = "sample"


# ---------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------
def ensure_sample_workspace(db: Session) -> int:
    """Returns the id of the "sample" workspace, creating it if needed."""
    ws = db.query(Workspace).filter(Workspace.is_sample.is_(True)).order_by(Workspace.id).first()
    if ws is None:
        ws = Workspace(name=SAMPLE_WORKSPACE_NAME, is_sample=True, created_at=datetime.utcnow())
        db.add(ws)
        db.commit()
        db.refresh(ws)
    return ws.id


def get_workspace(db: Session, workspace_id: int) -> Optional[Workspace]:
    return db.query(Workspace).filter(Workspace.id == workspace_id).first()


def get_user_workspace(db: Session, user_id: int) -> Optional[Workspace]:
    return db.query(Workspace).filter(Workspace.owner_user_id == user_id).first()


def require_invoice(db: Session, invoice_id: int, workspace_id: int) -> Invoice:
    """The invoice, but ONLY if it belongs to this workspace. Otherwise 404 — the same
    answer as for an invoice that does not exist, so other workspaces stay invisible."""
    inv = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.workspace_id == workspace_id)
        .first()
    )
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Invoice with ID {invoice_id} not found.")
    return inv


def workspace_invoice_count(db: Session, workspace_id: int) -> int:
    return db.query(Invoice).filter(Invoice.workspace_id == workspace_id).count()


# ---------------------------------------------------------------------
# Phase 3: files, demo flag
# ---------------------------------------------------------------------
def workspace_dir(workspace_id: int) -> Path:
    """Folder for this workspace's own files: invoices/ and contracts/ (git-ignored)."""
    return settings.data_path / "workspaces" / str(int(workspace_id))


def is_demo(ws: Optional[Workspace]) -> bool:
    """True only while the workspace holds the sample copy and nothing the user added."""
    return bool(ws and ws.sample_loaded and not ws.has_user_data)


def mark_user_data(db: Session, workspace_id: int) -> None:
    ws = get_workspace(db, workspace_id)
    if ws is not None and not ws.has_user_data:
        ws.has_user_data = True
        db.commit()


def _forget_workspace_files(workspace_id: int) -> None:
    """Drops the workspace's in-memory contract index and its uploaded files."""
    try:
        from backend.tools import contract_finder

        contract_finder.invalidate_workspace_store(workspace_id)
    except Exception:
        pass
    shutil.rmtree(workspace_dir(workspace_id), ignore_errors=True)


# ---------------------------------------------------------------------
# Clearing / deleting
# ---------------------------------------------------------------------
def clear_workspace_data(db: Session, workspace_id: int, keep_audit_logs: bool = True,
                         allow_sample: bool = False) -> None:
    """Deletes all business data of one workspace (children before parents, so it also
    works with PostgreSQL's foreign key rules). Other workspaces are never touched."""
    ws = get_workspace(db, workspace_id)
    if ws is None:
        return
    if ws.is_sample and not allow_sample:
        raise ValueError("The sample workspace can only be changed by the seeder.")

    invoice_ids = select(Invoice.id).where(Invoice.workspace_id == workspace_id).scalar_subquery()
    grn_ids = select(GoodsReceivedNote.id).where(GoodsReceivedNote.workspace_id == workspace_id).scalar_subquery()
    po_ids = select(PurchaseOrder.id).where(PurchaseOrder.workspace_id == workspace_id).scalar_subquery()

    db.query(InvoiceDecision).filter(InvoiceDecision.workspace_id == workspace_id).delete(synchronize_session=False)
    for child in (InvoiceInvestigation, InvoiceCheck, InvoiceExtraction, InvoiceItem):
        db.query(child).filter(child.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
    db.query(Invoice).filter(Invoice.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(GRNItem).filter(GRNItem.grn_id.in_(grn_ids)).delete(synchronize_session=False)
    db.query(GoodsReceivedNote).filter(GoodsReceivedNote.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(POItem).filter(POItem.po_id.in_(po_ids)).delete(synchronize_session=False)
    db.query(PurchaseOrder).filter(PurchaseOrder.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(Contract).filter(Contract.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(Supplier).filter(Supplier.workspace_id == workspace_id).delete(synchronize_session=False)
    if not keep_audit_logs:
        db.query(AuditLog).filter(AuditLog.workspace_id == workspace_id).delete(synchronize_session=False)
    if not ws.is_sample:
        ws.sample_loaded = False
        ws.has_user_data = False
    db.commit()
    if not ws.is_sample:
        _forget_workspace_files(workspace_id)


def delete_workspace(db: Session, workspace_id: int, delete_owner: bool = True) -> None:
    """Deletes a user's workspace with ALL its data, audit logs included, and (by default)
    the owner's login account. The sample workspace can never be deleted this way."""
    ws = get_workspace(db, workspace_id)
    if ws is None:
        return
    if ws.is_sample:
        raise ValueError("The sample workspace cannot be deleted.")
    owner_id = ws.owner_user_id
    clear_workspace_data(db, workspace_id, keep_audit_logs=False)
    db.query(APIKey).filter(APIKey.workspace_id == workspace_id).delete(synchronize_session=False)
    db.delete(ws)
    db.commit()
    if delete_owner and owner_id is not None:
        db.query(AIUsage).filter(AIUsage.user_id == owner_id).delete(synchronize_session=False)
        db.query(User).filter(User.id == owner_id).delete(synchronize_session=False)
        db.commit()


# ---------------------------------------------------------------------
# Copying the sample data
# ---------------------------------------------------------------------
def _clone(row, **overrides):
    """Copy of an ORM row without its id (the database gives the copy a new one)."""
    cls = type(row)
    data = {c.key: getattr(row, c.key) for c in cls.__table__.columns if c.key != "id"}
    data.update(overrides)
    return cls(**data)


def load_sample_data(db: Session, workspace_id: int, who: str = "system") -> Dict[str, Dict[int, int]]:
    """
    Replaces this workspace's data with a fresh copy of the sample workspace:
    suppliers, contracts, POs (+items), GRNs (+items), invoices (+items) and the saved
    extractions, checks and investigation reports. Decisions are NOT copied: a person
    must decide again. Returns {"invoices": {sample_id: new_id}, ...} for each table.
    """
    sample_id = ensure_sample_workspace(db)
    if workspace_id == sample_id:
        raise ValueError("Cannot copy the sample workspace into itself.")
    clear_workspace_data(db, workspace_id, keep_audit_logs=True)
    try:
        maps = _copy_sample_rows(db, sample_id, workspace_id, who)
    except Exception:
        db.rollback()  # never leave a half-copied workspace behind
        raise
    return maps


def _copy_sample_rows(db: Session, sample_id: int, workspace_id: int, who: str) -> Dict[str, Dict[int, int]]:
    maps: Dict[str, Dict[int, int]] = {k: {} for k in ("suppliers", "purchase_orders", "grns", "invoices")}

    def copy_rows(model, key, **fk_maps):
        for row in db.query(model).filter(model.workspace_id == sample_id).order_by(model.id).all():
            overrides = {"workspace_id": workspace_id}
            for column, mapping in fk_maps.items():
                value = getattr(row, column)
                overrides[column] = maps[mapping].get(value) if value is not None else None
            new = _clone(row, **overrides)
            db.add(new)
            db.flush()
            if key:
                maps[key][row.id] = new.id

    copy_rows(Supplier, "suppliers")
    copy_rows(Contract, None, supplier_id="suppliers")
    copy_rows(PurchaseOrder, "purchase_orders", supplier_id="suppliers")
    copy_rows(GoodsReceivedNote, "grns", po_id="purchase_orders")
    copy_rows(Invoice, "invoices", supplier_id="suppliers", po_id="purchase_orders")

    # children follow their parents
    for item in db.query(POItem).filter(POItem.po_id.in_(list(maps["purchase_orders"]))).all():
        db.add(_clone(item, po_id=maps["purchase_orders"][item.po_id]))
    for item in db.query(GRNItem).filter(GRNItem.grn_id.in_(list(maps["grns"]))).all():
        db.add(_clone(item, grn_id=maps["grns"][item.grn_id]))
    inv_map = maps["invoices"]
    for model in (InvoiceItem, InvoiceExtraction, InvoiceCheck):
        for row in db.query(model).filter(model.invoice_id.in_(list(inv_map))).all():
            db.add(_clone(row, invoice_id=inv_map[row.invoice_id]))
    for row in db.query(InvoiceInvestigation).filter(InvoiceInvestigation.invoice_id.in_(list(inv_map))).all():
        report = json.loads(row.report_json)
        report["invoice_id"] = inv_map[row.invoice_id]
        db.add(_clone(row, invoice_id=inv_map[row.invoice_id], report_json=json.dumps(report)))

    db.add(AuditLog(
        who=who, action="sample_data_loaded", workspace_id=workspace_id,
        details=f"Copied {len(inv_map)} sample invoices into this workspace.",
    ))
    ws = get_workspace(db, workspace_id)
    ws.sample_loaded = True       # "Demo data" until the user adds something
    ws.has_user_data = False
    db.commit()
    return maps
