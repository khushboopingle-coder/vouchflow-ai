"""
Makes the sample invoices in data/samples/ (FAKE data, for trying out the automation).

Two families:

1. Match the SAMPLE DATA (what a workspace with "sample data" contains). They reuse a real sample
   order - Patel Enterprises, PO-2026-0002, read from data/evaluation/mock_data.json - with NEW
   invoice numbers and dates, so they are not duplicates and the PO, goods received note and
   contract prices all exist:
       sample_invoice_clean.pdf           bills exactly what was ordered and received   -> verified
       sample_invoice_price_mismatch.pdf  Standing Desk billed Rs. 600 above contract   -> price mismatch

2. Match the CSV TEMPLATES of the "My data" page (a workspace built from the downloaded templates):
       template_invoice_clean.pdf           Acme Office Supplies, PO-1001               -> verified
       template_invoice_price_mismatch.pdf  chair billed at Rs. 4,800 (contract 4,500)   -> price mismatch

Run:  python scripts/make_sample_invoices.py
Reads data/evaluation/mock_data.json (read-only) and writes only data/samples/.
It does NOT touch any ground truth file.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "data" / "samples"
MOCK_DATA = BASE_DIR / "data" / "evaluation" / "mock_data.json"
GST_RATE = 0.18
SAMPLE_ORDER_ID = 2  # Patel Enterprises, PO-2026-0002 (a clean sample invoice with its PO, GRN and contract prices)

Item = Tuple[str, int, float]  # description, quantity, unit price

BUYER = "VouchFlow Technologies India Pvt Ltd, Ground Floor, Innovate Tech Park, Bengaluru 560100"

# What each sample PDF contains. "bump" raises one item's unit price (a planted price mismatch).
SAMPLE_DATA_CASES: Dict[str, dict] = {
    "sample_invoice_clean.pdf": dict(number="INV-DEMO-0001", date="2026-02-02", due="2026-03-04", bump={}),
    "sample_invoice_price_mismatch.pdf": dict(number="INV-DEMO-0002", date="2026-02-03", due="2026-03-05",
                                              bump={"Standing Desk 120cm": 600.0}),
}
TEMPLATE_SUPPLIER = dict(name="Acme Office Supplies", address="14 Market Road, Pune, Maharashtra 411001",
                         gstin="27AACCA1234F1Z5", email="billing@acme-office.example")
TEMPLATE_CASES: Dict[str, dict] = {
    "template_invoice_clean.pdf": dict(number="INV-ACME-0001", date="2026-01-22", due="2026-02-21",
                                       items=[("Ergonomic Office Chair", 10, 4500.0), ("LED Desk Lamp", 5, 1200.0)]),
    "template_invoice_price_mismatch.pdf": dict(number="INV-ACME-0002", date="2026-01-22", due="2026-02-21",
                                                items=[("Ergonomic Office Chair", 10, 4800.0),
                                                       ("LED Desk Lamp", 5, 1200.0)]),
}


def rs(value: float) -> str:
    return f"Rs. {value:,.2f}"


def load_sample_order() -> dict:
    """The real sample order (supplier, PO number and items) from the mock data."""
    data = json.loads(MOCK_DATA.read_text(encoding="utf-8"))
    invoice = next(i for i in data["invoices"] if i["id"] == SAMPLE_ORDER_ID)
    po = next(p for p in data["purchase_orders"] if p["id"] == invoice["po_id"])
    supplier = next(s for s in data["suppliers"] if s["id"] == invoice["supplier_id"])
    return {
        "supplier": dict(name=supplier["name"], address=supplier["address"], gstin=supplier["gstin"],
                         email=supplier["email"]),
        "po_number": po["po_number"],
        "items": [(i["item_name"], int(i["quantity"]), float(i["unit_price"])) for i in po["items"]],
    }


def sample_data_invoice(file_name: str) -> dict:
    """Everything printed on one of the sample-data PDFs (also used by the tests)."""
    case = SAMPLE_DATA_CASES[file_name]
    order = load_sample_order()
    items = [(name, qty, price + case["bump"].get(name, 0.0)) for name, qty, price in order["items"]]
    return dict(supplier=order["supplier"], po_number=order["po_number"], invoice_number=case["number"],
                invoice_date=case["date"], due_date=case["due"], items=items)


def totals(items: List[Item]) -> dict:
    subtotal = round(sum(q * p for _, q, p in items), 2)
    gst = round(subtotal * GST_RATE, 2)
    return {"subtotal": subtotal, "gst": gst, "total": round(subtotal + gst, 2)}


def render_invoice_pdf(path: Path, supplier: dict, invoice_number: str, invoice_date: str, due_date: str,
                       po_number: str, items: List[Item]) -> dict:
    """Writes a simple, clean tax-invoice PDF. Returns the totals."""
    t = totals(items)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=f"Invoice {invoice_number}")
    story = [
        Paragraph(f"<b>{supplier['name']}</b> TAX INVOICE", styles["Title"]),
        Paragraph(f"{supplier['address']}<br/>GSTIN: {supplier['gstin']}<br/>Email: {supplier['email']}",
                  styles["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph(f"Invoice No: {invoice_number}<br/>Invoice Date: {invoice_date}<br/>PO Number: {po_number}<br/>"
                  f"Due Date: {due_date}", styles["Normal"]),
        Spacer(1, 4 * mm),
        Paragraph(f"Billed To: {BUYER}", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    rows = [["#", "Item Description", "Qty", "Unit Price (Rs.)", "Amount (Rs.)"]]
    for n, (desc, qty, price) in enumerate(items, start=1):
        rows.append([str(n), desc, str(qty), rs(price), rs(qty * price)])
    table = Table(rows, colWidths=[10 * mm, 80 * mm, 15 * mm, 35 * mm, 35 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8C4B32")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFB2A5")),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    story += [table, Spacer(1, 6 * mm),
              Paragraph(f"Subtotal: {rs(t['subtotal'])}<br/>CGST (9%): {rs(t['gst'] / 2)}<br/>"
                        f"SGST (9%): {rs(t['gst'] / 2)}<br/>Total GST (18%): {rs(t['gst'])}<br/>"
                        f"<b>Grand Total: {rs(t['total'])}</b>", styles["Normal"]),
              Spacer(1, 8 * mm),
              Paragraph("Terms &amp; Conditions: Payment is due as per the agreed supplier contract terms. "
                        "This is a FAKE sample invoice for testing VouchFlow AI.", styles["Italic"])]
    doc.build(story)
    return t


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in SAMPLE_DATA_CASES:
        inv = sample_data_invoice(name)
        t = render_invoice_pdf(OUT_DIR / name, inv["supplier"], inv["invoice_number"], inv["invoice_date"],
                               inv["due_date"], inv["po_number"], inv["items"])
        print(f"{name:40s} {inv['supplier']['name']} / {inv['po_number']}  total {rs(t['total'])}")
    for name, case in TEMPLATE_CASES.items():
        t = render_invoice_pdf(OUT_DIR / name, TEMPLATE_SUPPLIER, case["number"], case["date"], case["due"],
                               "PO-1001", case["items"])
        print(f"{name:40s} {TEMPLATE_SUPPLIER['name']} / PO-1001  total {rs(t['total'])}")


if __name__ == "__main__":
    main()
