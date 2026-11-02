"""
Hard Test Cases Generator for VouchFlow AI (3-Way Matching Stress Test)
========================================================================
Generates 40 challenging, adversarial invoices (IDs 51 to 90) designed to
stress-test the 3-Way Matching Engine and uncover real-world weaknesses.

Covers 10 tricky categories (4 invoices each = 40 total):
1. Tiny price differences (Rs. 0.50 and 1% variance)
2. Price matches PO but not Contract, and the reverse
3. Partial delivery (GRN < billed) and Over-delivery (GRN > PO or billed > GRN)
4. Multi-item invoices (5 to 7 items) where only one line item is faulty
5. Commercial rounding differences (Rs. 0.01 to Rs. 1.00) that should count as OK
6. GST calculated at wrong tax rate (12%, 5%, 0%, 9%) instead of contracted 18%
7. Duplicate invoices with disguised invoice numbers (same supplier, amount, date)
8. Cross-supplier invoice number collision (same number from different vendors - NOT duplicate)
9. Suspicious-looking but 100% legitimate invoices (weekend dates, bulk orders, round sums)
10. Compound double-mistakes (simultaneous price + quantity, price + math, etc.)

Outputs:
- 40 PDF invoices in data/invoices/ (INV_051.pdf to INV_090.pdf)
- Database records in vouchflow.db (POs, GRNs, Invoices, Line Items, Extractions)
- Answer sheet in data/evaluation/hard_ground_truth.csv
"""

import os
import sys
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.database.db import SessionLocal, init_db
from backend.database.models import (
    Supplier,
    Contract,
    PurchaseOrder,
    POItem,
    GoodsReceivedNote,
    GRNItem,
    Invoice,
    InvoiceItem,
    InvoiceExtraction
)

# Output directories
DATA_DIR = BASE_DIR / "data"
INVOICES_DIR = DATA_DIR / "invoices"
EVAL_DIR = DATA_DIR / "evaluation"

for d in [INVOICES_DIR, EVAL_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Master Indian Suppliers & Products catalog
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
        "name": "Gupta Supplies & Logistics",
        "email": "invoicing@guptasupplies.co.in",
        "phone": "+91 98300 34567",
        "address": "88 Park Street, 4th Floor, Kolkata, West Bengal 700016",
        "gstin": "19CCCCC9012C3Z7",
        "payment_terms_days": 45
    },
    {
        "id": 4,
        "name": "Verma Office Solutions",
        "email": "finance@vermaoffice.in",
        "phone": "+91 98480 45678",
        "address": "102 MG Road, Secunderabad, Telangana 500003",
        "gstin": "36DDDDD3456D4Z8",
        "payment_terms_days": 30
    },
    {
        "id": 5,
        "name": "Reddy Tech Supplies",
        "email": "sales@reddytech.co.in",
        "phone": "+91 98450 56789",
        "address": "33 Brigade Road, Bangalore, Karnataka 560001",
        "gstin": "29EEEEE7890E5Z9",
        "payment_terms_days": 15
    },
    {
        "id": 6,
        "name": "Nair & Company",
        "email": "billing@nairco.in",
        "phone": "+91 98470 67890",
        "address": "56 MG Road, Ernakulam, Kochi, Kerala 682011",
        "gstin": "32FFFFF1234F6Z1",
        "payment_terms_days": 30
    },
    {
        "id": 7,
        "name": "Mehta Commercials",
        "email": "tax@mehtacommercials.com",
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

PRODUCTS = {
    "Ergonomic Office Chair": 4500.0,
    "Standing Desk 120cm": 12000.0,
    "Wireless Keyboard & Mouse Combo": 1500.0,
    "24-inch IPS Monitor": 8500.0,
    "High-Speed USB-C Dock": 3200.0,
    "A4 Copier Paper (Box of 5 Reams)": 1100.0,
    "Cat6 Network Cable (305m Roll)": 4200.0,
    "Industrial Surge Protector Strip": 1800.0,
    "HD 1080p Video Conferencing Webcam": 2600.0,
    "Active Noise-Cancelling Headset": 3800.0
}


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
    """Renders a PDF invoice using ReportLab."""
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

    header_data = [
        [
            Paragraph(f"<b>{supplier['name']}</b><br/>{supplier['address']}<br/>GSTIN: {supplier['gstin']}<br/>Email: {supplier['email']}", subtitle_style),
            Paragraph("<b>TAX INVOICE (STRESS TEST)</b>", title_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[340, 200])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    meta_data = [
        [
            Paragraph(f"<b>Invoice Number:</b> {invoice_number}", bold_style),
            Paragraph(f"<b>Invoice Date:</b> {invoice_date}", subtitle_style)
        ],
        [
            Paragraph(f"<b>PO Reference:</b> {po_number if po_number else 'N/A'}", bold_style),
            Paragraph(f"<b>Due Date:</b> {due_date}", subtitle_style)
        ],
        [
            Paragraph(f"<b>Payment Terms:</b> Net {supplier['payment_terms_days']} Days", subtitle_style),
            Paragraph("<b>Currency:</b> INR (Rs.)", subtitle_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[270, 270])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Line Items</b>", bold_style))
    story.append(Spacer(1, 4))

    table_data = [
        [
            Paragraph("<b>#</b>", cell_bold_style),
            Paragraph("<b>Item Description</b>", cell_bold_style),
            Paragraph("<b>Qty</b>", cell_bold_style),
            Paragraph("<b>Unit Price (Rs.)</b>", cell_bold_style),
            Paragraph("<b>Total (Rs.)</b>", cell_bold_style)
        ]
    ]

    for idx, item in enumerate(items, 1):
        table_data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(item["item_name"], cell_style),
            Paragraph(str(item["quantity"]), cell_style),
            Paragraph(f"Rs. {item['unit_price']:,.2f}", cell_style),
            Paragraph(f"Rs. {item['total_price']:,.2f}", cell_style)
        ])

    items_table = Table(table_data, colWidths=[25, 275, 45, 95, 100])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 10))

    half_tax = tax_amount / 2.0
    summary_data = [
        ["", "Subtotal:", f"Rs. {subtotal:,.2f}"],
        ["", "CGST (9%):", f"Rs. {half_tax:,.2f}"],
        ["", "SGST (9%):", f"Rs. {half_tax:,.2f}"],
        ["", "Total Tax (GST):", f"Rs. {tax_amount:,.2f}"],
        ["", "Grand Total:", f"Rs. {grand_total:,.2f}"]
    ]
    summary_table = Table(summary_data, colWidths=[290, 130, 120])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (1, 4), (-1, 4), 'Helvetica-Bold'),
        ('TEXTCOLOR', (1, 4), (-1, 4), colors.HexColor("#1A365D")),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('LINEABOVE', (1, 4), (-1, 4), 1, colors.HexColor("#1A365D")),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(summary_table)

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E0"), spaceAfter=4))
    terms_para = Paragraph(
        "<b>Terms & Conditions:</b> Payment subject to verification of PO and warehouse GRN receipts. "
        "Discrepancies will be placed on hold.",
        subtitle_style
    )
    story.append(terms_para)
    doc.build(story)


def generate_hard_dataset():
    """Generates 40 hard invoice cases with DB seeding and ground truth answer key."""
    print("Generating 40 Hard Test Cases for 3-Way Matching Stress Test...")
    init_db()
    db = SessionLocal()

    base_date = date(2026, 3, 1)

    hard_cases: List[Dict[str, Any]] = []

    # --------------------------------------------------------------------------
    # 1. Tiny price differences (Rs. 0.50 and 1%) -> IDs 51 to 54
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 51,
        "supplier_idx": 0,
        "category": "tiny_price_difference",
        "items": [{"name": "Ergonomic Office Chair", "qty": 10, "inv_price": 4500.50, "po_price": 4500.0, "contract_price": 4500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Invoiced unit price is Rs. 0.50 higher than PO and contract agreed price"
    })
    hard_cases.append({
        "id": 52,
        "supplier_idx": 1,
        "category": "tiny_price_difference",
        "items": [{"name": "Wireless Keyboard & Mouse Combo", "qty": 20, "inv_price": 1499.50, "po_price": 1500.0, "contract_price": 1500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Invoiced unit price is Rs. 0.50 lower than PO and contract agreed price"
    })
    hard_cases.append({
        "id": 53,
        "supplier_idx": 2,
        "category": "tiny_price_difference",
        "items": [{"name": "24-inch IPS Monitor", "qty": 5, "inv_price": 8585.00, "po_price": 8500.0, "contract_price": 8500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Invoiced unit price has a subtle 1% markup (Rs. 8585 vs Rs. 8500)"
    })
    hard_cases.append({
        "id": 54,
        "supplier_idx": 3,
        "category": "tiny_price_difference",
        "items": [{"name": "Standing Desk 120cm", "qty": 4, "inv_price": 12120.00, "po_price": 12000.0, "contract_price": 12000.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Invoiced unit price has a 1% price increase over PO and contract"
    })

    # --------------------------------------------------------------------------
    # 2. Price matches PO but not contract, and reverse -> IDs 55 to 58
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 55,
        "supplier_idx": 4,
        "category": "po_vs_contract_price",
        "items": [{"name": "High-Speed USB-C Dock", "qty": 10, "inv_price": 3500.0, "po_price": 3500.0, "contract_price": 3200.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Invoice price matches PO (Rs. 3500) but violates contract agreed price (Rs. 3200)"
    })
    hard_cases.append({
        "id": 56,
        "supplier_idx": 5,
        "category": "po_vs_contract_price",
        "items": [{"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 15, "inv_price": 1100.0, "po_price": 1250.0, "contract_price": 1100.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Invoice price matches Contract (Rs. 1100) but mismatches PO price (Rs. 1250)"
    })
    hard_cases.append({
        "id": 57,
        "supplier_idx": 6,
        "category": "po_vs_contract_price",
        "items": [{"name": "Active Noise-Cancelling Headset", "qty": 8, "inv_price": 4200.0, "po_price": 4200.0, "contract_price": 3800.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Invoice matches PO price but exceeds master contract rate by Rs. 400"
    })
    hard_cases.append({
        "id": 58,
        "supplier_idx": 7,
        "category": "po_vs_contract_price",
        "items": [{"name": "Cat6 Network Cable (305m Roll)", "qty": 6, "inv_price": 4200.0, "po_price": 3900.0, "contract_price": 4200.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Invoice billed full contract rate ignoring special negotiated lower PO rate"
    })

    # --------------------------------------------------------------------------
    # 3. Partial delivery & Over-delivery -> IDs 59 to 62
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 59,
        "supplier_idx": 0,
        "category": "delivery_discrepancy",
        "items": [{"name": "Industrial Surge Protector Strip", "qty": 30, "grn_qty": 20, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
        "description": "Partial delivery: invoice bills for 30 units but warehouse GRN only received 20"
    })
    hard_cases.append({
        "id": 60,
        "supplier_idx": 1,
        "category": "delivery_discrepancy",
        "items": [{"name": "HD 1080p Video Conferencing Webcam", "qty": 50, "grn_qty": 42, "inv_price": 2600.0, "po_price": 2600.0, "contract_price": 2600.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
        "description": "Partial delivery: billed 50 units but GRN recorded 42 received"
    })
    hard_cases.append({
        "id": 61,
        "supplier_idx": 2,
        "category": "delivery_discrepancy",
        "items": [{"name": "Ergonomic Office Chair", "qty": 20, "po_qty": 15, "grn_qty": 20, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
        "description": "Over-delivery: invoice bills 20 units exceeding PO authorized quantity of 15"
    })
    hard_cases.append({
        "id": 62,
        "supplier_idx": 3,
        "category": "delivery_discrepancy",
        "items": [{"name": "24-inch IPS Monitor", "qty": 12, "po_qty": 10, "grn_qty": 10, "inv_price": 8500.0, "po_price": 8500.0, "contract_price": 8500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
        "description": "Invoiced quantity (12) exceeds both PO (10) and GRN physical receipt (10)"
    })

    # --------------------------------------------------------------------------
    # 4. Multi-item invoices (5+ items) where only one is wrong -> IDs 63 to 66
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 63,
        "supplier_idx": 4,
        "category": "multi_item_single_error",
        "items": [
            {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 10, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0},
            {"name": "Wireless Keyboard & Mouse Combo", "qty": 5, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0},
            {"name": "Industrial Surge Protector Strip", "qty": 4, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0},
            {"name": "High-Speed USB-C Dock", "qty": 3, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0},
            {"name": "Active Noise-Cancelling Headset", "qty": 2, "inv_price": 4200.0, "po_price": 3800.0, "contract_price": 3800.0}  # faulty item 5
        ],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "5-item invoice where item 5 has a subtle price mismatch of Rs. 400"
    })
    hard_cases.append({
        "id": 64,
        "supplier_idx": 5,
        "category": "multi_item_single_error",
        "items": [
            {"name": "Cat6 Network Cable (305m Roll)", "qty": 2, "inv_price": 4200.0, "po_price": 4200.0, "contract_price": 4200.0},
            {"name": "HD 1080p Video Conferencing Webcam", "qty": 4, "inv_price": 2600.0, "po_price": 2600.0, "contract_price": 2600.0},
            {"name": "Wireless Keyboard & Mouse Combo", "qty": 8, "grn_qty": 4, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0},  # faulty item 3
            {"name": "Industrial Surge Protector Strip", "qty": 5, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0},
            {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 10, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0},
            {"name": "High-Speed USB-C Dock", "qty": 2, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0}
        ],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
        "description": "6-item invoice where only item 3 has a quantity mismatch (billed 8, GRN 4)"
    })
    hard_cases.append({
        "id": 65,
        "supplier_idx": 6,
        "category": "multi_item_single_error",
        "items": [
            {"name": "Ergonomic Office Chair", "qty": 3, "inv_price": 4900.0, "po_price": 4500.0, "contract_price": 4500.0},  # faulty item 1
            {"name": "Standing Desk 120cm", "qty": 2, "inv_price": 12000.0, "po_price": 12000.0, "contract_price": 12000.0},
            {"name": "24-inch IPS Monitor", "qty": 2, "inv_price": 8500.0, "po_price": 8500.0, "contract_price": 8500.0},
            {"name": "High-Speed USB-C Dock", "qty": 4, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0},
            {"name": "Wireless Keyboard & Mouse Combo", "qty": 5, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0}
        ],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "5-item invoice where only the first item has an inflated unit price"
    })
    hard_cases.append({
        "id": 66,
        "supplier_idx": 7,
        "category": "multi_item_single_error",
        "items": [
            {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 20, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0},
            {"name": "Cat6 Network Cable (305m Roll)", "qty": 3, "inv_price": 4200.0, "po_price": 4200.0, "contract_price": 4200.0},
            {"name": "Industrial Surge Protector Strip", "qty": 6, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0},
            {"name": "Wireless Keyboard & Mouse Combo", "qty": 15, "grn_qty": 10, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0},  # faulty item 4
            {"name": "HD 1080p Video Conferencing Webcam", "qty": 3, "inv_price": 2600.0, "po_price": 2600.0, "contract_price": 2600.0},
            {"name": "Active Noise-Cancelling Headset", "qty": 2, "inv_price": 3800.0, "po_price": 3800.0, "contract_price": 3800.0},
            {"name": "High-Speed USB-C Dock", "qty": 2, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0}
        ],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
        "description": "7-item invoice where single middle item has quantity mismatch (billed 15, GRN 10)"
    })

    # --------------------------------------------------------------------------
    # 5. Rounding difference of Rs. 0.01 to Rs. 1.00 (The Trap Case) -> IDs 67 to 70
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 67,
        "supplier_idx": 0,
        "category": "rounding_difference_trap",
        "items": [
            {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 7, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0},
            {"name": "Wireless Keyboard & Mouse Combo", "qty": 3, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0}
        ],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.25,  # +0.25 roundoff
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Legitimate commercial rounding difference of +Rs. 0.25 (should count as OK)"
    })
    hard_cases.append({
        "id": 68,
        "supplier_idx": 1,
        "category": "rounding_difference_trap",
        "items": [{"name": "Ergonomic Office Chair", "qty": 2, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": -0.45,  # -0.45 roundoff
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Legitimate rounding to nearest integer rupee with -Rs. 0.45 difference"
    })
    hard_cases.append({
        "id": 69,
        "supplier_idx": 2,
        "category": "rounding_difference_trap",
        "items": [
            {"name": "Industrial Surge Protector Strip", "qty": 5, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0},
            {"name": "Cat6 Network Cable (305m Roll)", "qty": 1, "inv_price": 4200.0, "po_price": 4200.0, "contract_price": 4200.0}
        ],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.50,  # +0.50 roundoff
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Commercial round-off adjustment of Rs. 0.50 (should count as OK)"
    })
    hard_cases.append({
        "id": 70,
        "supplier_idx": 3,
        "category": "rounding_difference_trap",
        "items": [{"name": "24-inch IPS Monitor", "qty": 3, "inv_price": 8500.0, "po_price": 8500.0, "contract_price": 8500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": -0.80,  # -0.80 roundoff
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Commercial invoice total round-off adjustment of -Rs. 0.80 (should count as OK)"
    })

    # --------------------------------------------------------------------------
    # 6. GST calculated at wrong tax rate (12% or 5%) -> IDs 71 to 74
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 71,
        "supplier_idx": 4,
        "category": "wrong_gst_rate",
        "items": [{"name": "Standing Desk 120cm", "qty": 2, "inv_price": 12000.0, "po_price": 12000.0, "contract_price": 12000.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.12, "round_diff": 0.0,  # 12% instead of 18%
        "expected_status": "mismatch_detected", "expected_mistake": "wrong_total",
        "description": "GST calculated at incorrect rate of 12% instead of contracted 18%"
    })
    hard_cases.append({
        "id": 72,
        "supplier_idx": 5,
        "category": "wrong_gst_rate",
        "items": [{"name": "HD 1080p Video Conferencing Webcam", "qty": 6, "inv_price": 2600.0, "po_price": 2600.0, "contract_price": 2600.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.05, "round_diff": 0.0,  # 5% instead of 18%
        "expected_status": "mismatch_detected", "expected_mistake": "wrong_total",
        "description": "GST calculated at incorrect rate of 5% instead of contracted 18%"
    })
    hard_cases.append({
        "id": 73,
        "supplier_idx": 6,
        "category": "wrong_gst_rate",
        "items": [{"name": "Active Noise-Cancelling Headset", "qty": 4, "inv_price": 3800.0, "po_price": 3800.0, "contract_price": 3800.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.0, "round_diff": 0.0,  # 0% GST billed
        "expected_status": "mismatch_detected", "expected_mistake": "wrong_total",
        "description": "GST billed at 0% instead of required 18% tax rate"
    })
    hard_cases.append({
        "id": 74,
        "supplier_idx": 7,
        "category": "wrong_gst_rate",
        "items": [{"name": "High-Speed USB-C Dock", "qty": 5, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.09, "round_diff": 0.0,  # SGST omitted (9% total)
        "expected_status": "mismatch_detected", "expected_mistake": "wrong_total",
        "description": "SGST omitted resulting in 9% total tax instead of required 18% GST"
    })

    # --------------------------------------------------------------------------
    # 7. Disguised duplicates (same supplier, amount, date; tweaked invoice number) -> IDs 75 to 78
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 75,
        "supplier_idx": 0,
        "category": "disguised_duplicate",
        "duplicate_of_id": 51,
        "custom_inv_num": "INV-HARD-0051-DUP",
        "items": [{"name": "Ergonomic Office Chair", "qty": 10, "inv_price": 4500.50, "po_price": 4500.0, "contract_price": 4500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "duplicate_invoice",
        "description": "Duplicate invoice: changed invoice number but identical supplier, date, and amount"
    })
    hard_cases.append({
        "id": 76,
        "supplier_idx": 2,
        "category": "disguised_duplicate",
        "duplicate_of_id": 53,
        "custom_inv_num": "INV-HARD-0053-REVISED",
        "items": [{"name": "24-inch IPS Monitor", "qty": 5, "inv_price": 8585.00, "po_price": 8500.0, "contract_price": 8500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "duplicate_invoice",
        "description": "Duplicate invoice: revised invoice number with identical supplier, date, and amount"
    })
    hard_cases.append({
        "id": 77,
        "supplier_idx": 0,
        "category": "disguised_duplicate",
        "duplicate_of_id": 67,
        "custom_inv_num": "BILL/2026/0067",
        "items": [
            {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 7, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0},
            {"name": "Wireless Keyboard & Mouse Combo", "qty": 3, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0}
        ],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.25,
        "expected_status": "mismatch_detected", "expected_mistake": "duplicate_invoice",
        "description": "Duplicate invoice: reformatted number with identical supplier, date, and total"
    })
    hard_cases.append({
        "id": 78,
        "supplier_idx": 7,
        "category": "disguised_duplicate",
        "duplicate_of_id": 58,
        "custom_inv_num": "INV-HARD-0058-A",
        "items": [{"name": "Cat6 Network Cable (305m Roll)", "qty": 6, "inv_price": 4200.0, "po_price": 3900.0, "contract_price": 4200.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "duplicate_invoice",
        "description": "Duplicate invoice: same supplier, date, and grand total under alias number"
    })

    # --------------------------------------------------------------------------
    # 8. Same invoice number from two different suppliers (NOT duplicate) -> IDs 79 to 82
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 79,
        "supplier_idx": 0,  # Sharma Traders
        "category": "cross_supplier_collision",
        "custom_inv_num": "INV-SHARED-9901",
        "items": [{"name": "Ergonomic Office Chair", "qty": 4, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Valid invoice sharing common numbering format INV-SHARED-9901 from Supplier 1"
    })
    hard_cases.append({
        "id": 80,
        "supplier_idx": 1,  # Patel Enterprises (Different Supplier)
        "category": "cross_supplier_collision",
        "custom_inv_num": "INV-SHARED-9901",
        "items": [{"name": "Wireless Keyboard & Mouse Combo", "qty": 10, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Valid invoice sharing number INV-SHARED-9901 from Supplier 2 (NOT a duplicate)"
    })
    hard_cases.append({
        "id": 81,
        "supplier_idx": 2,  # Gupta Supplies
        "category": "cross_supplier_collision",
        "custom_inv_num": "BILL-COMMON-X1",
        "items": [{"name": "24-inch IPS Monitor", "qty": 2, "inv_price": 8500.0, "po_price": 8500.0, "contract_price": 8500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Valid invoice with shared series number BILL-COMMON-X1 from Supplier 3"
    })
    hard_cases.append({
        "id": 82,
        "supplier_idx": 3,  # Verma Office Solutions
        "category": "cross_supplier_collision",
        "custom_inv_num": "BILL-COMMON-X1",
        "items": [{"name": "High-Speed USB-C Dock", "qty": 4, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Valid invoice with shared series number BILL-COMMON-X1 from Supplier 4 (NOT a duplicate)"
    })

    # --------------------------------------------------------------------------
    # 9. Suspicious-looking but 100% valid invoices -> IDs 83 to 86
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 83,
        "supplier_idx": 4,
        "category": "suspicious_looking_valid",
        "custom_inv_date": date(2026, 3, 15),  # Sunday
        "items": [{"name": "Standing Desk 120cm", "qty": 3, "inv_price": 12000.0, "po_price": 12000.0, "contract_price": 12000.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Valid weekend/Sunday invoice fully authorized by PO delivery schedule"
    })
    hard_cases.append({
        "id": 84,
        "supplier_idx": 5,
        "category": "suspicious_looking_valid",
        "items": [{"name": "Ergonomic Office Chair", "qty": 150, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Valid massive bulk order with large grand total matching PO and GRN"
    })
    hard_cases.append({
        "id": 85,
        "supplier_idx": 6,
        "category": "suspicious_looking_valid",
        "items": [{"name": "Standing Desk 120cm", "qty": 10, "inv_price": 12000.0, "po_price": 12000.0, "contract_price": 12000.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Valid invoice with round numbers that appears synthetic but is 100% correct"
    })
    hard_cases.append({
        "id": 86,
        "supplier_idx": 7,
        "category": "suspicious_looking_valid",
        "items": [{"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 1, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "verified", "expected_mistake": "none",
        "description": "Valid low-value single item invoice matching PO and GRN"
    })

    # --------------------------------------------------------------------------
    # 10. Compound double mistakes -> IDs 87 to 90
    # --------------------------------------------------------------------------
    hard_cases.append({
        "id": 87,
        "supplier_idx": 0,
        "category": "compound_double_mistake",
        "items": [{"name": "Ergonomic Office Chair", "qty": 25, "po_qty": 15, "grn_qty": 15, "inv_price": 5000.0, "po_price": 4500.0, "contract_price": 4500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 0.0,
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Compound error: simultaneous price mismatch and quantity mismatch"
    })
    hard_cases.append({
        "id": 88,
        "supplier_idx": 1,
        "category": "compound_double_mistake",
        "items": [{"name": "Wireless Keyboard & Mouse Combo", "qty": 10, "inv_price": 1800.0, "po_price": 1500.0, "contract_price": 1500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 2500.0,  # massive subtotal/grand total error
        "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
        "description": "Compound error: simultaneous unit price inflation and arithmetic calculation error"
    })
    hard_cases.append({
        "id": 89,
        "supplier_idx": 2,
        "category": "compound_double_mistake",
        "items": [{"name": "24-inch IPS Monitor", "qty": 10, "grn_qty": 6, "inv_price": 8500.0, "po_price": 8500.0, "contract_price": 8500.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.05, "round_diff": 0.0,  # quantity mismatch + 5% GST bug
        "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
        "description": "Compound error: simultaneous quantity overbilling and tax calculation error"
    })
    hard_cases.append({
        "id": 90,
        "supplier_idx": 3,
        "category": "compound_double_mistake",
        "missing_po": True,
        "items": [{"name": "Industrial Surge Protector Strip", "qty": 8, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0}],
        "po_tax_rate": 0.18, "inv_tax_rate": 0.18, "round_diff": 1200.0,  # missing PO + wrong total
        "expected_status": "needs_review", "expected_mistake": "missing_po",
        "description": "Compound error: missing PO reference and arithmetic total error"
    })

    # --------------------------------------------------------------------------
    # Database Population & PDF Generation
    # --------------------------------------------------------------------------
    ground_truth_rows = []

    for case in hard_cases:
        inv_id = case["id"]
        supplier = SUPPLIERS[case["supplier_idx"]]

        # Dates
        if "custom_inv_date" in case:
            inv_date = case["custom_inv_date"]
        elif "duplicate_of_id" in case:
            # Must match original invoice date exactly for duplicate
            inv_date = base_date + timedelta(days=(case["duplicate_of_id"] - 50) * 2)
        else:
            inv_date = base_date + timedelta(days=(inv_id - 50) * 2)

        due_date = inv_date + timedelta(days=supplier["payment_terms_days"])

        # Numbers
        po_number = f"PO-HARD-{inv_id:04d}"
        grn_number = f"GRN-HARD-{inv_id:04d}"
        inv_number = case.get("custom_inv_num", f"INV-HARD-{inv_id:04d}")

        file_name = f"INV_{inv_id:03d}.pdf"
        file_path = INVOICES_DIR / file_name

        # Calculate Invoiced items and PO items
        invoice_items_data = []
        po_items_data = []
        grn_items_data = []

        subtotal = 0.0
        po_subtotal = 0.0

        for item in case["items"]:
            name = item["name"]
            qty = item["qty"]
            inv_price = item["inv_price"]
            line_tot = round(qty * inv_price, 2)
            subtotal += line_tot

            invoice_items_data.append({
                "item_name": name,
                "quantity": qty,
                "unit_price": inv_price,
                "total_price": line_tot
            })

            po_q = item.get("po_qty", qty)
            po_p = item.get("po_price", inv_price)
            po_line_tot = round(po_q * po_p, 2)
            po_subtotal += po_line_tot
            po_items_data.append({
                "item_name": name,
                "quantity": po_q,
                "unit_price": po_p,
                "total_price": po_line_tot
            })

            grn_q = item.get("grn_qty", po_q)
            grn_items_data.append({
                "item_name": name,
                "quantity_received": grn_q
            })

        # Calculate taxes and grand total
        tax_rate = case.get("inv_tax_rate", 0.18)
        tax_amount = round(subtotal * tax_rate, 2)
        grand_total = round(subtotal + tax_amount + case.get("round_diff", 0.0), 2)

        # For duplicates, make sure grand_total matches duplicate_of_id exactly
        if "duplicate_of_id" in case:
            # find the duplicate case
            orig_case = next(c for c in hard_cases if c["id"] == case["duplicate_of_id"])
            orig_sub = sum(round(it["qty"] * it["inv_price"], 2) for it in orig_case["items"])
            orig_tax = round(orig_sub * orig_case.get("inv_tax_rate", 0.18), 2)
            grand_total = round(orig_sub + orig_tax + orig_case.get("round_diff", 0.0), 2)
            subtotal = orig_sub
            tax_amount = orig_tax

        # Render PDF
        is_missing_po = case.get("missing_po", False)
        displayed_po = "" if is_missing_po else po_number

        build_invoice_pdf(
            file_path=file_path,
            invoice_number=inv_number,
            invoice_date=str(inv_date),
            due_date=str(due_date),
            po_number=displayed_po,
            supplier=supplier,
            items=invoice_items_data,
            subtotal=subtotal,
            tax_amount=tax_amount,
            grand_total=grand_total
        )

        # DB Insertion: PO
        po_db = None
        if not is_missing_po:
            po_tax = round(po_subtotal * case.get("po_tax_rate", 0.18), 2)
            po_db = PurchaseOrder(
                id=inv_id,
                po_number=po_number,
                supplier_id=supplier["id"],
                order_date=inv_date - timedelta(days=5),
                total_amount=round(po_subtotal + po_tax, 2),
                status="approved"
            )
            # Remove any existing
            existing_po = db.query(PurchaseOrder).filter(PurchaseOrder.id == inv_id).first()
            if existing_po:
                db.delete(existing_po)
            db.add(po_db)
            db.flush()

            for it in po_items_data:
                db.add(POItem(
                    po_id=po_db.id,
                    item_name=it["item_name"],
                    quantity=it["quantity"],
                    unit_price=it["unit_price"],
                    total_price=it["total_price"]
                ))

            # DB Insertion: GRN
            grn_db = GoodsReceivedNote(
                id=inv_id,
                grn_number=grn_number,
                po_id=po_db.id,
                received_date=inv_date - timedelta(days=2),
                remarks="Delivered to Main Warehouse"
            )
            existing_grn = db.query(GoodsReceivedNote).filter(GoodsReceivedNote.id == inv_id).first()
            if existing_grn:
                db.delete(existing_grn)
            db.add(grn_db)
            db.flush()

            for it in grn_items_data:
                db.add(GRNItem(
                    grn_id=grn_db.id,
                    item_name=it["item_name"],
                    quantity_received=it["quantity_received"]
                ))

        # DB Insertion: Invoice
        existing_inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
        if existing_inv:
            db.delete(existing_inv)

        inv_db = Invoice(
            id=inv_id,
            invoice_number=inv_number,
            supplier_id=supplier["id"],
            po_id=po_db.id if po_db else None,
            invoice_date=inv_date,
            due_date=due_date,
            subtotal=subtotal,
            tax_amount=tax_amount,
            grand_total=grand_total,
            status="needs_review" if is_missing_po else "verified",
            file_path=str(file_path.relative_to(BASE_DIR))
        )
        db.add(inv_db)
        db.flush()

        for it in invoice_items_data:
            db.add(InvoiceItem(
                invoice_id=inv_db.id,
                item_name=it["item_name"],
                quantity=it["quantity"],
                unit_price=it["unit_price"],
                total_price=it["total_price"]
            ))

        # DB Insertion: Invoice Extraction
        extracted_payload = {
            "vendor": supplier["name"],
            "invoice_number": inv_number,
            "invoice_date": str(inv_date),
            "po_reference": displayed_po if displayed_po else None,
            "items": [
                {
                    "name": it["item_name"],
                    "quantity": it["quantity"],
                    "unit_price": it["unit_price"],
                    "total_price": it["total_price"]
                }
                for it in invoice_items_data
            ],
            "subtotal": subtotal,
            "gst_amount": tax_amount,
            "grand_total": grand_total,
            "confidence": 0.98,
            "is_success": True
        }

        existing_ext = db.query(InvoiceExtraction).filter(InvoiceExtraction.invoice_id == inv_id).first()
        if existing_ext:
            db.delete(existing_ext)

        db.add(InvoiceExtraction(
            invoice_id=inv_id,
            extracted_json=json.dumps(extracted_payload),
            confidence=0.98,
            model_name="mock-stress-test"
        ))

        # Add to ground truth
        ground_truth_rows.append({
            "invoice_id": inv_id,
            "invoice_file": file_name,
            "supplier_name": supplier["name"],
            "invoice_number": inv_number,
            "invoice_date": str(inv_date),
            "grand_total": grand_total,
            "expected_status": case["expected_status"],
            "expected_mistake": case["expected_mistake"],
            "description": case["description"]
        })

    db.commit()
    db.close()

    # Save to hard_ground_truth.csv
    hard_gt_csv = EVAL_DIR / "hard_ground_truth.csv"
    gt_df = pd.DataFrame(ground_truth_rows)
    gt_df.to_csv(hard_gt_csv, index=False)

    print(f"\nSuccessfully generated 40 hard invoices:")
    print(f"  - PDFs saved to: {INVOICES_DIR}")
    print(f"  - Database records seeded for IDs 51 to 90")
    print(f"  - Ground truth answer sheet: {hard_gt_csv}")
    print(f"  - Mistake distribution:")
    print(gt_df["expected_mistake"].value_counts().to_string())
    print("\nStatus distribution:")
    print(gt_df["expected_status"].value_counts().to_string())


if __name__ == "__main__":
    generate_hard_dataset()
