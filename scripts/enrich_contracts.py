"""Enriches the 8 master supplier contracts with Clauses 5-8 while preserving Clauses 1-4.
Ensures compliance with test_generator.py assertions.
"""
from pathlib import Path

CONTRACTS_DIR = Path("data/contracts")

CONTRACTS = {
    1: {
        "name": "Sharma Traders Pvt Ltd",
        "address": "12 Chandni Chowk Commercial Complex, Delhi 110006",
        "gstin": "07AAAAA1234A1Z5",
        "email": "billing@sharmatraders.in",
        "phone": "+91 98110 12345",
        "payment_terms": "Net 30 Days",
        "payment_days": 30,
        "warranty": "12 months comprehensive replacement warranty on all furniture and hardware. Defective items shall be replaced within 7 business days of written notice.",
        "late_penalty": "A penalty of 1% per week of delayed shipment value, capped at a maximum of 5% of the total purchase order value.",
        "early_discount": "2% cash discount on total invoice amount if payment is settled within 10 days of clean invoice receipt.",
        "dispute_amendment": "Clause 8. AMENDMENT AND PRICE REVISION\nEffective 2026-06-01, agreed unit price for 'High-Speed USB-C Dock' is revised from Rs. 3200.00 to Rs. 3500.00 under Addendum A. Arbitration under Delhi jurisdiction."
    },
    2: {
        "name": "Patel Enterprises",
        "address": "45 Ashram Road, Navrangpura, Ahmedabad, Gujarat 380009",
        "gstin": "24BBBBB5678B2Z6",
        "email": "accounts@patelenterprise.in",
        "phone": "+91 98250 23456",
        "payment_terms": "Net 30 Days",
        "payment_days": 30,
        "warranty": "12 months limited warranty on manufacturing defects only. Inspection and replacement completed within 14 calendar days.",
        "late_penalty": "A penalty of 0.5% per week of delay, capped at a maximum of 4% of the total purchase order value.",
        "early_discount": "No early payment discount is offered or permitted under any circumstances.",
        "dispute_amendment": "Clause 8. JURISDICTION & DISPUTE RESOLUTION\nGoverned by the Indian Contract Act, 1872 with exclusive arbitration jurisdiction in Ahmedabad, Gujarat."
    },
    3: {
        "name": "Reddy Logistics & Supplies",
        "address": "88 Cyber Towers, Madhapur, Hyderabad, Telangana 500081",
        "gstin": "36CCCCC9012C3Z7",
        "email": "finance@reddylogistics.in",
        "phone": "+91 98480 34567",
        "payment_terms": "Net 45 Days",
        "payment_days": 45,
        "warranty": "6 months standard warranty on logistics, cabling, and office consumable supplies.",
        "late_penalty": "A penalty of 1.5% per week of delay, capped at 6% of the purchase order value.",
        "early_discount": "1% cash discount applicable if invoice is settled within 15 days of verified delivery.",
        "dispute_amendment": "Clause 8. JURISDICTION & DISPUTE RESOLUTION\nSubject to arbitration under Hyderabad, Telangana jurisdiction."
    },
    4: {
        "name": "Mehta Industrial Solutions",
        "address": "102 Industrial Suburb, Peenya 2nd Stage, Bangalore, Karnataka 560058",
        "gstin": "29DDDDD3456D4Z8",
        "email": "invoicing@mehtaindustrial.in",
        "phone": "+91 98450 45678",
        "payment_terms": "Net 30 Days",
        "payment_days": 30,
        "warranty": "18 months standard warranty on industrial surge protectors and standing desks. On-site support within 48 hours in Bengaluru.",
        "late_penalty": "A penalty of 1.0% per week of delay, capped at 5% of PO value.",
        "early_discount": "1.5% cash discount for payment received within 7 days of invoice submission.",
        "dispute_amendment": "Clause 8. JURISDICTION & DISPUTE RESOLUTION\nArbitration venue in Bengaluru, Karnataka under the Indian Arbitration and Conciliation Act."
    },
    5: {
        "name": "Gupta Office Essentials",
        "address": "56 Park Street, Commercial Area, Kolkata, West Bengal 700016",
        "gstin": "19EEEEE7890E5Z9",
        "email": "billing@guptaoffice.in",
        "phone": "+91 98310 56789",
        "payment_terms": "Net 30 Days",
        "payment_days": 30,
        "warranty": "12 months carry-in warranty for office paper, stationery, and small office electronics.",
        "late_penalty": "A penalty of 2% per week of delayed shipment, capped at 10% of PO amount.",
        "early_discount": "No early payment discount permitted or recognized.",
        "dispute_amendment": "Clause 8. JURISDICTION & DISPUTE RESOLUTION\nArbitration jurisdiction in Kolkata, West Bengal."
    },
    6: {
        "name": "Verma Tech Components",
        "address": "23 Electronics Zone, MIDC Bhosari, Pune, Maharashtra 411026",
        "gstin": "27FFFFF1234F6Z1",
        "email": "orders@vermatech.in",
        "phone": "+91 98220 67890",
        "payment_terms": "Net 30 Days",
        "payment_days": 30,
        "warranty": "24 months extended warranty on microchips, video webcams, and electronic hardware components. Free repair or replacement.",
        "late_penalty": "A penalty of 1% per week of delay, capped at 5% of purchase order value.",
        "early_discount": "2% cash discount if payment is released within 10 days of clean invoice receipt.",
        "dispute_amendment": "Clause 8. JURISDICTION & DISPUTE RESOLUTION\nDisputes settled via sole arbitrator in Pune, Maharashtra."
    },
    7: {
        "name": "Nair & Company",
        "address": "77 Nariman Point, Marine Drive, Mumbai, Maharashtra 400021",
        "gstin": "27GGGGG5678G7Z2",
        "email": "contact@naircompany.in",
        "phone": "+91 98200 78901",
        "payment_terms": "Net 30 Days",
        "payment_days": 30,
        "warranty": "12 months standard replacement warranty on all supplied commercial goods.",
        "late_penalty": "A penalty of 0.75% per week of delay, capped at 5% of purchase order value.",
        "early_discount": "No early payment cash discount applicable under this agreement.",
        "dispute_amendment": "Clause 8. JURISDICTION & DISPUTE RESOLUTION\nArbitration jurisdiction in Mumbai, Maharashtra."
    },
    8: {
        "name": "Singh & Sons Equipment",
        "address": "19 Focal Point, GT Road, Ludhiana, Punjab 141010",
        "gstin": "03HHHHH9012H8Z3",
        "email": "accounts@singhandsons.in",
        "phone": "+91 98140 89012",
        "payment_terms": "Net 60 Days",
        "payment_days": 60,
        "warranty": "36 months industrial heavy-duty warranty on equipment and furniture. Free replacement parts and on-site service included.",
        "late_penalty": "A penalty of 2% per week of delay, capped at 10% of purchase order amount.",
        "early_discount": "3% cash discount for payment cleared within 14 days of invoice approval.",
        "dispute_amendment": "Clause 8. JURISDICTION & DISPUTE RESOLUTION\nArbitration venue in Ludhiana / Chandigarh under the Indian Contract Act."
    }
}

PRODUCTS = [
    ("Ergonomic Office Chair", 4500.0),
    ("Standing Desk 120cm", 12000.0),
    ("Wireless Keyboard & Mouse Combo", 1500.0),
    ("24-inch IPS Monitor", 8500.0),
    ("High-Speed USB-C Dock", 3200.0),
    ("A4 Copier Paper (Box of 5 Reams)", 1100.0),
    ("Cat6 Network Cable (305m Roll)", 4200.0),
    ("Industrial Surge Protector Strip", 1800.0),
    ("HD 1080p Video Conferencing Webcam", 2600.0),
    ("Active Noise-Cancelling Headset", 3800.0)
]

def main():
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for supp_id, s in CONTRACTS.items():
        file_path = CONTRACTS_DIR / f"contract_supplier_{supp_id}.txt"
        
        lines = [
            "=" * 80,
            "                    MASTER VENDOR SUPPLY AGREEMENT",
            "=" * 80,
            f"Supplier: {s['name']}",
            f"Address:  {s['address']}",
            f"GSTIN:    {s['gstin']}",
            f"Email:    {s['email']} | Phone: {s['phone']}",
            f"Payment Terms: {s['payment_terms']}",
            "Agreement Date: 2026-01-01",
            "Jurisdiction: Indian Contract Act, 1872",
            "",
            "1. SCOPE AND PRICING",
            "The Supplier agrees to deliver the following items at the agreed fixed unit rates.",
            "All rates are denominated in Rs. (Indian Rupees).",
            "",
            f"{'Item Name':<42} {'Agreed Unit Price':<20}",
            "-" * 65
        ]
        
        for item_name, price in PRODUCTS:
            lines.append(f"{item_name:<42} Rs. {price:>10.2f}")
            
        lines.extend([
            "",
            "2. TAXATION & GST CLAUSE",
            "All listed prices are exclusive of Goods and Services Tax (GST).",
            "A standard GST rate of 18% (comprising 9% CGST and 9% SGST) shall apply to all",
            "tax invoices. Valid GSTIN of both the supplier and buyer must appear on invoices.",
            "",
            "3. DELIVERY & ACCEPTANCE",
            "Goods will only be deemed received upon verification by warehouse staff and",
            "issuance of a valid Goods Received Note (GRN). Invoices must match the approved",
            "Purchase Order (PO) and GRN quantities.",
            "",
            "4. PAYMENT TERMS",
            f"Payment shall be released within {s['payment_days']} days from the date of receipt",
            "of a verified and clean invoice. Any invoice containing discrepancies will be",
            "placed on hold with status 'needs_review' or 'mismatch_detected'.",
            "",
            "5. WARRANTY AND DEFECT LIABILITY",
            s["warranty"],
            "",
            "6. LATE DELIVERY PENALTY",
            s["late_penalty"],
            "",
            "7. EARLY PAYMENT CASH DISCOUNT",
            s["early_discount"],
            "",
            s["dispute_amendment"],
            "",
            f"{'Authorized Signatory,':<35} {'Authorized Signatory,':<35}",
            f"{s['name']:<35} {'VouchFlow AI Corporate Finance':<35}",
            ""
        ])
        
        content = "\n".join(lines)
        file_path.write_text(content, encoding="utf-8")
        print(f"Updated {file_path.name} ({len(content)} bytes)")

if __name__ == "__main__":
    main()
