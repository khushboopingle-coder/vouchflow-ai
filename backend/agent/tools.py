"""
Read-Only Tools for VouchFlow AI Investigation Agent
====================================================
Mandatory Policy:
- All tools in this module are strictly READ-ONLY.
- No tool modifies database records.
- No tool releases payment, approves invoices, or sends emails.
- Decisions and numbers come strictly from existing system tools and records.
"""

import json
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session, joinedload

from backend.database.models import (
    Invoice,
    InvoiceItem,
    InvoiceExtraction,
    PurchaseOrder,
    POItem,
    GoodsReceivedNote,
    GRNItem,
    Supplier,
    Contract
)
from backend.database.schemas import ExtractedInvoice
from backend.tools.matcher import perform_three_way_match
from backend.tools.contract_finder import ask_contract


def get_invoice(invoice_id: int, db: Session) -> Dict[str, Any]:
    """
    Read-only tool: Retrieves invoice data, vendor profile, and line items.
    Does not mutate any database state.
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
        return {"error": f"Invoice with ID {invoice_id} not found", "found": False}

    items = [
        {
            "id": it.id,
            "item_name": it.item_name,
            "quantity": it.quantity,
            "unit_price": float(it.unit_price),
            "total_price": float(it.total_price)
        }
        for it in inv.items
    ]

    return {
        "found": True,
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "supplier_id": inv.supplier_id,
        "supplier_name": inv.supplier.name if inv.supplier else "Unknown Supplier",
        "supplier_gstin": inv.supplier.gstin if inv.supplier else None,
        "po_id": inv.po_id,
        "po_number": inv.purchase_order.po_number if inv.purchase_order else None,
        "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
        "due_date": str(inv.due_date) if inv.due_date else None,
        "subtotal": float(inv.subtotal),
        "tax_amount": float(inv.tax_amount),
        "grand_total": float(inv.grand_total),
        "file_path": inv.file_path,
        "status": inv.status,
        "items": items
    }


def get_extraction(invoice_id: int, db: Session) -> Dict[str, Any]:
    """
    Read-only tool: Retrieves existing AI/OCR extracted invoice record from invoice_extractions.
    Does not run any write operations.
    """
    record = (
        db.query(InvoiceExtraction)
        .filter(InvoiceExtraction.invoice_id == invoice_id)
        .order_by(InvoiceExtraction.created_at.desc())
        .first()
    )
    if not record:
        return {"found": False, "extracted": None}

    try:
        parsed_data = json.loads(record.extracted_json)
    except Exception:
        parsed_data = {"raw_text": record.extracted_json}

    return {
        "found": True,
        "id": record.id,
        "invoice_id": record.invoice_id,
        "confidence": float(record.confidence),
        "model_name": record.model_name,
        "created_at": str(record.created_at),
        "extracted": parsed_data
    }


def run_matcher(invoice_id: int, db: Session) -> Dict[str, Any]:
    """
    Read-only tool: Executes the deterministic 3-way matching engine in-memory.
    Does NOT save check records to invoice_checks table and does NOT alter invoice status.
    """
    match_result = perform_three_way_match(invoice_id=invoice_id, db=db)
    
    findings_list = [
        {
            "check_name": f.check_name,
            "status": f.status,
            "mistake_type": f.mistake_type,
            "message": f.message,
            "evidence": f.evidence,
            "difference_amount": float(f.difference_amount)
        }
        for f in match_result.findings
    ]

    return {
        "invoice_id": match_result.invoice_id,
        "status": match_result.status,
        "mistake_types": match_result.mistake_types,
        "difference_amount": float(match_result.difference_amount),
        "findings": findings_list
    }


def get_po_and_grn(invoice_id: int, db: Session) -> Dict[str, Any]:
    """
    Read-only tool: Fetches Purchase Order facts (authorized quantity and price)
    and Warehouse Goods Received Notes (GRN physical quantities and dates).
    """
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv or not inv.po_id:
        return {
            "has_po": False,
            "po": None,
            "grn_list": [],
            "items_summary": {}
        }

    po = (
        db.query(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.items),
            joinedload(PurchaseOrder.goods_received_notes).joinedload(GoodsReceivedNote.items)
        )
        .filter(PurchaseOrder.id == inv.po_id)
        .first()
    )
    if not po:
        return {
            "has_po": False,
            "po": None,
            "grn_list": [],
            "items_summary": {}
        }

    po_items = [
        {
            "item_name": it.item_name,
            "quantity": it.quantity,
            "unit_price": float(it.unit_price),
            "total_price": float(it.total_price)
        }
        for it in po.items
    ]

    grn_list = []
    grn_qty_by_item: Dict[str, int] = {}
    for grn in po.goods_received_notes:
        grn_items = []
        for git in grn.items:
            grn_items.append({
                "item_name": git.item_name,
                "quantity_received": git.quantity_received
            })
            grn_qty_by_item[git.item_name] = grn_qty_by_item.get(git.item_name, 0) + git.quantity_received

        grn_list.append({
            "grn_number": grn.grn_number,
            "received_date": str(grn.received_date),
            "received_by": grn.received_by,
            "remarks": grn.remarks,
            "items": grn_items
        })

    # Summary by item name
    items_summary = {}
    for it in po.items:
        items_summary[it.item_name] = {
            "po_authorized_quantity": it.quantity,
            "po_unit_price": float(it.unit_price),
            "grn_received_quantity": grn_qty_by_item.get(it.item_name, 0)
        }

    return {
        "has_po": True,
        "po": {
            "id": po.id,
            "po_number": po.po_number,
            "order_date": str(po.order_date),
            "status": po.status,
            "total_amount": float(po.total_amount),
            "items": po_items
        },
        "grn_list": grn_list,
        "items_summary": items_summary
    }


def search_contract(query: str, supplier_name: Optional[str] = None,
                    workspace_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Read-only tool: Uses the contract finder RAG tool to search master contracts
    for clauses governing prices, penalties, delivery, or terms.
    Strictly scopes search to supplier_name if provided, and (Phase 3) to the contracts
    of workspace_id when given.
    Does not modify data, send email, or execute financial transactions.
    """
    result = ask_contract(question=query, supplier_name=supplier_name, workspace_id=workspace_id)
    return {
        "query": query,
        "supplier_name": supplier_name,
        "answer": result.get("answer"),
        "source": result.get("source"),
        "sources": result.get("sources", []),
        "status": result.get("status"),
        "distance": result.get("distance"),
        "matched_clause": result.get("matched_clause")
    }

