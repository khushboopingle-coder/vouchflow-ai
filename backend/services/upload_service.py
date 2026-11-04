"""
Bring your own data (Phase 3)
=============================
Everything a user uploads lands in THEIR workspace only:
- invoices: PDF / PNG / JPG -> data/workspaces/<id>/invoices/ (+ an invoice row, 'needs_review')
- purchase orders and goods received notes: CSV (one row per line item)
- contract prices: CSV (agreed unit price per supplier + item; used by the price check)
- contract documents: TXT or PDF -> data/workspaces/<id>/contracts/*.txt (contract search)

Every file is checked before anything is saved (type, size, not empty, real file
signature). CSV imports are all-or-nothing: if any row is wrong, nothing is saved and
every problem is reported with its row number. Each upload marks the workspace as
"Live workspace" (has_user_data).
"""

import csv
import io
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.database.models import (
    AuditLog, Contract, GoodsReceivedNote, GRNItem, Invoice, POItem, PurchaseOrder, Supplier,
)
from backend.database.schemas import UploadResponse
from backend.services import workspace_service

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_CSV_ROWS = 5000
MAX_REPORTED_ERRORS = 25

# file signatures ("magic bytes") the content must start with
INVOICE_TYPES: Dict[str, Tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}
CONTRACT_TYPES = (".txt", ".pdf")

TEMPLATES: Dict[str, str] = {
    "purchase_orders.csv": (
        "po_number,supplier_name,order_date,item_name,quantity,unit_price\n"
        "PO-1001,Acme Office Supplies,2026-01-15,Ergonomic Office Chair,10,4500\n"
        "PO-1001,Acme Office Supplies,2026-01-15,LED Desk Lamp,5,1200\n"
    ),
    "goods_received_notes.csv": (
        "grn_number,po_number,received_date,item_name,quantity_received,received_by,remarks\n"
        "GRN-1001,PO-1001,2026-01-20,Ergonomic Office Chair,10,R. Kumar,All boxes intact\n"
        "GRN-1001,PO-1001,2026-01-20,LED Desk Lamp,5,R. Kumar,\n"
    ),
    "contract_prices.csv": (
        "supplier_name,item_name,agreed_unit_price,payment_terms_days\n"
        "Acme Office Supplies,Ergonomic Office Chair,4500,30\n"
        "Acme Office Supplies,LED Desk Lamp,1200,30\n"
    ),
}


class UploadError(ValueError):
    """A problem with an uploaded file. `errors` lists row-level problems for CSV files."""

    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []

    def __str__(self) -> str:
        if not self.errors:
            return self.message
        return self.message + " " + " | ".join(self.errors)


@dataclass
class ImportResult:
    kind: str
    created: int
    details: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------
def _safe_name(filename: str) -> Tuple[str, str]:
    """('Supplier_Invoice_7', '.pdf') - only letters, digits, - and _ in the stem."""
    path = Path(filename or "upload")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem).strip("_")[:80] or "upload"
    return stem, path.suffix.lower()


def _check_size(data: bytes) -> None:
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"The file is too large (maximum {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")


def _unique_path(folder: Path, stem: str, ext: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{stem}{ext}"
    counter = 1
    while target.exists():
        target = folder / f"{stem}_{counter}{ext}"
        counter += 1
    return target


def _relative(path: Path) -> str:
    """Path stored in the database, relative to the project root (data/workspaces/...)."""
    from backend.config import settings

    try:
        return path.resolve().relative_to(settings.data_path.parent.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _supplier(db: Session, workspace_id: int, name: str) -> Supplier:
    """The workspace's supplier with this name (case-insensitive), created if new."""
    clean = " ".join(name.split())
    for sup in db.query(Supplier).filter(Supplier.workspace_id == workspace_id).all():
        if sup.name.lower() == clean.lower():
            return sup
    sup = Supplier(name=clean, workspace_id=workspace_id)
    db.add(sup)
    db.flush()
    return sup


def _audit(db: Session, workspace_id: int, who: str, action: str, details: str) -> None:
    db.add(AuditLog(who=who, action=action, workspace_id=workspace_id, details=details))


# ---------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------
def save_invoice_file(db: Session, workspace_id: int, filename: str, data: bytes,
                      who: str = "web_user") -> UploadResponse:
    stem, ext = _safe_name(filename)
    if ext not in INVOICE_TYPES:
        raise UploadError(f"Invalid file type '{ext or 'none'}'. Allowed types: PDF, PNG, JPG.")
    _check_size(data)
    if not any(data.startswith(sig) for sig in INVOICE_TYPES[ext]):
        raise UploadError(f"This file does not look like a real {ext[1:].upper()} file. "
                          "Please upload the original invoice document.")

    target = _unique_path(workspace_service.workspace_dir(workspace_id) / "invoices", stem, ext)
    target.write_bytes(data)
    relative = _relative(target)

    invoice = Invoice(invoice_number=stem.upper(), supplier_id=None, po_id=None, invoice_date=date.today(),
                      subtotal=0.0, tax_amount=0.0, grand_total=0.0, file_path=relative,
                      status="needs_review", workspace_id=workspace_id)
    db.add(invoice)
    db.flush()
    _audit(db, workspace_id, who, "invoice_upload",
           f"Uploaded file '{filename}' saved to '{relative}'. Created Invoice ID {invoice.id} "
           "with status 'needs_review'.")
    db.commit()
    workspace_service.mark_user_data(db, workspace_id)
    return UploadResponse(message="Invoice uploaded successfully and queued for review.",
                          invoice_id=invoice.id, file_name=target.name, status=invoice.status,
                          file_path=relative)


# ---------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------
def _read_csv(data: bytes, required: List[str], what: str) -> List[Tuple[int, Dict[str, str]]]:
    _check_size(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadError(f"The {what} file is not a UTF-8 text CSV. In Excel use 'Save as -> CSV UTF-8'.")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in headers]
    if missing:
        raise UploadError(f"The {what} file is missing these columns: {', '.join(missing)}. "
                          "Download the template to see the expected columns.")
    rows = []
    for i, raw in enumerate(reader, start=2):  # row 1 is the header
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if any(row.values()):
            rows.append((i, row))
        if len(rows) > MAX_CSV_ROWS:
            raise UploadError(f"Too many rows (maximum {MAX_CSV_ROWS}).")
    if not rows:
        raise UploadError(f"The {what} file has no data rows.")
    return rows


def _need(row, col, n, errors) -> str:
    value = row.get(col, "")
    if not value:
        errors.append(f"row {n}: '{col}' is empty")
    return value


def _date(row, col, n, errors) -> Optional[date]:
    value = _need(row, col, n, errors)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"row {n}: '{col}' must look like 2026-01-31 (got '{value}')")
        return None


def _positive_int(row, col, n, errors) -> Optional[int]:
    value = _need(row, col, n, errors)
    if not value:
        return None
    try:
        number = int(float(value))
        if number <= 0 or float(value) != number:
            raise ValueError
        return number
    except ValueError:
        errors.append(f"row {n}: '{col}' must be a whole number above 0 (got '{value}')")
        return None


def _positive_money(row, col, n, errors) -> Optional[float]:
    value = _need(row, col, n, errors)
    if not value:
        return None
    try:
        amount = float(value.replace(",", ""))
        if amount <= 0:
            raise ValueError
        return round(amount, 2)
    except ValueError:
        errors.append(f"row {n}: '{col}' must be an amount above 0 (got '{value}')")
        return None


def _fail_if(errors: List[str], what: str) -> None:
    if errors:
        shown = errors[:MAX_REPORTED_ERRORS]
        more = len(errors) - len(shown)
        if more:
            shown.append(f"... and {more} more")
        raise UploadError(f"Nothing was imported: the {what} file has {len(errors)} problem(s).", shown)


# ---------------------------------------------------------------------
# Purchase orders / GRNs / contract prices (CSV)
# ---------------------------------------------------------------------
def import_purchase_orders(db: Session, workspace_id: int, data: bytes, who: str = "web_user") -> ImportResult:
    rows = _read_csv(data, ["po_number", "supplier_name", "order_date", "item_name", "quantity", "unit_price"],
                     "purchase orders")
    errors: List[str] = []
    orders: "OrderedDict[str, dict]" = OrderedDict()
    for n, row in rows:
        po_number = _need(row, "po_number", n, errors)
        supplier = _need(row, "supplier_name", n, errors)
        order_date = _date(row, "order_date", n, errors)
        item = _need(row, "item_name", n, errors)
        qty = _positive_int(row, "quantity", n, errors)
        price = _positive_money(row, "unit_price", n, errors)
        if not po_number:
            continue
        po = orders.setdefault(po_number, {"supplier": supplier, "date": order_date, "items": [], "row": n})
        if supplier and po["supplier"] and supplier.lower() != po["supplier"].lower():
            errors.append(f"row {n}: {po_number} has two different suppliers ('{po['supplier']}' and '{supplier}')")
        if order_date and po["date"] and order_date != po["date"]:
            errors.append(f"row {n}: {po_number} has two different order dates")
        if item and qty and price:
            po["items"].append((item, qty, price))
    existing = {p.po_number for p in db.query(PurchaseOrder.po_number)
                .filter(PurchaseOrder.workspace_id == workspace_id, PurchaseOrder.po_number.in_(list(orders)))}
    for po_number in existing:
        errors.append(f"row {orders[po_number]['row']}: {po_number} already exists in your workspace")
    _fail_if(errors, "purchase orders")

    for po_number, po in orders.items():
        sup = _supplier(db, workspace_id, po["supplier"])
        total = round(sum(q * p for _, q, p in po["items"]), 2)
        record = PurchaseOrder(po_number=po_number, supplier_id=sup.id, order_date=po["date"], status="issued",
                               total_amount=total, workspace_id=workspace_id)
        db.add(record)
        db.flush()
        for item, qty, price in po["items"]:
            db.add(POItem(po_id=record.id, item_name=item, quantity=qty, unit_price=price,
                          total_price=round(qty * price, 2)))
    _audit(db, workspace_id, who, "upload_purchase_orders", f"Imported {len(orders)} purchase orders from CSV.")
    db.commit()
    workspace_service.mark_user_data(db, workspace_id)
    return ImportResult("purchase orders", len(orders), list(orders))


def import_grns(db: Session, workspace_id: int, data: bytes, who: str = "web_user") -> ImportResult:
    rows = _read_csv(data, ["grn_number", "po_number", "received_date", "item_name", "quantity_received"],
                     "goods received notes")
    errors: List[str] = []
    pos = {p.po_number: p for p in db.query(PurchaseOrder).filter(PurchaseOrder.workspace_id == workspace_id)}
    grns: "OrderedDict[str, dict]" = OrderedDict()
    for n, row in rows:
        grn_number = _need(row, "grn_number", n, errors)
        po_number = _need(row, "po_number", n, errors)
        received = _date(row, "received_date", n, errors)
        item = _need(row, "item_name", n, errors)
        qty = _positive_int(row, "quantity_received", n, errors)
        if po_number and po_number not in pos:
            errors.append(f"row {n}: purchase order {po_number} is not in your workspace (upload it first)")
        if not grn_number:
            continue
        grn = grns.setdefault(grn_number, {"po": po_number, "date": received, "items": [], "row": n,
                                           "by": row.get("received_by", ""), "remarks": row.get("remarks", "")})
        if po_number and grn["po"] and po_number != grn["po"]:
            errors.append(f"row {n}: {grn_number} points at two different purchase orders")
        if item and qty:
            grn["items"].append((item, qty))
    existing = {g.grn_number for g in db.query(GoodsReceivedNote.grn_number)
                .filter(GoodsReceivedNote.workspace_id == workspace_id, GoodsReceivedNote.grn_number.in_(list(grns)))}
    for grn_number in existing:
        errors.append(f"row {grns[grn_number]['row']}: {grn_number} already exists in your workspace")
    _fail_if(errors, "goods received notes")

    for grn_number, grn in grns.items():
        record = GoodsReceivedNote(grn_number=grn_number, po_id=pos[grn["po"]].id, received_date=grn["date"],
                                   received_by=grn["by"] or None, remarks=grn["remarks"] or None,
                                   workspace_id=workspace_id)
        db.add(record)
        db.flush()
        for item, qty in grn["items"]:
            db.add(GRNItem(grn_id=record.id, item_name=item, quantity_received=qty))
    _audit(db, workspace_id, who, "upload_goods_received_notes", f"Imported {len(grns)} GRNs from CSV.")
    db.commit()
    workspace_service.mark_user_data(db, workspace_id)
    return ImportResult("goods received notes", len(grns), list(grns))


def import_contract_prices(db: Session, workspace_id: int, data: bytes, who: str = "web_user") -> ImportResult:
    rows = _read_csv(data, ["supplier_name", "item_name", "agreed_unit_price"], "contract prices")
    errors: List[str] = []
    prices = []
    for n, row in rows:
        supplier = _need(row, "supplier_name", n, errors)
        item = _need(row, "item_name", n, errors)
        price = _positive_money(row, "agreed_unit_price", n, errors)
        terms = 30
        if row.get("payment_terms_days"):
            terms = _positive_int(row, "payment_terms_days", n, errors) or 30
        if supplier and item and price:
            prices.append((supplier, item, price, terms))
    _fail_if(errors, "contract prices")

    for supplier, item, price, terms in prices:
        sup = _supplier(db, workspace_id, supplier)
        db.add(Contract(supplier_id=sup.id, item_name=item, agreed_unit_price=price, payment_terms_days=terms,
                        terms_text=f"Agreed price for {item}: Rs. {price:,.2f} (uploaded)", workspace_id=workspace_id))
    _audit(db, workspace_id, who, "upload_contract_prices", f"Imported {len(prices)} contract prices from CSV.")
    db.commit()
    workspace_service.mark_user_data(db, workspace_id)
    return ImportResult("contract prices", len(prices))


# ---------------------------------------------------------------------
# Contract documents (TXT / PDF) for contract search
# ---------------------------------------------------------------------
def _pdf_text(data: bytes) -> str:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:
        raise UploadError("The PDF could not be read. Is it damaged or password-protected?")


def save_contract_document(db: Session, workspace_id: int, filename: str, data: bytes,
                           supplier_name: str, who: str = "web_user") -> ImportResult:
    stem, ext = _safe_name(filename)
    if ext not in CONTRACT_TYPES:
        raise UploadError(f"Invalid file type '{ext or 'none'}'. Contracts must be TXT or PDF.")
    supplier_name = " ".join((supplier_name or "").split())
    if not supplier_name:
        raise UploadError("Please enter the supplier this contract belongs to.")
    _check_size(data)
    if ext == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise UploadError("This file does not look like a real PDF file.")
        text = _pdf_text(data)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise UploadError("The text file is not UTF-8 text.")
    if len(text.strip()) < 20:
        raise UploadError("No readable text was found in the contract (a scanned image PDF cannot be searched).")

    if not re.search(r"Supplier:\s*\S", text):
        text = f"Supplier: {supplier_name}\n\n{text}"
    from backend.tools import contract_finder

    target = _unique_path(contract_finder.workspace_contracts_dir(workspace_id), stem, ".txt")
    target.write_text(text, encoding="utf-8")
    _supplier(db, workspace_id, supplier_name)
    _audit(db, workspace_id, who, "upload_contract_document",
           f"Contract '{filename}' for {supplier_name} added to contract search.")
    db.commit()
    contract_finder.invalidate_workspace_store(workspace_id)  # rebuilt on the next search
    workspace_service.mark_user_data(db, workspace_id)
    return ImportResult("contract document", 1, [target.name])
