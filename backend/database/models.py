"""
SQLAlchemy ORM Models for VouchFlow AI
Defines database tables:
- suppliers: Vendor details
- purchase_orders & po_items: Internal approved orders
- goods_received_notes & grn_items: Warehouse physical delivery receipts
- invoices & invoice_items: Vendor bills for payment
- contracts: Master price agreement per supplier and item
- invoice_extractions: Stored AI/OCR extracted data per invoice
- audit_logs: Tracking of user/system actions
- users & workspaces (Phase 2): login accounts; every user owns one private workspace.
  workspace_id on suppliers, contracts, purchase_orders, goods_received_notes,
  invoices, invoice_decisions and audit_logs. Child rows (line items, extractions,
  checks, investigations) belong to the workspace of their parent row.
"""

from datetime import datetime, date
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from backend.database.db import Base


class Supplier(Base):
    """Stores vendor / supplier company profile."""
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True, index=True)  # owner workspace
    name = Column(String(255), nullable=False, index=True)
    contact_email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    gstin = Column(String(50), nullable=True)  # Indian GST Identification Number
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    purchase_orders = relationship("PurchaseOrder", back_populates="supplier", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="supplier")
    contracts = relationship("Contract", back_populates="supplier", cascade="all, delete-orphan")


class PurchaseOrder(Base):
    """Stores Purchase Orders issued to suppliers."""
    __tablename__ = "purchase_orders"
    # PO numbers are unique per workspace (two companies may both have "PO-2026-0001")
    __table_args__ = (UniqueConstraint("workspace_id", "po_number", name="uq_purchase_orders_workspace_po_number"),)

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True, index=True)  # owner workspace
    po_number = Column(String(100), index=True, nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    order_date = Column(Date, default=date.today, nullable=False)
    status = Column(String(50), default="issued", nullable=False)  # issued, fulfilled, cancelled
    total_amount = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    supplier = relationship("Supplier", back_populates="purchase_orders")
    items = relationship("POItem", back_populates="purchase_order", cascade="all, delete-orphan")
    goods_received_notes = relationship("GoodsReceivedNote", back_populates="purchase_order")
    invoices = relationship("Invoice", back_populates="purchase_order")


class POItem(Base):
    """Line items for a Purchase Order."""
    __tablename__ = "po_items"

    id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    item_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="items")


class GoodsReceivedNote(Base):
    """Stores warehouse physical receipt confirmation (GRN)."""
    __tablename__ = "goods_received_notes"
    # GRN numbers are unique per workspace
    __table_args__ = (UniqueConstraint("workspace_id", "grn_number", name="uq_goods_received_notes_workspace_grn_number"),)

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True, index=True)  # owner workspace
    grn_number = Column(String(100), index=True, nullable=False)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    received_date = Column(Date, default=date.today, nullable=False)
    received_by = Column(String(100), nullable=True)  # Warehouse staff name
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="goods_received_notes")
    items = relationship("GRNItem", back_populates="goods_received_note", cascade="all, delete-orphan")


class GRNItem(Base):
    """Physical quantity received per item in warehouse."""
    __tablename__ = "grn_items"

    id = Column(Integer, primary_key=True, index=True)
    grn_id = Column(Integer, ForeignKey("goods_received_notes.id"), nullable=False)
    item_name = Column(String(255), nullable=False)
    quantity_received = Column(Integer, nullable=False)

    # Relationships
    goods_received_note = relationship("GoodsReceivedNote", back_populates="items")


class Invoice(Base):
    """
    Stores supplier bills / invoices.
    Allowed status values:
    - 'verified': Clean match across Invoice, PO, GRN, and Contract
    - 'needs_review': Newly uploaded or flagged for human inspection
    - 'mismatch_detected': Discrepancy in price, quantity, or total
    - 'pending_approval': Ready for finance manager sign-off
    """
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True, index=True)  # owner workspace
    invoice_number = Column(String(100), index=True, nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    invoice_date = Column(Date, default=date.today, nullable=True)
    due_date = Column(Date, nullable=True)
    subtotal = Column(Float, default=0.0, nullable=False)
    tax_amount = Column(Float, default=0.0, nullable=False)  # 18% GST (CGST 9% + SGST 9%)
    grand_total = Column(Float, default=0.0, nullable=False)
    file_path = Column(String(500), nullable=True)  # Path to saved PDF or image
    status = Column(String(50), default="needs_review", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    supplier = relationship("Supplier", back_populates="invoices")
    purchase_order = relationship("PurchaseOrder", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    extractions = relationship("InvoiceExtraction", back_populates="invoice", cascade="all, delete-orphan")
    checks = relationship("InvoiceCheck", back_populates="invoice", cascade="all, delete-orphan")
    investigations = relationship("InvoiceInvestigation", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    """Line items listed on a supplier invoice."""
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    item_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    # Relationships
    invoice = relationship("Invoice", back_populates="items")


class Contract(Base):
    """
    Stores agreed master contract pricing and payment terms between
    the company and each supplier for each item.
    """
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True, index=True)  # owner workspace
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    item_name = Column(String(255), nullable=False)
    agreed_unit_price = Column(Float, nullable=False)
    payment_terms_days = Column(Integer, default=30, nullable=False)
    terms_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    supplier = relationship("Supplier", back_populates="contracts")


class InvoiceExtraction(Base):
    """
    Stores extracted data produced by AI / OCR for an invoice.
    Allows auditing and inspection without mutating original invoice tables or status.
    """
    __tablename__ = "invoice_extractions"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    extracted_json = Column(Text, nullable=False)  # Complete JSON string of ExtractedInvoice
    confidence = Column(Float, default=0.0, nullable=False)  # Confidence score (0.0 - 1.0)
    model_name = Column(String(100), nullable=False)  # AI model or extraction tool used
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    invoice = relationship("Invoice", back_populates="extractions")


class InvoiceCheck(Base):
    """
    Stores 3-way matching validation results comparing an invoice against
    Purchase Orders, Goods Received Notes (GRN), and Master Supplier Contracts.
    Status values: 'verified', 'mismatch_detected', 'needs_review'.
    """
    __tablename__ = "invoice_checks"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    status = Column(String(50), nullable=False)  # verified, mismatch_detected, needs_review
    mistake_types = Column(Text, nullable=False)  # JSON list string of mistake types, e.g. ["price_mismatch"] or ["none"]
    findings_json = Column(Text, nullable=False)  # Full JSON array of findings with evidence
    difference_amount = Column(Float, default=0.0, nullable=False)  # Discrepancy amount in INR
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    invoice = relationship("Invoice", back_populates="checks")


class AuditLog(Base):
    """
    Audit log tracking all critical actions (uploads, approvals, edits, extractions).
    Ensures complete compliance and accountability.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True, index=True)  # owner workspace
    who = Column(String(100), default="system", nullable=False)
    action = Column(String(100), nullable=False)
    time = Column(DateTime, default=datetime.utcnow, nullable=False)
    details = Column(Text, nullable=True)


class InvoiceInvestigation(Base):
    """
    Stores Investigation Agent reports for an invoice.
    Tracks status, findings, contract citations, template explanation,
    recommended next action, confidence, limitations, and full report JSON.
    """
    __tablename__ = "invoice_investigations"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    status = Column(String(50), nullable=False)  # verified, mismatch_detected, needs_review
    recommended_next_action = Column(String(50), nullable=False)
    confidence = Column(Float, default=0.0, nullable=False)
    report_json = Column(Text, nullable=False)  # Full JSON payload of InvestigationReport
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    invoice = relationship("Invoice", back_populates="investigations")


class InvoiceDecision(Base):
    """
    Phase 8: A HUMAN approval or rejection of an invoice.
    Each decision is linked to the investigation report the person looked at.
    The Investigation Agent can never create rows here (see approval_service).
    The original invoices.status column is NOT changed by a decision.
    """
    __tablename__ = "invoice_decisions"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True, index=True)  # owner workspace
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    investigation_id = Column(Integer, ForeignKey("invoice_investigations.id"), nullable=False, index=True)
    decision = Column(String(20), nullable=False)  # approved or rejected
    decided_by = Column(String(100), nullable=False)  # name of the finance person
    note = Column(Text, nullable=True)
    agent_recommendation = Column(String(50), nullable=False)  # what the agent advised at the time
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class User(Base):
    """A person who can log in to the dashboard. Passwords are stored ONLY as bcrypt hashes."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)  # stored lower-case
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Workspace(Base):
    """
    A private data space. Every user gets one on signup (owner_user_id).
    The special workspace with is_sample=True (name "sample") holds the demo data that
    users can copy into their own workspace; nobody logs into it.
    """
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, unique=True, index=True)
    is_sample = Column(Boolean, default=False, nullable=False)
    # Phase 3: "Demo data" badge/banner only while the workspace holds the sample copy and
    # nothing the user added. Any upload sets has_user_data -> "Live workspace".
    sample_loaded = Column(Boolean, default=False, nullable=False)
    has_user_data = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AIUsage(Base):
    """Phase 3: how many real Gemini explanations a user got on one day (limit: 5/day)."""
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_ai_usage_user_day"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    day = Column(Date, nullable=False)
    count = Column(Integer, default=0, nullable=False)


class APIKey(Base):
    """
    Phase 4: a key that lets automation (n8n) call the ingest API for ONE workspace.
    Only the SHA-256 hash is stored; the key itself is shown once, when it is created.
    key_prefix (first characters) just helps a person recognise the key in the list.
    """
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String(100), nullable=False)
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
