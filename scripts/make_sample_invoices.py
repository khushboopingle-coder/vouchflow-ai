"""
Makes the two sample invoices in data/samples/ (fake data, for testing the automation).

They match the CSV templates of the "My data" page (purchase_orders.csv, goods_received_notes.csv,
contract_prices.csv): supplier "Acme Office Supplies", PO-1001, GRN-1001.

    sample_invoice_clean.pdf           everything matches            -> verified
    sample_invoice_price_mismatch.pdf  chair billed at Rs. 4,800     -> price mismatch (contract: Rs. 4,500)

Run:  python scripts/make_sample_invoices.py
Reads/writes only data/samples/. It does NOT touch any ground truth file.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
GST_RATE = 0.18


def rs(value: float) -> str:
    return f"Rs. {value:,.2f}"


def build_invoice(path: Path, invoice_no: str, items) -> dict:
    """items = [(description, qty, unit_price)]. Returns the totals (for the README / tests)."""
    subtotal = round(sum(q * p for _, q, p in items), 2)
    gst = round(subtotal * GST_RATE, 2)
    total = round(subtotal + gst, 2)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=f"Invoice {invoice_no}")
    story = [
        Paragraph("<b>Acme Office Supplies</b> TAX INVOICE", styles["Title"]),
        Paragraph("14 Market Road, Pune, Maharashtra 411001<br/>GSTIN: 27AACCA1234F1Z5<br/>"
                  "Email: billing@acme-office.example", styles["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph(f"Invoice No: {invoice_no}<br/>Invoice Date: 2026-01-22<br/>PO Number: PO-1001<br/>"
                  "Due Date: 2026-02-21", styles["Normal"]),
        Spacer(1, 4 * mm),
        Paragraph("Billed To: Sample Company Pvt Ltd, 1 Demo Street, Bengaluru 560100", styles["Normal"]),
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
              Paragraph(f"Subtotal: {rs(subtotal)}<br/>CGST (9%): {rs(gst / 2)}<br/>SGST (9%): {rs(gst / 2)}<br/>"
                        f"Total GST (18%): {rs(gst)}<br/><b>Grand Total: {rs(total)}</b>", styles["Normal"]),
              Spacer(1, 8 * mm),
              Paragraph("Terms &amp; Conditions: Payment is due as per the agreed supplier contract terms. "
                        "This is a FAKE sample invoice for testing VouchFlow AI.", styles["Italic"])]
    doc.build(story)
    return {"subtotal": subtotal, "gst": gst, "total": total}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    clean = build_invoice(
        OUT_DIR / "sample_invoice_clean.pdf", "INV-ACME-0001",
        [("Ergonomic Office Chair", 10, 4500.0), ("LED Desk Lamp", 5, 1200.0)],
    )
    mismatch = build_invoice(
        OUT_DIR / "sample_invoice_price_mismatch.pdf", "INV-ACME-0002",
        [("Ergonomic Office Chair", 10, 4800.0), ("LED Desk Lamp", 5, 1200.0)],
    )
    print("clean:   ", clean)
    print("mismatch:", mismatch)


if __name__ == "__main__":
    main()
