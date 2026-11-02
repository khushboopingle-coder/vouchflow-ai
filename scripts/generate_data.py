"""
Fake Data Generator for VouchFlow AI
====================================
Generates:
1. 8 Supplier master contracts saved to data/contracts/
2. 50 Realistic Invoice PDF files using ReportLab saved to data/invoices/
3. 3-way matching records (Purchase Orders, Goods Received Notes, Contracts)
4. Seed dataset in data/evaluation/mock_data.json for database seeding
5. Evaluation answer sheet saved to data/evaluation/ground_truth.csv

Features:
- Fixed random seed for 100% reproducible data.
- Indian business names and addresses.
- Uses "Rs." (not the rupee symbol) to prevent font encoding issues in ReportLab.
- Exact GST breakdown (9% CGST + 9% SGST = 18%).
- 70% clean invoices (35 invoices) and 30% planted mistakes (15 invoices):
    1. price_mismatch
    2. quantity_mismatch
    3. wrong_total
    4. duplicate_invoice
    5. missing_po
"""

import os
import sys
import json
import random
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Set fixed random seed for repeatability
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# Output directory paths
DATA_DIR = BASE_DIR / "data"
INVOICES_DIR = DATA_DIR / "invoices"
CONTRACTS_DIR = DATA_DIR / "contracts"
EVAL_DIR = DATA_DIR / "evaluation"

# Ensure all target directories exist
for directory in [INVOICES_DIR, CONTRACTS_DIR, EVAL_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------------------
# 1. Master Definitions: 8 Indian Suppliers & 10 Products
# -------------------------------------------------------------
SUPPLIERS = [
    {
        "id": 1,
        "name": "Sharma Traders Pvt Ltd",
        "email": "billing@sharmatraders.in",
        "phone": "+91 98110 12345",
        "address": "12 Chandni Chowk Commercial Complex, Delhi 110006",
        "gstin": "07AAAAA1234A1Z5",
        "payment_terms_days": 30
    },
    {
        "id": 2,
        "name": "Patel Enterprises",
        "email": "accounts@patelenterprise.in",
        "phone": "+91 98250 23456",
        "address": "45 Ashram Road, Navrangpura, Ahmedabad, Gujarat 380009",
        "gstin": "24BBBBB5678B2Z6",
        "payment_terms_days": 30
    },
    {
        "id": 3,
        "name": "Reddy Logistics & Supplies",
        "email": "finance@reddylogistics.in",
        "phone": "+91 98480 34567",
        "address": "88 Cyber Towers, Madhapur, Hyderabad, Telangana 500081",
        "gstin": "36CCCCC9012C3Z7",
        "payment_terms_days": 45
    },
    {
        "id": 4,
        "name": "Gupta Stationery & Tech",
        "email": "orders@guptastationery.in",
        "phone": "+91 98390 45678",
        "address": "23 Hazratganj Plaza, Lucknow, Uttar Pradesh 226001",
        "gstin": "09DDDDD3456D4Z8",
        "payment_terms_days": 30
    },
    {
        "id": 5,
        "name": "Nair Office Solutions",
        "email": "billing@nairoffice.in",
        "phone": "+91 98470 56789",
        "address": "14 MG Road, Ernakulam, Kochi, Kerala 682016",
        "gstin": "32EEEEE7890E5Z9",
        "payment_terms_days": 30
    },
    {
        "id": 6,
        "name": "Chatterjee Commercials",
        "email": "sales@chatterjeecomm.in",
        "phone": "+91 98310 67890",
        "address": "5 Park Street, Chowringhee, Kolkata, West Bengal 700016",
        "gstin": "19FFFFF1234F6Z1",
        "payment_terms_days": 45
    },
    {
        "id": 7,
        "name": "Mehta Industrial Goods",
        "email": "invoices@mehtaindustrial.in",
        "phone": "+91 98200 78901",
        "address": "77 Nariman Point, Marine Drive, Mumbai, Maharashtra 400021",
        "gstin": "27GGGGG5678G7Z2",
        "payment_terms_days": 30
    },
    {
        "id": 8,
        "name": "Singh & Sons Equipment",
        "email": "accounts@singhandsons.in",
        "phone": "+91 98140 89012",
        "address": "19 Focal Point, GT Road, Ludhiana, Punjab 141010",
        "gstin": "03HHHHH9012H8Z3",
        "payment_terms_days": 60
    }
]

PRODUCTS = [
    {"name": "Ergonomic Office Chair", "agreed_price": 4500.0},
    {"name": "Standing Desk 120cm", "agreed_price": 12000.0},
    {"name": "Wireless Keyboard & Mouse Combo", "agreed_price": 1500.0},
    {"name": "24-inch IPS Monitor", "agreed_price": 8500.0},
    {"name": "High-Speed USB-C Dock", "agreed_price": 3200.0},
    {"name": "A4 Copier Paper (Box of 5 Reams)", "agreed_price": 1100.0},
    {"name": "Cat6 Network Cable (305m Roll)", "agreed_price": 4200.0},
    {"name": "Industrial Surge Protector Strip", "agreed_price": 1800.0},
    {"name": "HD 1080p Video Conferencing Webcam", "agreed_price": 2600.0},
    {"name": "Active Noise-Cancelling Headset", "agreed_price": 3800.0}
]


# -------------------------------------------------------------
# 2. Generate 8 Supplier Contract Text Files
# -------------------------------------------------------------
def generate_contracts():
    """Generates 8 master vendor contract text files in data/contracts/."""
    print("Generating 8 supplier contracts...")
    for supplier in SUPPLIERS:
        file_path = CONTRACTS_DIR / f"contract_supplier_{supplier['id']}.txt"
        content = f"""================================================================================
                    MASTER VENDOR SUPPLY AGREEMENT
================================================================================
Supplier: {supplier['name']}
Address:  {supplier['address']}
GSTIN:    {supplier['gstin']}
Email:    {supplier['email']} | Phone: {supplier['phone']}
Payment Terms: Net {supplier['payment_terms_days']} Days
Agreement Date: 2026-01-01
Jurisdiction: Indian Contract Act, 1872

1. SCOPE AND PRICING
The Supplier agrees to deliver the following items at the agreed fixed unit rates.
All rates are denominated in Rs. (Indian Rupees).

"""
        content += f"{'Item Name':<42} {'Agreed Unit Price':<20}\n"
        content += "-" * 65 + "\n"
        for prod in PRODUCTS:
            content += f"{prod['name']:<42} Rs. {prod['agreed_price']:>10.2f}\n"

        content += f"""
2. TAXATION & GST CLAUSE
All listed prices are exclusive of Goods and Services Tax (GST).
A standard GST rate of 18% (comprising 9% CGST and 9% SGST) shall apply to all
tax invoices. Valid GSTIN of both the supplier and buyer must appear on invoices.

3. DELIVERY & ACCEPTANCE
Goods will only be deemed received upon verification by warehouse staff and
issuance of a valid Goods Received Note (GRN). Invoices must match the approved
Purchase Order (PO) and GRN quantities.

4. PAYMENT TERMS
Payment shall be released within {supplier['payment_terms_days']} days from the date of receipt
of a verified and clean invoice. Any invoice containing discrepancies will be
placed on hold with status 'needs_review' or 'mismatch_detected'.

Authorized Signatory,                         Authorized Signatory,
{supplier['name']}                            VouchFlow AI Corporate Finance
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    print(f"Contracts saved to: {CONTRACTS_DIR}")


# -------------------------------------------------------------
# 3. ReportLab PDF Invoice Generator
# -------------------------------------------------------------
def build_invoice_pdf(
    file_path: Path,
    invoice_number: str,
    invoice_date: str,
    due_date: str,
    po_number: str,
    supplier: dict,
    items: list,
    subtotal: float,
    tax_amount: float,
    grand_total: float,
    watermark_note: str = ""
):
    """
    Renders a clean, professional invoice PDF using ReportLab.
    Uses 'Rs.' exclusively to ensure standard Helvetica font compatibility.
    """
    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4A5568")
    )
    bold_style = ParagraphStyle(
        'BoldText',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#2D3748")
    )
    cell_style = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#2D3748")
    )
    cell_bold_style = ParagraphStyle(
        'CellBold',
        parent=cell_style,
        fontName="Helvetica-Bold"
    )

    story = []

    # Header section: Supplier info & Invoice Title
    header_data = [
        [
            Paragraph(f"<b>{supplier['name']}</b><br/>{supplier['address']}<br/>GSTIN: {supplier['gstin']}<br/>Email: {supplier['email']}", subtitle_style),
            Paragraph("<b>TAX INVOICE</b>", title_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[340, 200])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A365D"), spaceAfter=10))

    # Meta Information Table: Invoice details and Billed-to details
    po_display = po_number if po_number else "N/A (Missing PO)"
    meta_data = [
        [
            Paragraph("<b>Billed To:</b>", cell_bold_style),
            Paragraph(f"<b>Invoice No:</b> {invoice_number}", cell_style),
            Paragraph(f"<b>Invoice Date:</b> {invoice_date}", cell_style)
        ],
        [
            Paragraph("VouchFlow Technologies India Pvt Ltd<br/>Ground Floor, Innovate Tech Park, Bengaluru 560100<br/>GSTIN: 29ABCDE1234F1Z5", cell_style),
            Paragraph(f"<b>PO Number:</b> {po_display}", cell_style),
            Paragraph(f"<b>Due Date:</b> {due_date}", cell_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[240, 150, 150])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))

    # Line Items Table
    table_rows = [
        [
            Paragraph("<b>#</b>", cell_bold_style),
            Paragraph("<b>Item Description</b>", cell_bold_style),
            Paragraph("<b>Qty</b>", cell_bold_style),
            Paragraph("<b>Unit Price (Rs.)</b>", cell_bold_style),
            Paragraph("<b>Amount (Rs.)</b>", cell_bold_style)
        ]
    ]

    for idx, item in enumerate(items, start=1):
        table_rows.append([
            Paragraph(str(idx), cell_style),
            Paragraph(item["item_name"], cell_style),
            Paragraph(str(item["quantity"]), cell_style),
            Paragraph(f"Rs. {item['unit_price']:,.2f}", cell_style),
            Paragraph(f"Rs. {item['total_price']:,.2f}", cell_style)
        ])

    items_table = Table(table_rows, colWidths=[30, 260, 50, 100, 100])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 10))

    # Totals breakdown (Subtotal, CGST 9%, SGST 9%, Grand Total)
    cgst = tax_amount / 2.0
    sgst = tax_amount / 2.0
    summary_data = [
        ["", Paragraph("Subtotal:", bold_style), Paragraph(f"Rs. {subtotal:,.2f}", bold_style)],
        ["", Paragraph("CGST (9%):", cell_style), Paragraph(f"Rs. {cgst:,.2f}", cell_style)],
        ["", Paragraph("SGST (9%):", cell_style), Paragraph(f"Rs. {sgst:,.2f}", cell_style)],
        ["", Paragraph("Total GST (18%):", cell_style), Paragraph(f"Rs. {tax_amount:,.2f}", cell_style)],
        ["", Paragraph("<b>Grand Total:</b>", bold_style), Paragraph(f"<b>Rs. {grand_total:,.2f}</b>", bold_style)],
    ]

    summary_table = Table(summary_data, colWidths=[290, 120, 130])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('LINEABOVE', (1, 4), (-1, 4), 1, colors.HexColor("#1A365D")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(summary_table)

    # Footer Notes
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E0"), spaceAfter=6))
    terms_para = Paragraph(
        "<b>Terms & Conditions:</b> Payment is due as per agreed vendor contract terms. "
        "All disputes are subject to the local jurisdiction. Thank you for your business.",
        subtitle_style
    )
    story.append(terms_para)

    # Build PDF
    doc.build(story)


# -------------------------------------------------------------
# 4. Generate 50 Invoices, POs, GRNs & Planted Discrepancies
# -------------------------------------------------------------
def generate_dataset():
    """
    Creates 50 invoices:
    - ~70% clean (35 invoices, expected_status: 'verified')
    - ~30% with mistakes (15 invoices, 3 of each mistake type):
        1. price_mismatch
        2. quantity_mismatch
        3. wrong_total
        4. duplicate_invoice
        5. missing_po
    """
    print("Generating 50 invoices, POs, GRNs and ground truth dataset...")

    # Assign mistake distribution
    # Exactly 15 mistake invoices and 35 clean invoices = 50 total
    mistake_types = (
        ["price_mismatch"] * 3 +
        ["quantity_mismatch"] * 3 +
        ["wrong_total"] * 3 +
        ["duplicate_invoice"] * 3 +
        ["missing_po"] * 3
    )
    clean_types = ["none"] * (50 - len(mistake_types))

    assignment = clean_types + mistake_types
    # Shuffle predictably
    random.shuffle(assignment)

    all_invoices = []
    all_pos = []
    all_grns = []
    ground_truth_records = []

    base_date = date(2026, 1, 10)

    # Keep track of an earlier clean invoice to duplicate for 'duplicate_invoice'
    clean_sample_for_dup = None

    for i in range(1, 51):
        invoice_id = i
        mistake = assignment[i - 1]
        file_name = f"INV_{invoice_id:03d}.pdf"
        file_path = INVOICES_DIR / file_name

        supplier = SUPPLIERS[(i - 1) % len(SUPPLIERS)]
        po_number = f"PO-2026-{invoice_id:04d}"
        grn_number = f"GRN-2026-{invoice_id:04d}"

        inv_date = base_date + timedelta(days=i * 2)
        due_date = inv_date + timedelta(days=supplier["payment_terms_days"])

        # Select 1 to 3 distinct items for this invoice
        num_items = random.choice([1, 2, 3])
        sampled_products = random.sample(PRODUCTS, num_items)

        # Baseline correct items
        base_items = []
        for p in sampled_products:
            qty = random.randint(2, 20)
            u_price = p["agreed_price"]
            base_items.append({
                "item_name": p["name"],
                "quantity": qty,
                "unit_price": u_price,
                "total_price": round(qty * u_price, 2)
            })

        # Correct totals
        correct_subtotal = round(sum(item["total_price"] for item in base_items), 2)
        correct_tax = round(correct_subtotal * 0.18, 2)
        correct_grand_total = round(correct_subtotal + correct_tax, 2)

        # PO and GRN items match the baseline items initially
        po_items = [dict(item) for item in base_items]
        grn_items = [{"item_name": item["item_name"], "quantity_received": item["quantity"]} for item in base_items]

        # Invoice items initially match baseline
        invoice_items = [dict(item) for item in base_items]
        inv_subtotal = correct_subtotal
        inv_tax = correct_tax
        inv_grand_total = correct_grand_total
        inv_po_number = po_number

        expected_status = "verified"
        notes = "All checks passed: Invoice matches PO, GRN, and Contract."

        # Apply specific planted mistake
        if mistake == "price_mismatch":
            expected_status = "mismatch_detected"
            # Increase unit price of the first item by Rs. 500
            diff = 500.0
            invoice_items[0]["unit_price"] += diff
            invoice_items[0]["total_price"] = round(invoice_items[0]["quantity"] * invoice_items[0]["unit_price"], 2)
            inv_subtotal = round(sum(it["total_price"] for it in invoice_items), 2)
            inv_tax = round(inv_subtotal * 0.18, 2)
            inv_grand_total = round(inv_subtotal + inv_tax, 2)
            notes = f"Price mismatch: Item '{invoice_items[0]['item_name']}' billed at Rs. {invoice_items[0]['unit_price']} vs agreed Rs. {base_items[0]['unit_price']}."

        elif mistake == "quantity_mismatch":
            expected_status = "mismatch_detected"
            # Invoice bills for 5 more units than warehouse GRN received
            extra_qty = 5
            invoice_items[0]["quantity"] += extra_qty
            invoice_items[0]["total_price"] = round(invoice_items[0]["quantity"] * invoice_items[0]["unit_price"], 2)
            inv_subtotal = round(sum(it["total_price"] for it in invoice_items), 2)
            inv_tax = round(inv_subtotal * 0.18, 2)
            inv_grand_total = round(inv_subtotal + inv_tax, 2)
            notes = f"Quantity mismatch: Invoiced {invoice_items[0]['quantity']} units of '{invoice_items[0]['item_name']}', but GRN received only {grn_items[0]['quantity_received']}."

        elif mistake == "wrong_total":
            expected_status = "mismatch_detected"
            # Math calculation error on invoice total (+ Rs. 1500 discrepancy)
            inv_grand_total = round(inv_grand_total + 1500.0, 2)
            notes = f"Calculation error: Line items and tax add up to Rs. {correct_grand_total}, but invoice total states Rs. {inv_grand_total}."

        elif mistake == "missing_po":
            expected_status = "needs_review"
            inv_po_number = ""  # No PO linked on the invoice
            notes = "Missing Purchase Order: Invoice does not reference a valid purchase order."

        elif mistake == "duplicate_invoice":
            expected_status = "mismatch_detected"
            if clean_sample_for_dup is not None:
                dup_target = clean_sample_for_dup
                invoice_number = dup_target["invoice_number"]
                inv_po_number = dup_target["po_number"]
                invoice_items = [dict(it) for it in dup_target["items"]]
                inv_subtotal = dup_target["subtotal"]
                inv_tax = dup_target["tax_amount"]
                inv_grand_total = dup_target["grand_total"]
                notes = f"Duplicate invoice: Duplicate of previously submitted invoice {invoice_number}."
            else:
                invoice_number = f"INV-2026-{invoice_id:04d}"
                notes = "Duplicate invoice submission detected."
        else:
            invoice_number = f"INV-2026-{invoice_id:04d}"

        if mistake != "duplicate_invoice" or clean_sample_for_dup is None:
            invoice_number = f"INV-2026-{invoice_id:04d}"

        # Save first clean invoice as template for duplicate testing
        if mistake == "none" and clean_sample_for_dup is None:
            clean_sample_for_dup = {
                "invoice_number": invoice_number,
                "po_number": po_number,
                "items": [dict(it) for it in invoice_items],
                "subtotal": inv_subtotal,
                "tax_amount": inv_tax,
                "grand_total": inv_grand_total
            }

        # Build PDF file
        build_invoice_pdf(
            file_path=file_path,
            invoice_number=invoice_number,
            invoice_date=str(inv_date),
            due_date=str(due_date),
            po_number=inv_po_number,
            supplier=supplier,
            items=invoice_items,
            subtotal=inv_subtotal,
            tax_amount=inv_tax,
            grand_total=inv_grand_total
        )

        # Store record for ground truth CSV
        ground_truth_records.append({
            "invoice_id": invoice_id,
            "file_name": file_name,
            "invoice_number": invoice_number,
            "supplier_id": supplier["id"],
            "supplier_name": supplier["name"],
            "po_number": inv_po_number,
            "expected_status": expected_status,
            "mistake_type": mistake,
            "invoiced_subtotal": inv_subtotal,
            "invoiced_tax": inv_tax,
            "invoiced_grand_total": inv_grand_total,
            "correct_subtotal": correct_subtotal,
            "correct_tax": correct_tax,
            "correct_grand_total": correct_grand_total,
            "notes": notes
        })

        # Store in-memory objects for JSON export
        all_pos.append({
            "id": invoice_id,
            "po_number": po_number,
            "supplier_id": supplier["id"],
            "order_date": str(inv_date - timedelta(days=5)),
            "status": "issued",
            "total_amount": correct_grand_total,
            "items": po_items
        })

        all_grns.append({
            "id": invoice_id,
            "grn_number": grn_number,
            "po_id": invoice_id,
            "received_date": str(inv_date - timedelta(days=2)),
            "received_by": "Ramesh Kumar (Warehouse Supv)",
            "remarks": "Received in good condition",
            "items": grn_items
        })

        all_invoices.append({
            "id": invoice_id,
            "invoice_number": invoice_number,
            "supplier_id": supplier["id"] if mistake != "missing_po" else supplier["id"],
            "po_id": invoice_id if inv_po_number else None,
            "invoice_date": str(inv_date),
            "due_date": str(due_date),
            "subtotal": inv_subtotal,
            "tax_amount": inv_tax,
            "grand_total": inv_grand_total,
            "file_path": f"data/invoices/{file_name}",
            "status": expected_status,
            "mistake_type": mistake,
            "items": invoice_items
        })

    # Save Ground Truth CSV
    gt_df = pd.DataFrame(ground_truth_records)
    gt_csv_path = EVAL_DIR / "ground_truth.csv"
    gt_df.to_csv(gt_csv_path, index=False)
    print(f"Ground truth CSV saved to: {gt_csv_path}")

    # Save Mock Data JSON for seeding database
    mock_data = {
        "suppliers": SUPPLIERS,
        "products": PRODUCTS,
        "purchase_orders": all_pos,
        "goods_received_notes": all_grns,
        "invoices": all_invoices
    }
    mock_json_path = EVAL_DIR / "mock_data.json"
    with open(mock_json_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, indent=2)
    print(f"Mock seed dataset saved to: {mock_json_path}")

    # Print summary statistics
    status_counts = gt_df["expected_status"].value_counts().to_dict()
    mistake_counts = gt_df["mistake_type"].value_counts().to_dict()
    print("\n--- Generation Summary ---")
    print(f"Total Invoices Generated: {len(gt_df)}")
    print(f"Status Breakdown: {status_counts}")
    print(f"Mistake Distribution: {mistake_counts}")


if __name__ == "__main__":
    generate_contracts()
    generate_dataset()
