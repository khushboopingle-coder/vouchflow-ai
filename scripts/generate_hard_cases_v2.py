"""
Hard Test Cases Generator v2 for VouchFlow AI (30 New Adversarial Invoices)
============================================================================
Generates 30 new, challenging invoices (IDs 91 to 120) with seed 2026 and
a diverse mix of subtle discrepancies and edge cases:
- Tiny price differences (Rs. 0.50, 1.5% markup)
- PO vs Contract price conflicts (negotiated discounts, outdated contracts)
- Delivery discrepancies (partial shipments, unauthorized over-delivery)
- Multi-item invoices (5-6 items) with single buried discrepancies
- Commercial rounding boundary tests (Rs. 0.35, Rs. 0.65, Rs. 0.99 vs Rs. 1.05, Rs. 1.85)
- GST tax rate errors (12%, 5%, 9%)
- Disguised duplicates (reformatted/revised numbering)
- Cross-supplier numbering collisions (same number from different vendors)
- Suspicious looking valid invoices (Sunday dates, bulk orders)
- Compound double mistakes (price+qty, price+math, qty+tax, missing_po+math)
- Missing PO references

Outputs:
- 30 PDF invoices in data/invoices/ (INV_091.pdf to INV_120.pdf)
- Database records in vouchflow.db (POs, GRNs, Invoices, Line Items, Extractions)
- Answer sheet in data/evaluation/hard_ground_truth_v2.csv
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

# Master Suppliers Catalog
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
    grand_total: float
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
        "<b>Terms & Conditions:</b> Payment subject to verification of PO and warehouse GRN receipts.",
        subtitle_style
    )
    story.append(terms_para)
    doc.build(story)


def generate_hard_dataset_v2():
    """Generates 30 new hard invoices (IDs 91 to 120) with random seed 2026."""
    print("Generating 30 New Hard Test Cases (IDs 91 to 120, Seed: 2026)...")
    random.seed(2026)
    init_db()
    db = SessionLocal()

    base_date = date(2026, 4, 1)

    hard_cases: List[Dict[str, Any]] = [
        # 1. Tiny price differences
        {
            "id": 91, "supplier_idx": 0, "category": "tiny_price_difference",
            "items": [{"name": "Ergonomic Office Chair", "qty": 8, "inv_price": 4500.50, "po_price": 4500.0, "contract_price": 4500.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
            "description": "Invoiced unit price is Rs. 0.50 higher than PO and contract rate"
        },
        {
            "id": 92, "supplier_idx": 1, "category": "tiny_price_difference",
            "items": [{"name": "Standing Desk 120cm", "qty": 5, "inv_price": 12180.00, "po_price": 12000.0, "contract_price": 12000.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
            "description": "Invoiced unit price has a 1.5% markup over PO and contract"
        },

        # 2. PO vs Contract price conflicts
        {
            "id": 93, "supplier_idx": 2, "category": "po_vs_contract_price",
            "items": [{"name": "Wireless Keyboard & Mouse Combo", "qty": 15, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1500.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
            "description": "Invoice price matches PO (Rs. 1800) but violates contract agreed price (Rs. 1500)"
        },
        {
            "id": 94, "supplier_idx": 3, "category": "po_vs_contract_price",
            "items": [{"name": "24-inch IPS Monitor", "qty": 6, "inv_price": 8500.0, "po_price": 8000.0, "contract_price": 8500.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
            "description": "Invoice price matches Contract (Rs. 8500) but ignores negotiated PO discount (Rs. 8000)"
        },

        # 3. Clean invoice
        {
            "id": 95, "supplier_idx": 4, "category": "clean_match",
            "items": [
                {"name": "High-Speed USB-C Dock", "qty": 6, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0},
                {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 12, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0}
            ],
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Pristine multi-item invoice perfectly matching PO, GRN, and Contract"
        },

        # 4. Delivery discrepancies
        {
            "id": 96, "supplier_idx": 5, "category": "delivery_discrepancy",
            "items": [{"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 40, "grn_qty": 28, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
            "description": "Partial delivery: invoice bills for 40 units but warehouse GRN confirmed 28"
        },
        {
            "id": 97, "supplier_idx": 6, "category": "delivery_discrepancy",
            "items": [{"name": "Cat6 Network Cable (305m Roll)", "qty": 18, "po_qty": 12, "grn_qty": 18, "inv_price": 4200.0, "po_price": 4200.0, "contract_price": 4200.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
            "description": "Over-delivery: invoice bills 18 units exceeding PO authorized limit of 12"
        },
        {
            "id": 98, "supplier_idx": 7, "category": "delivery_discrepancy",
            "items": [{"name": "Industrial Surge Protector Strip", "qty": 30, "po_qty": 25, "grn_qty": 25, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
            "description": "Quantity overbilling: invoice bills 30 units while PO and GRN both authorized 25"
        },

        # 5. Multi-item single error
        {
            "id": 99, "supplier_idx": 0, "category": "multi_item_single_error",
            "items": [
                {"name": "Ergonomic Office Chair", "qty": 2, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0},
                {"name": "Standing Desk 120cm", "qty": 1, "inv_price": 12000.0, "po_price": 12000.0, "contract_price": 12000.0},
                {"name": "Wireless Keyboard & Mouse Combo", "qty": 4, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0},
                {"name": "HD 1080p Video Conferencing Webcam", "qty": 3, "inv_price": 2950.0, "po_price": 2600.0, "contract_price": 2600.0},  # faulty item 4
                {"name": "High-Speed USB-C Dock", "qty": 2, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0},
                {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 5, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0}
            ],
            "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
            "description": "6-item invoice where single item #4 has an inflated unit price"
        },
        {
            "id": 100, "supplier_idx": 1, "category": "multi_item_single_error",
            "items": [
                {"name": "24-inch IPS Monitor", "qty": 4, "inv_price": 8500.0, "po_price": 8500.0, "contract_price": 8500.0},
                {"name": "High-Speed USB-C Dock", "qty": 3, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0},
                {"name": "Wireless Keyboard & Mouse Combo", "qty": 14, "grn_qty": 8, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0},  # faulty item 3
                {"name": "Industrial Surge Protector Strip", "qty": 2, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0},
                {"name": "Active Noise-Cancelling Headset", "qty": 2, "inv_price": 3800.0, "po_price": 3800.0, "contract_price": 3800.0}
            ],
            "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
            "description": "5-item invoice where middle item #3 has a quantity shortage on GRN"
        },

        # 6. Commercial rounding tolerances (Accepted <= 1.00 vs Rejected > 1.00)
        {
            "id": 101, "supplier_idx": 2, "category": "rounding_acceptable",
            "items": [
                {"name": "Active Noise-Cancelling Headset", "qty": 3, "inv_price": 3800.0, "po_price": 3800.0, "contract_price": 3800.0},
                {"name": "High-Speed USB-C Dock", "qty": 2, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0}
            ],
            "round_diff": 0.35,  # within 1.00
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Commercial rounding difference of +Rs. 0.35 accepted within tolerance"
        },
        {
            "id": 102, "supplier_idx": 3, "category": "rounding_acceptable",
            "items": [{"name": "Cat6 Network Cable (305m Roll)", "qty": 4, "inv_price": 4200.0, "po_price": 4200.0, "contract_price": 4200.0}],
            "round_diff": -0.65,  # within 1.00
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Commercial round-off adjustment of -Rs. 0.65 accepted within tolerance"
        },
        {
            "id": 103, "supplier_idx": 4, "category": "rounding_excessive",
            "items": [{"name": "Standing Desk 120cm", "qty": 3, "inv_price": 12000.0, "po_price": 12000.0, "contract_price": 12000.0}],
            "round_diff": 1.85,  # EXCEEDS 1.00 tolerance
            "expected_status": "mismatch_detected", "expected_mistake": "wrong_total",
            "description": "Mathematical calculation discrepancy of Rs. 1.85 exceeding rounding tolerance"
        },

        # 7. GST calculation errors
        {
            "id": 104, "supplier_idx": 5, "category": "wrong_gst_rate",
            "items": [{"name": "24-inch IPS Monitor", "qty": 4, "inv_price": 8500.0, "po_price": 8500.0, "contract_price": 8500.0}],
            "inv_tax_rate": 0.12,  # 12% instead of 18%
            "expected_status": "mismatch_detected", "expected_mistake": "wrong_total",
            "description": "GST calculated at incorrect rate of 12% instead of standard 18%"
        },
        {
            "id": 105, "supplier_idx": 6, "category": "wrong_gst_rate",
            "items": [{"name": "HD 1080p Video Conferencing Webcam", "qty": 8, "inv_price": 2600.0, "po_price": 2600.0, "contract_price": 2600.0}],
            "inv_tax_rate": 0.05,  # 5% instead of 18%
            "expected_status": "mismatch_detected", "expected_mistake": "wrong_total",
            "description": "GST calculated at incorrect rate of 5% instead of standard 18%"
        },

        # 8. Clean invoice with round amounts
        {
            "id": 106, "supplier_idx": 7, "category": "clean_match",
            "items": [{"name": "Standing Desk 120cm", "qty": 5, "inv_price": 12000.0, "po_price": 12000.0, "contract_price": 12000.0}],
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Clean invoice with round figures matching PO and GRN"
        },

        # 9. Disguised duplicates
        {
            "id": 107, "supplier_idx": 4, "category": "disguised_duplicate",
            "duplicate_of_id": 95, "custom_inv_num": "INV-HARD-0095-REV",
            "items": [
                {"name": "High-Speed USB-C Dock", "qty": 6, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0},
                {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 12, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0}
            ],
            "expected_status": "mismatch_detected", "expected_mistake": "duplicate_invoice",
            "description": "Duplicate invoice: revised invoice number with identical supplier, date, and amount"
        },
        {
            "id": 108, "supplier_idx": 7, "category": "disguised_duplicate",
            "duplicate_of_id": 106, "custom_inv_num": "DUP/2026/0106",
            "items": [{"name": "Standing Desk 120cm", "qty": 5, "inv_price": 12000.0, "po_price": 12000.0, "contract_price": 12000.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "duplicate_invoice",
            "description": "Duplicate invoice: re-numbered submission with identical supplier, date, and grand total"
        },

        # 10. Cross-supplier numbering collisions (Valid / NOT duplicate)
        {
            "id": 109, "supplier_idx": 2, "category": "cross_supplier_collision",
            "custom_inv_num": "INV-V2-SHARED-01",
            "items": [{"name": "Wireless Keyboard & Mouse Combo", "qty": 10, "inv_price": 1500.0, "po_price": 1500.0, "contract_price": 1500.0}],
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Valid invoice using shared format INV-V2-SHARED-01 from Supplier 3"
        },
        {
            "id": 110, "supplier_idx": 4, "category": "cross_supplier_collision",  # Different supplier
            "custom_inv_num": "INV-V2-SHARED-01",
            "items": [{"name": "Industrial Surge Protector Strip", "qty": 6, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0}],
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Valid invoice using shared format INV-V2-SHARED-01 from Supplier 5 (NOT a duplicate)"
        },

        # 11. Suspicious-looking but valid invoices
        {
            "id": 111, "supplier_idx": 0, "category": "suspicious_looking_valid",
            "custom_inv_date": date(2026, 4, 19),  # Sunday
            "items": [{"name": "Ergonomic Office Chair", "qty": 6, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0}],
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Valid weekend/Sunday invoice fully authorized by PO schedule"
        },
        {
            "id": 112, "supplier_idx": 1, "category": "suspicious_looking_valid",
            "items": [{"name": "Ergonomic Office Chair", "qty": 200, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0}],
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Valid massive bulk order with large grand total matching PO and GRN"
        },

        # 12. Compound double mistakes (testing priority order)
        {
            "id": 113, "supplier_idx": 2, "category": "compound_double_mistake",
            "items": [{"name": "Standing Desk 120cm", "qty": 10, "po_qty": 6, "grn_qty": 6, "inv_price": 13000.0, "po_price": 12000.0, "contract_price": 12000.0}],
            "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
            "description": "Compound error: simultaneous price mismatch and quantity mismatch (priority: price_mismatch)"
        },
        {
            "id": 114, "supplier_idx": 3, "category": "compound_double_mistake",
            "items": [{"name": "Active Noise-Cancelling Headset", "qty": 8, "inv_price": 4200.0, "po_price": 3800.0, "contract_price": 3800.0}],
            "round_diff": 3000.0,  # massive subtotal/grand total calculation error
            "expected_status": "mismatch_detected", "expected_mistake": "price_mismatch",
            "description": "Compound error: simultaneous price mismatch and arithmetic calculation error (priority: price_mismatch)"
        },
        {
            "id": 115, "supplier_idx": 4, "category": "compound_double_mistake",
            "items": [{"name": "24-inch IPS Monitor", "qty": 12, "grn_qty": 7, "inv_price": 8500.0, "po_price": 8500.0, "contract_price": 8500.0}],
            "inv_tax_rate": 0.09,  # quantity mismatch + SGST omitted tax error
            "expected_status": "mismatch_detected", "expected_mistake": "quantity_mismatch",
            "description": "Compound error: simultaneous quantity shortage and tax calculation error (priority: quantity_mismatch)"
        },
        {
            "id": 116, "supplier_idx": 5, "category": "compound_double_mistake",
            "missing_po": True,
            "items": [{"name": "High-Speed USB-C Dock", "qty": 5, "inv_price": 3200.0, "po_price": 3200.0, "contract_price": 3200.0}],
            "round_diff": 1500.0,  # missing PO + arithmetic total error
            "expected_status": "needs_review", "expected_mistake": "missing_po",
            "description": "Compound error: missing PO reference and arithmetic total error (priority: missing_po -> needs_review)"
        },

        # 13. Missing PO reference
        {
            "id": 117, "supplier_idx": 6, "category": "missing_po",
            "missing_po": True,
            "items": [{"name": "Cat6 Network Cable (305m Roll)", "qty": 3, "inv_price": 4200.0, "po_price": 4200.0, "contract_price": 4200.0}],
            "expected_status": "needs_review", "expected_mistake": "missing_po",
            "description": "Invoice missing PO reference on otherwise pristine billing"
        },

        # 14. Clean invoice
        {
            "id": 118, "supplier_idx": 7, "category": "clean_match",
            "items": [
                {"name": "A4 Copier Paper (Box of 5 Reams)", "qty": 15, "inv_price": 1100.0, "po_price": 1100.0, "contract_price": 1100.0},
                {"name": "Industrial Surge Protector Strip", "qty": 5, "inv_price": 1800.0, "po_price": 1800.0, "contract_price": 1800.0}
            ],
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Clean 2-item invoice matching PO and GRN perfectly"
        },

        # 15. Fine-grained Sub-Rupee Boundary Tests (Rs. 0.99 vs Rs. 1.05)
        {
            "id": 119, "supplier_idx": 0, "category": "sub_rupee_boundary_pass",
            "items": [{"name": "Ergonomic Office Chair", "qty": 4, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0}],
            "round_diff": 0.99,  # Just within Rs. 1.00 tolerance
            "expected_status": "verified", "expected_mistake": "none",
            "description": "Commercial rounding difference of +Rs. 0.99 (just within Rs. 1.00 tolerance)"
        },
        {
            "id": 120, "supplier_idx": 1, "category": "sub_rupee_boundary_fail",
            "items": [{"name": "Ergonomic Office Chair", "qty": 4, "inv_price": 4500.0, "po_price": 4500.0, "contract_price": 4500.0}],
            "round_diff": 1.05,  # Exceeds Rs. 1.00 tolerance by 5 paise
            "expected_status": "mismatch_detected", "expected_mistake": "wrong_total",
            "description": "Discrepancy of Rs. 1.05 exceeding rounding tolerance by 5 paise"
        }
    ]

    ground_truth_rows = []

    for case in hard_cases:
        inv_id = case["id"]
        supplier = SUPPLIERS[case["supplier_idx"]]

        # Dates
        if "custom_inv_date" in case:
            inv_date = case["custom_inv_date"]
        elif "duplicate_of_id" in case:
            inv_date = base_date + timedelta(days=(case["duplicate_of_id"] - 90) * 2)
        else:
            inv_date = base_date + timedelta(days=(inv_id - 90) * 2)

        due_date = inv_date + timedelta(days=supplier["payment_terms_days"])

        po_number = f"PO-V2-{inv_id:04d}"
        grn_number = f"GRN-V2-{inv_id:04d}"
        inv_number = case.get("custom_inv_num", f"INV-V2-{inv_id:04d}")

        file_name = f"INV_{inv_id:03d}.pdf"
        file_path = INVOICES_DIR / file_name

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

        tax_rate = case.get("inv_tax_rate", 0.18)
        tax_amount = round(subtotal * tax_rate, 2)
        grand_total = round(subtotal + tax_amount + case.get("round_diff", 0.0), 2)

        if "duplicate_of_id" in case:
            orig_case = next(c for c in hard_cases if c["id"] == case["duplicate_of_id"])
            orig_sub = sum(round(it["qty"] * it["inv_price"], 2) for it in orig_case["items"])
            orig_tax = round(orig_sub * orig_case.get("inv_tax_rate", 0.18), 2)
            grand_total = round(orig_sub + orig_tax + orig_case.get("round_diff", 0.0), 2)
            subtotal = orig_sub
            tax_amount = orig_tax

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
                remarks="Delivered to Warehouse"
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
            model_name="mock-stress-test-v2"
        ))

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

    hard_gt_csv = EVAL_DIR / "hard_ground_truth_v2.csv"
    gt_df = pd.DataFrame(ground_truth_rows)
    gt_df.to_csv(hard_gt_csv, index=False)

    print(f"\nSuccessfully generated 30 new hard invoices (IDs 91 to 120):")
    print(f"  - PDFs saved to: {INVOICES_DIR}")
    print(f"  - Database records seeded for IDs 91 to 120")
    print(f"  - Ground truth answer sheet: {hard_gt_csv}")
    print(f"  - Mistake distribution:")
    print(gt_df["expected_mistake"].value_counts().to_string())
    print("\nStatus distribution:")
    print(gt_df["expected_status"].value_counts().to_string())


if __name__ == "__main__":
    generate_hard_dataset_v2()
