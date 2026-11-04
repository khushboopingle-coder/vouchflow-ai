"""
3-Way Matching Engine for VouchFlow AI
======================================
Automated rule-based verification comparing:
1. Supplier Invoice (extracted AI/OCR data)
2. Purchase Order (internal approved PO & line items)
3. Goods Received Note (warehouse physical receipts)
4. Master Supplier Contract (agreed unit pricing and terms)

Rule Checks:
- Check 1: Price Verification (Invoice unit price vs BOTH PO and Contract)
- Check 2: Quantity Verification (Invoiced quantity vs GRN physical receipt and PO limit)
- Check 3: Mathematical Totals (Subtotal, 18% GST, Grand Total with commercial rounding tolerance)
- Check 4: Missing Purchase Order (No PO reference or PO not found in database)
- Check 5: Duplicate Detection (Duplicate invoice number scoped to supplier, same supplier/date/amount, or file hash)

Priority Order for Compound Mistakes:
  missing_po > duplicate_invoice > price_mismatch > quantity_mismatch > wrong_total

Status Policy:
  - If missing_po is present -> status is 'needs_review'
  - Else if any discrepancy detected -> status is 'mismatch_detected'
  - Else -> status is 'verified'

This module is 100% deterministic Python logic (0% LLM).
"""

import os
import json
import hashlib
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy.orm import Session

from backend.config import settings
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
from backend.database.schemas import (
    ExtractedInvoice,
    ExtractedItem,
    MatchFinding,
    InvoiceCheckResult
)

# Priority order for primary mistake selection on compound mistakes
PRIORITY_ORDER = [
    "missing_po",
    "duplicate_invoice",
    "price_mismatch",
    "quantity_mismatch",
    "wrong_total"
]


def normalize_str(s: Any) -> str:
    """Normalizes string for robust, fair comparison."""
    if s is None:
        return ""
    clean = str(s).lower().strip()
    for suffix in ["pvt ltd", "pvt. ltd.", "ltd", "enterprises", "traders", "supplies", "commercials", "solutions"]:
        clean = clean.replace(suffix, "")
    return "".join(c for c in clean if c.isalnum())


def normalize_inv_num(s: Any) -> str:
    """Normalizes invoice numbers by lowercasing and stripping punctuation and whitespace."""
    if s is None:
        return ""
    return "".join(c for c in str(s).lower() if c.isalnum())


def compute_file_hash(file_path: Optional[str]) -> Optional[str]:
    """Computes SHA-256 hash of a file for content duplicate detection."""
    if not file_path:
        return None
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(settings.DATA_DIR).parent / file_path
    if not p.exists() or not p.is_file():
        return None

    hasher = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def find_matching_key(target: str, candidates: Dict[str, Any]) -> Optional[str]:
    """Finds best matching key in a dictionary by exact normalized match or substring."""
    norm_t = normalize_str(target)
    if not norm_t:
        return None
    # 1. Exact normalized match
    for k in candidates:
        if normalize_str(k) == norm_t:
            return k
    # 2. Substring match
    for k in candidates:
        norm_k = normalize_str(k)
        if norm_k and (norm_k in norm_t or norm_t in norm_k):
            return k
    return None


def perform_three_way_match(
    invoice_id: int,
    db: Session,
    extracted_override: Optional[ExtractedInvoice] = None
) -> InvoiceCheckResult:
    """
    Executes automated 3-way matching for an invoice against PO, GRN, and Contract.

    Parameters:
        invoice_id: Primary key of the invoice in the invoices table.
        db: Active SQLAlchemy database session.
        extracted_override: Optional in-memory ExtractedInvoice (useful for testing).

    Returns:
        InvoiceCheckResult with status ('verified', 'mismatch_detected', 'needs_review'),
        mistake_types list (primary mistake first, followed by any additional mistakes),
        total discrepancy amount, and detailed findings with evidence.
    """
    # 1. Fetch Invoice record
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise ValueError(f"Invoice with ID {invoice_id} not found in database.")

    # 2. Fetch Extracted Invoice data
    extracted: Optional[ExtractedInvoice] = extracted_override
    if extracted is None:
        ext_record = (
            db.query(InvoiceExtraction)
            .filter(InvoiceExtraction.invoice_id == invoice_id)
            .order_by(InvoiceExtraction.created_at.desc())
            .first()
        )
        if ext_record:
            try:
                parsed = json.loads(ext_record.extracted_json)
                extracted = ExtractedInvoice(**parsed)
            except Exception as e:
                print(f"[Matcher] Warning: could not parse extraction for invoice {invoice_id}: {e}")

    # Fallback to database line items if extraction is missing
    if extracted is None:
        db_items = [
            ExtractedItem(
                name=it.item_name,
                quantity=it.quantity,
                unit_price=it.unit_price,
                total_price=it.total_price
            )
            for it in invoice.items
        ]
        po_record_fb = db.query(PurchaseOrder).filter(PurchaseOrder.id == invoice.po_id).first() if invoice.po_id else None
        extracted = ExtractedInvoice(
            vendor=invoice.supplier.name if invoice.supplier else None,
            invoice_number=invoice.invoice_number,
            invoice_date=str(invoice.invoice_date) if invoice.invoice_date else None,
            po_reference=po_record_fb.po_number if po_record_fb else None,
            items=db_items,
            subtotal=invoice.subtotal,
            gst_amount=invoice.tax_amount,
            grand_total=invoice.grand_total,
            confidence=1.0,
            is_success=True
        )

    findings: List[MatchFinding] = []
    mistake_types: List[str] = []
    total_difference_amount = 0.0

    # -------------------------------------------------------------------------
    # Guard Check: Extraction Success and Confidence
    # -------------------------------------------------------------------------
    if not extracted.is_success or (extracted.confidence is not None and extracted.confidence < 0.70):
        findings.append(MatchFinding(
            check_name="extraction",
            status="warning",
            mistake_type="needs_review",
            message=f"Invoice extraction incomplete or low confidence ({extracted.confidence or 0.0:.2f}). Flagged for manual review.",
            evidence={
                "is_success": extracted.is_success,
                "confidence": extracted.confidence,
                "error_message": extracted.error_message
            },
            difference_amount=0.0
        ))
        mistake_types.append("needs_review")
        return InvoiceCheckResult(
            invoice_id=invoice_id,
            status="needs_review",
            mistake_types=mistake_types,
            difference_amount=0.0,
            findings=findings
        )

    # -------------------------------------------------------------------------
    # Check 5: Duplicate Invoice Detection (Scoped to same supplier)
    # -------------------------------------------------------------------------
    norm_cur_num = normalize_inv_num(extracted.invoice_number or invoice.invoice_number)
    current_supplier_id = invoice.supplier_id
    current_supplier_name = invoice.supplier.name if invoice.supplier else (extracted.vendor or "")
    current_file_hash = compute_file_hash(invoice.file_path)
    cur_po_ref = normalize_inv_num(extracted.po_reference or (invoice.purchase_order.po_number if invoice.purchase_order else ""))

    # In AP accounting, an invoice is a duplicate if an earlier invoice was already submitted
    # with the same number from the SAME supplier (or billing the same PO), identical supplier+date+amount, or identical file hash.
    # Workspaces (Phase 2): only invoices of the SAME workspace can be duplicates of each other.
    earlier_query = db.query(Invoice).filter(Invoice.id < invoice_id)
    if invoice.workspace_id is not None:
        earlier_query = earlier_query.filter(Invoice.workspace_id == invoice.workspace_id)
    all_earlier_invoices = earlier_query.all()

    for other in all_earlier_invoices:
        norm_other_num = normalize_inv_num(other.invoice_number)
        other_supplier_name = other.supplier.name if other.supplier else ""
        other_po_ref = normalize_inv_num(other.purchase_order.po_number if other.purchase_order else "")

        # Verify supplier match
        is_same_supplier = False
        if current_supplier_id is not None and other.supplier_id is not None:
            is_same_supplier = (other.supplier_id == current_supplier_id)
        elif current_supplier_name and other_supplier_name:
            is_same_supplier = (normalize_str(current_supplier_name) == normalize_str(other_supplier_name))

        cur_grand_total = float(extracted.grand_total or invoice.grand_total or 0.0)
        cur_subtotal = float(extracted.subtotal or invoice.subtotal or 0.0)
        is_same_total = bool(abs(other.grand_total - cur_grand_total) <= 0.01 and abs(other.subtotal - cur_subtotal) <= 0.01)

        # Condition 1: Same invoice number from the SAME supplier, or identical invoice resubmission with matching totals
        is_same_num = bool(norm_cur_num and norm_cur_num == norm_other_num and (is_same_supplier or is_same_total))

        # Condition 2: Same supplier, amount, and date (with rounding tolerance)
        other_inv_date = str(other.invoice_date) if other.invoice_date else ""
        cur_inv_date = str(extracted.invoice_date or invoice.invoice_date or "")

        is_same_supplier_amt_date = (
            is_same_supplier
            and abs(other.grand_total - cur_grand_total) <= settings.ROUNDING_TOLERANCE_RS
            and (other_inv_date == cur_inv_date and other_inv_date != "")
        )

        # Condition 3: Identical binary file hash
        is_same_hash = False
        if current_file_hash:
            other_hash = compute_file_hash(other.file_path)
            if other_hash and other_hash == current_file_hash:
                is_same_hash = True

        if is_same_num or is_same_supplier_amt_date or is_same_hash:
            reasons = []
            if is_same_num:
                reasons.append(f"same invoice number '{other.invoice_number}' from same supplier")
            if is_same_supplier_amt_date:
                reasons.append(f"identical supplier, date ({cur_inv_date}), and grand total (Rs. {cur_grand_total:,.2f})")
            if is_same_hash:
                reasons.append("identical binary file hash")

            findings.append(MatchFinding(
                check_name="duplicate_invoice",
                status="fail",
                mistake_type="duplicate_invoice",
                message=f"Duplicate invoice detected: matches earlier Invoice ID #{other.id} ({', '.join(reasons)}).",
                evidence={
                    "current_invoice_id": invoice_id,
                    "duplicate_with_invoice_id": other.id,
                    "matched_number": other.invoice_number,
                    "matched_total": other.grand_total,
                    "matched_supplier_id": other.supplier_id,
                    "matched_supplier_name": other_supplier_name,
                    "identical_file_hash": is_same_hash
                },
                difference_amount=cur_grand_total
            ))
            if "duplicate_invoice" not in mistake_types:
                mistake_types.append("duplicate_invoice")
            total_difference_amount += cur_grand_total
            break

    # -------------------------------------------------------------------------
    # Check 4: Missing Purchase Order
    # -------------------------------------------------------------------------
    extracted_po_ref = (extracted.po_reference or "").strip()
    po_record: Optional[PurchaseOrder] = None

    if extracted_po_ref:
        po_query = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == extracted_po_ref)
        if invoice.workspace_id is not None:  # a PO number is only looked up in the same workspace
            po_query = po_query.filter(PurchaseOrder.workspace_id == invoice.workspace_id)
        po_record = po_query.first()

    if not po_record and invoice.po_id:
        po_record = db.query(PurchaseOrder).filter(PurchaseOrder.id == invoice.po_id).first()

    if not po_record:
        findings.append(MatchFinding(
            check_name="missing_po",
            status="fail",
            mistake_type="missing_po",
            message=f"Missing Purchase Order: Invoice does not reference a valid purchase order (stated PO: '{extracted_po_ref or 'None'}').",
            evidence={
                "extracted_po_reference": extracted_po_ref or None,
                "database_po_id": invoice.po_id
            },
            difference_amount=0.0
        ))
        if "missing_po" not in mistake_types:
            mistake_types.append("missing_po")
    else:
        findings.append(MatchFinding(
            check_name="missing_po",
            status="pass",
            mistake_type=None,
            message=f"Valid Purchase Order linked: {po_record.po_number}.",
            evidence={"po_number": po_record.po_number, "po_id": po_record.id},
            difference_amount=0.0
        ))

    # -------------------------------------------------------------------------
    # Check 3: Mathematical Totals Reconciliation (with Rounding Tolerance)
    # -------------------------------------------------------------------------
    items = extracted.items or []
    calc_subtotal = round(sum(float(it.quantity) * float(it.unit_price) for it in items), 2)
    expected_tax = round(calc_subtotal * 0.18, 2)
    expected_grand_total = round(calc_subtotal + expected_tax, 2)

    invoiced_subtotal = float(extracted.subtotal) if extracted.subtotal is not None else calc_subtotal
    invoiced_tax = float(extracted.gst_amount) if extracted.gst_amount is not None else expected_tax
    invoiced_grand_total = float(extracted.grand_total) if extracted.grand_total is not None else expected_grand_total

    # Verify mathematics
    math_discrepancy = round(abs(invoiced_grand_total - expected_grand_total), 2)
    subtotal_diff = round(abs(invoiced_subtotal - calc_subtotal), 2)
    tax_diff = round(abs(invoiced_tax - expected_tax), 2)
    max_math_diff = max(math_discrepancy, subtotal_diff, tax_diff)

    rounding_tolerance = float(settings.ROUNDING_TOLERANCE_RS)

    if max_math_diff > rounding_tolerance:
        findings.append(MatchFinding(
            check_name="totals",
            status="fail",
            mistake_type="wrong_total",
            message=(
                f"Mathematical calculation error: Line items and 18% GST sum to Rs. {expected_grand_total:,.2f}, "
                f"but invoice total states Rs. {invoiced_grand_total:,.2f} "
                f"(discrepancy: Rs. {math_discrepancy:,.2f} exceeds rounding tolerance of Rs. {rounding_tolerance:,.2f})."
            ),
            evidence={
                "calculated_subtotal": calc_subtotal,
                "invoiced_subtotal": invoiced_subtotal,
                "expected_tax_18pct": expected_tax,
                "invoiced_tax": invoiced_tax,
                "expected_grand_total": expected_grand_total,
                "invoiced_grand_total": invoiced_grand_total,
                "difference": math_discrepancy,
                "rounding_tolerance": rounding_tolerance
            },
            difference_amount=math_discrepancy
        ))
        if "wrong_total" not in mistake_types:
            mistake_types.append("wrong_total")
        total_difference_amount += math_discrepancy
    elif max_math_diff > 0.01:
        # Rounding difference accepted within configured tolerance
        findings.append(MatchFinding(
            check_name="totals",
            status="pass",
            mistake_type=None,
            message=(
                f"Invoice mathematics acceptable: rounding difference accepted "
                f"(discrepancy of Rs. {max_math_diff:,.2f} is within rounding tolerance of Rs. {rounding_tolerance:,.2f})."
            ),
            evidence={
                "calculated_subtotal": calc_subtotal,
                "invoiced_subtotal": invoiced_subtotal,
                "expected_tax_18pct": expected_tax,
                "invoiced_tax": invoiced_tax,
                "expected_grand_total": expected_grand_total,
                "invoiced_grand_total": invoiced_grand_total,
                "rounding_difference": max_math_diff,
                "rounding_tolerance": rounding_tolerance
            },
            difference_amount=0.0
        ))
    else:
        findings.append(MatchFinding(
            check_name="totals",
            status="pass",
            mistake_type=None,
            message=f"Invoice mathematics reconciled cleanly: Subtotal Rs. {invoiced_subtotal:,.2f} + 18% GST Rs. {invoiced_tax:,.2f} = Grand Total Rs. {invoiced_grand_total:,.2f}.",
            evidence={
                "subtotal": invoiced_subtotal,
                "gst_18pct": invoiced_tax,
                "grand_total": invoiced_grand_total
            },
            difference_amount=0.0
        ))

    # -------------------------------------------------------------------------
    # Lookups for Checks 1 & 2 (Only if PO is present)
    # -------------------------------------------------------------------------
    if po_record:
        # Load PO line items
        po_items_map: Dict[str, POItem] = {it.item_name: it for it in po_record.items}

        # Load GRN line items for this PO
        grn_qty_map: Dict[str, int] = {}
        for grn in po_record.goods_received_notes:
            for grn_it in grn.items:
                grn_qty_map[grn_it.item_name] = grn_qty_map.get(grn_it.item_name, 0) + grn_it.quantity_received

        # Load Contract agreements for this supplier
        supplier_id = po_record.supplier_id or invoice.supplier_id
        contracts = db.query(Contract).filter(Contract.supplier_id == supplier_id).all() if supplier_id else []
        contract_price_map: Dict[str, float] = {c.item_name: c.agreed_unit_price for c in contracts}

        price_mismatch_detected = False
        quantity_mismatch_detected = False

        # ---------------------------------------------------------------------
        # Check 1: Price Verification (Invoice unit price vs BOTH PO and Contract)
        # ---------------------------------------------------------------------
        for it in items:
            inv_unit_price = float(it.unit_price)
            item_name = it.name

            # Match PO item
            po_matched_key = find_matching_key(item_name, po_items_map)
            po_item = po_items_map.get(po_matched_key) if po_matched_key else None
            po_unit_price = float(po_item.unit_price) if po_item else None

            # Match Contract item
            contract_matched_key = find_matching_key(item_name, contract_price_map)
            contract_unit_price = float(contract_price_map.get(contract_matched_key)) if contract_matched_key else None

            # Compare against BOTH PO price and Contract price
            po_price_differs = False
            contract_price_differs = False

            if po_unit_price is not None and abs(inv_unit_price - po_unit_price) > 0.01:
                po_price_differs = True
            if contract_unit_price is not None and abs(inv_unit_price - contract_unit_price) > 0.01:
                contract_price_differs = True

            if po_price_differs or contract_price_differs:
                # Determine which one differed
                differing_sources = []
                if po_price_differs and contract_price_differs:
                    differing_sources.append(f"both PO (Rs. {po_unit_price:,.2f}) and Contract (Rs. {contract_unit_price:,.2f})")
                elif po_price_differs:
                    differing_sources.append(f"agreed PO price (Rs. {po_unit_price:,.2f}) [matches Contract Rs. {contract_unit_price:,.2f}]")
                elif contract_price_differs:
                    differing_sources.append(f"master Contract price (Rs. {contract_unit_price:,.2f}) [matches PO Rs. {po_unit_price:,.2f}]")

                max_unit_diff = max(
                    abs(inv_unit_price - po_unit_price) if po_unit_price is not None else 0.0,
                    abs(inv_unit_price - contract_unit_price) if contract_unit_price is not None else 0.0
                )
                item_diff_total = round(max_unit_diff * float(it.quantity) * 1.18, 2)

                findings.append(MatchFinding(
                    check_name="price",
                    status="fail",
                    mistake_type="price_mismatch",
                    message=(
                        f"Price mismatch on '{item_name}': Invoiced unit price is Rs. {inv_unit_price:,.2f}, "
                        f"which differs from {', '.join(differing_sources)}."
                    ),
                    evidence={
                        "item_name": item_name,
                        "invoiced_unit_price": inv_unit_price,
                        "po_unit_price": po_unit_price,
                        "contract_unit_price": contract_unit_price,
                        "quantity": it.quantity,
                        "po_price_differs": po_price_differs,
                        "contract_price_differs": contract_price_differs,
                        "line_discrepancy_with_tax": item_diff_total
                    },
                    difference_amount=item_diff_total
                ))
                price_mismatch_detected = True
                total_difference_amount += item_diff_total
            else:
                findings.append(MatchFinding(
                    check_name="price",
                    status="pass",
                    mistake_type=None,
                    message=f"Unit price verified for '{item_name}': Rs. {inv_unit_price:,.2f} matches both PO and Contract.",
                    evidence={
                        "item_name": item_name,
                        "invoiced_unit_price": inv_unit_price,
                        "po_unit_price": po_unit_price,
                        "contract_unit_price": contract_unit_price
                    },
                    difference_amount=0.0
                ))

        if price_mismatch_detected and "price_mismatch" not in mistake_types:
            mistake_types.append("price_mismatch")

        # ---------------------------------------------------------------------
        # Check 2: Quantity Verification (Invoice vs GRN physical receipt AND PO limit)
        # ---------------------------------------------------------------------
        for it in items:
            inv_qty = int(it.quantity)
            item_name = it.name

            # PO authorized quantity
            po_matched_key = find_matching_key(item_name, po_items_map)
            po_item = po_items_map.get(po_matched_key) if po_matched_key else None
            po_qty = int(po_item.quantity) if po_item else None

            # Warehouse GRN physical receipt
            grn_matched_key = find_matching_key(item_name, grn_qty_map)
            received_qty = grn_qty_map.get(grn_matched_key) if grn_matched_key else None

            # 1. Partial delivery / GRN shortage check: invoiced quantity exceeds physical warehouse receipt
            grn_shortage = bool(received_qty is not None and inv_qty > received_qty)

            # 2. Over-delivery check: invoiced quantity exceeds PO authorized quantity (even if GRN accepted delivery)
            po_overdelivery = bool(po_qty is not None and inv_qty > po_qty)

            if grn_shortage or po_overdelivery:
                reasons = []
                if grn_shortage and po_overdelivery:
                    reasons.append(f"exceeds both PO authorized quantity ({po_qty}) and GRN physical receipt ({received_qty})")
                elif grn_shortage:
                    reasons.append(f"exceeds warehouse GRN confirmed receipt of {received_qty} units (partial delivery billed in full)")
                elif po_overdelivery:
                    reasons.append(f"exceeds PO authorized limit of {po_qty} units (unauthorized over-delivery)")

                excess_units = max(
                    inv_qty - received_qty if received_qty is not None else 0,
                    inv_qty - po_qty if po_qty is not None else 0
                )
                overbilled_amount = round(excess_units * float(it.unit_price) * 1.18, 2)

                findings.append(MatchFinding(
                    check_name="quantity",
                    status="fail",
                    mistake_type="quantity_mismatch",
                    message=f"Quantity mismatch on '{item_name}': Invoiced {inv_qty} units {', '.join(reasons)}.",
                    evidence={
                        "item_name": item_name,
                        "invoiced_quantity": inv_qty,
                        "po_authorized_quantity": po_qty,
                        "grn_received_quantity": received_qty,
                        "excess_units": excess_units,
                        "overbilled_amount_with_tax": overbilled_amount
                    },
                    difference_amount=overbilled_amount
                ))
                quantity_mismatch_detected = True
                total_difference_amount += overbilled_amount
            elif received_qty is not None:
                findings.append(MatchFinding(
                    check_name="quantity",
                    status="pass",
                    mistake_type=None,
                    message=f"Quantity verified for '{item_name}': {inv_qty} units invoiced <= {received_qty} units received on GRN and <= {po_qty} PO units.",
                    evidence={
                        "item_name": item_name,
                        "invoiced_quantity": inv_qty,
                        "po_authorized_quantity": po_qty,
                        "grn_received_quantity": received_qty
                    },
                    difference_amount=0.0
                ))
            else:
                findings.append(MatchFinding(
                    check_name="quantity",
                    status="warning",
                    mistake_type=None,
                    message=f"No corresponding GRN item found for '{item_name}'.",
                    evidence={"item_name": item_name, "invoiced_quantity": inv_qty},
                    difference_amount=0.0
                ))

        if quantity_mismatch_detected and "quantity_mismatch" not in mistake_types:
            mistake_types.append("quantity_mismatch")

    # -------------------------------------------------------------------------
    # Compound Mistake Priority Ordering
    # Priority hierarchy: missing_po > duplicate_invoice > price_mismatch > quantity_mismatch > wrong_total
    # -------------------------------------------------------------------------
    ordered_mistakes: List[str] = []
    for prio in PRIORITY_ORDER:
        if prio in mistake_types and prio not in ordered_mistakes:
            ordered_mistakes.append(prio)

    # Append any unexpected mistake types not in the standard list
    for m in mistake_types:
        if m not in ordered_mistakes:
            ordered_mistakes.append(m)

    mistake_types = ordered_mistakes

    # -------------------------------------------------------------------------
    # Overall Status Determination
    # Policy:
    # 1. If missing_po is present -> 'needs_review'
    # 2. Else if any discrepancies detected -> 'mismatch_detected'
    # 3. Else -> 'verified'
    # -------------------------------------------------------------------------
    if "missing_po" in mistake_types:
        overall_status = "needs_review"
    elif any(m in {"price_mismatch", "quantity_mismatch", "wrong_total", "duplicate_invoice"} for m in mistake_types):
        overall_status = "mismatch_detected"
    elif not mistake_types:
        overall_status = "verified"
        mistake_types = ["none"]
    else:
        overall_status = "mismatch_detected"

    return InvoiceCheckResult(
        invoice_id=invoice_id,
        status=overall_status,
        mistake_types=mistake_types,
        difference_amount=round(total_difference_amount, 2),
        findings=findings
    )
