"""
Database Seeder for VouchFlow AI
================================
Populates the database with:
- 8 Suppliers
- Master Contracts for each supplier and product
- 50 Purchase Orders (with line items)
- 50 Goods Received Notes (with line items)
- 50 Invoices (with line items and assigned initial statuses)
- Initial system audit log

Idempotent: Can be run multiple times safely by wiping and refreshing tables.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, date

# Ensure project root is in sys.path so 'backend' can be imported
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.database.db import engine, SessionLocal, init_db, Base

from backend.database.models import (
    Supplier,
    Contract,
    PurchaseOrder,
    POItem,
    GoodsReceivedNote,
    GRNItem,
    Invoice,
    InvoiceItem,
    AuditLog
)

BASE_DIR = Path(__file__).resolve().parent.parent
MOCK_DATA_PATH = BASE_DIR / "data" / "evaluation" / "mock_data.json"


def seed_database():
    """Reads generated mock data and populates SQLite/PostgreSQL database."""
    print("--- Starting Database Seeder ---")

    # Ensure tables exist
    init_db()

    # If mock_data.json doesn't exist yet, run generator first
    if not MOCK_DATA_PATH.exists():
        print("Mock data file not found. Running generate_data.py first...")
        from scripts.generate_data import generate_contracts, generate_dataset
        generate_contracts()
        generate_dataset()

    with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()
    try:
        # Clear existing records in proper dependency order
        print("Clearing existing database records for a fresh seed...")
        db.query(AuditLog).delete()
        db.query(InvoiceItem).delete()
        db.query(Invoice).delete()
        db.query(GRNItem).delete()
        db.query(GoodsReceivedNote).delete()
        db.query(POItem).delete()
        db.query(PurchaseOrder).delete()
        db.query(Contract).delete()
        db.query(Supplier).delete()
        db.commit()

        # 1. Insert Suppliers
        print(f"Inserting {len(data['suppliers'])} suppliers...")
        supplier_map = {}
        for s in data["suppliers"]:
            supplier = Supplier(
                id=s["id"],
                name=s["name"],
                contact_email=s["email"],
                phone=s["phone"],
                address=s["address"],
                gstin=s["gstin"]
            )
            db.add(supplier)
            supplier_map[s["id"]] = supplier
        db.commit()

        # 2. Insert Master Contracts (agreed prices for 10 products per supplier)
        print("Inserting supplier master contracts...")
        contract_count = 0
        for s in data["suppliers"]:
            for p in data["products"]:
                contract = Contract(
                    supplier_id=s["id"],
                    item_name=p["name"],
                    agreed_unit_price=p["agreed_price"],
                    payment_terms_days=s["payment_terms_days"],
                    terms_text=f"Standard master pricing agreement for {p['name']} at Rs. {p['agreed_price']:.2f}"
                )
                db.add(contract)
                contract_count += 1
        db.commit()

        # 3. Insert Purchase Orders & Items
        print(f"Inserting {len(data['purchase_orders'])} purchase orders...")
        for po_data in data["purchase_orders"]:
            po = PurchaseOrder(
                id=po_data["id"],
                po_number=po_data["po_number"],
                supplier_id=po_data["supplier_id"],
                order_date=datetime.strptime(po_data["order_date"], "%Y-%m-%d").date(),
                status=po_data["status"],
                total_amount=po_data["total_amount"]
            )
            db.add(po)
            db.flush()  # Acquire PO id

            for item_data in po_data["items"]:
                po_item = POItem(
                    po_id=po.id,
                    item_name=item_data["item_name"],
                    quantity=item_data["quantity"],
                    unit_price=item_data["unit_price"],
                    total_price=item_data["total_price"]
                )
                db.add(po_item)
        db.commit()

        # 4. Insert Goods Received Notes (GRN) & Items
        print(f"Inserting {len(data['goods_received_notes'])} goods received notes...")
        for grn_data in data["goods_received_notes"]:
            grn = GoodsReceivedNote(
                id=grn_data["id"],
                grn_number=grn_data["grn_number"],
                po_id=grn_data["po_id"],
                received_date=datetime.strptime(grn_data["received_date"], "%Y-%m-%d").date(),
                received_by=grn_data["received_by"],
                remarks=grn_data["remarks"]
            )
            db.add(grn)
            db.flush()

            for item_data in grn_data["items"]:
                grn_item = GRNItem(
                    grn_id=grn.id,
                    item_name=item_data["item_name"],
                    quantity_received=item_data["quantity_received"]
                )
                db.add(grn_item)
        db.commit()

        # 5. Insert Invoices & Items
        print(f"Inserting {len(data['invoices'])} invoices...")
        for inv_data in data["invoices"]:
            inv = Invoice(
                id=inv_data["id"],
                invoice_number=inv_data["invoice_number"],
                supplier_id=inv_data["supplier_id"],
                po_id=inv_data["po_id"],
                invoice_date=datetime.strptime(inv_data["invoice_date"], "%Y-%m-%d").date(),
                due_date=datetime.strptime(inv_data["due_date"], "%Y-%m-%d").date(),
                subtotal=inv_data["subtotal"],
                tax_amount=inv_data["tax_amount"],
                grand_total=inv_data["grand_total"],
                file_path=inv_data["file_path"],
                status=inv_data["status"]
            )
            db.add(inv)
            db.flush()

            for item_data in inv_data["items"]:
                inv_item = InvoiceItem(
                    invoice_id=inv.id,
                    item_name=item_data["item_name"],
                    quantity=item_data["quantity"],
                    unit_price=item_data["unit_price"],
                    total_price=item_data["total_price"]
                )
                db.add(inv_item)
        db.commit()

        # 6. Add Audit Log entry for the database seeding
        audit_log = AuditLog(
            who="system_seeder",
            action="database_seed",
            details="Database populated with 8 suppliers, 80 contracts, 50 POs, 50 GRNs, and 50 Invoices."
        )
        db.add(audit_log)
        db.commit()

        # Summary count check
        print("\n--- Seeding Successfully Finished ---")
        print(f"Suppliers:            {db.query(Supplier).count()}")
        print(f"Contracts:            {db.query(Contract).count()}")
        print(f"Purchase Orders:      {db.query(PurchaseOrder).count()}")
        print(f"PO Line Items:        {db.query(POItem).count()}")
        print(f"Goods Received Notes: {db.query(GoodsReceivedNote).count()}")
        print(f"GRN Line Items:       {db.query(GRNItem).count()}")
        print(f"Invoices:             {db.query(Invoice).count()}")
        print(f"Invoice Line Items:   {db.query(InvoiceItem).count()}")
        print(f"Audit Logs:           {db.query(AuditLog).count()}")

    except Exception as e:
        db.rollback()
        print(f"Error during seeding: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
