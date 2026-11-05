"""
Pydantic v2 Schemas for VouchFlow AI
Used for API request validation and response serialization.
"""

from datetime import datetime, date
from typing import Optional, List, Any, Dict, Literal
from pydantic import BaseModel, ConfigDict, Field


# ==========================================
# Supplier Schemas
# ==========================================
class SupplierBase(BaseModel):
    name: str = Field(..., description="Business name of the supplier")
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = Field(None, description="GST Identification Number")


class SupplierCreate(SupplierBase):
    pass


class SupplierRead(SupplierBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Contract Schemas
# ==========================================
class ContractBase(BaseModel):
    supplier_id: int
    item_name: str
    agreed_unit_price: float
    payment_terms_days: int = 30
    terms_text: Optional[str] = None


class ContractCreate(ContractBase):
    pass


class ContractRead(ContractBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Purchase Order Line Items
# ==========================================
class POItemBase(BaseModel):
    item_name: str
    quantity: int
    unit_price: float
    total_price: float


class POItemCreate(POItemBase):
    pass


class POItemRead(POItemBase):
    id: int
    po_id: int
    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Purchase Order Schemas
# ==========================================
class PurchaseOrderBase(BaseModel):
    po_number: str
    supplier_id: int
    order_date: date = Field(default_factory=date.today)
    status: str = "issued"
    total_amount: float = 0.0


class PurchaseOrderCreate(PurchaseOrderBase):
    pass


class PurchaseOrderRead(PurchaseOrderBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderWithItems(PurchaseOrderRead):
    items: List[POItemRead] = []
    supplier: Optional[SupplierRead] = None


# ==========================================
# Goods Received Note (GRN) Schemas
# ==========================================
class GRNItemBase(BaseModel):
    item_name: str
    quantity_received: int


class GRNItemCreate(GRNItemBase):
    pass


class GRNItemRead(GRNItemBase):
    id: int
    grn_id: int
    model_config = ConfigDict(from_attributes=True)


class GoodsReceivedNoteBase(BaseModel):
    grn_number: str
    po_id: int
    received_date: date = Field(default_factory=date.today)
    received_by: Optional[str] = None
    remarks: Optional[str] = None


class GoodsReceivedNoteCreate(GoodsReceivedNoteBase):
    pass


class GoodsReceivedNoteRead(GoodsReceivedNoteBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class GoodsReceivedNoteWithItems(GoodsReceivedNoteRead):
    items: List[GRNItemRead] = []


# ==========================================
# Invoice Line Items
# ==========================================
class InvoiceItemBase(BaseModel):
    item_name: str
    quantity: int
    unit_price: float
    total_price: float


class InvoiceItemCreate(InvoiceItemBase):
    pass


class InvoiceItemRead(InvoiceItemBase):
    id: int
    invoice_id: int
    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Invoice Schemas
# ==========================================
class InvoiceBase(BaseModel):
    invoice_number: str
    supplier_id: Optional[int] = None
    po_id: Optional[int] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    subtotal: float = 0.0
    tax_amount: float = 0.0
    grand_total: float = 0.0
    file_path: Optional[str] = None
    status: str = Field(
        default="needs_review",
        description="Status: verified, needs_review, mismatch_detected, pending_approval"
    )


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceRead(InvoiceBase):
    id: int
    created_at: datetime
    supplier_name: Optional[str] = None
    po_number: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class InvoiceDetail(InvoiceRead):
    items: List[InvoiceItemRead] = []
    supplier: Optional[SupplierRead] = None
    purchase_order: Optional[PurchaseOrderRead] = None


# ==========================================
# Phase 1: Invoice Reader & Extraction Schemas
# ==========================================
class ExtractedItem(BaseModel):
    """A line item extracted from an invoice by AI / OCR."""
    name: str = Field(..., description="Item or product description")
    quantity: int = Field(1, description="Quantity billed")
    unit_price: float = Field(0.0, description="Unit price before tax")
    total_price: Optional[float] = Field(None, description="Calculated or stated line item total")


class ExtractedInvoice(BaseModel):
    """
    Validated invoice data structure parsed from Gemini AI.
    Contains core header fields, line items, totals, and quality metrics.
    """
    vendor: Optional[str] = Field(None, description="Supplier / vendor name")
    invoice_number: Optional[str] = Field(None, description="Invoice reference number")
    invoice_date: Optional[str] = Field(None, description="Invoice date in YYYY-MM-DD or raw format")
    due_date: Optional[str] = Field(None, description="Payment due date")
    po_reference: Optional[str] = Field(None, description="Referenced PO number if present")
    items: List[ExtractedItem] = Field(default_factory=list, description="Extracted line items")
    subtotal: Optional[float] = Field(None, description="Subtotal before taxes")
    gst_amount: Optional[float] = Field(None, description="Total GST / tax amount")
    grand_total: Optional[float] = Field(None, description="Total payable amount")
    currency: Optional[str] = Field("INR", description="Currency (e.g. INR or Rs.)")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    missing_fields: List[str] = Field(default_factory=list, description="List of expected fields that were missing or empty")
    is_success: bool = Field(True, description="True if extraction succeeded, False if failed")
    error_message: Optional[str] = Field(None, description="Error details if extraction failed")
    model_name: Optional[str] = Field(None, description="Name of the Gemini model used for extraction")


class InvoiceExtractionRead(BaseModel):
    """Schema for returning saved extraction records."""
    id: int
    invoice_id: int
    extracted_json: str
    confidence: float
    model_name: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class InvoiceExtractionDetail(BaseModel):
    """Schema returning the parsed extraction alongside metadata."""
    id: int
    invoice_id: int
    model_name: str
    confidence: float
    created_at: datetime
    data: ExtractedInvoice


# ==========================================
# 3-Way Matching Check Schemas
# ==========================================
class MatchFinding(BaseModel):
    """Granular check finding with auditable evidence."""
    check_name: str = Field(..., description="Name of the matching check (price, quantity, totals, missing_po, duplicate)")
    status: str = Field(..., description="Status: pass, fail, or warning")
    mistake_type: Optional[str] = Field(None, description="Flagged mistake type matching ground truth (or 'none')")
    message: str = Field(..., description="Human-readable explanation of the finding")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Values compared and their sources")
    difference_amount: float = Field(0.0, description="Financial discrepancy amount in INR")


class InvoiceCheckResult(BaseModel):
    """Overall 3-way matching result evaluated for an invoice."""
    invoice_id: int
    status: str = Field(..., description="Overall status: verified, mismatch_detected, or needs_review")
    mistake_types: List[str] = Field(default_factory=list, description="List of detected mistake types")
    difference_amount: float = Field(0.0, description="Net discrepancy amount in INR")
    findings: List[MatchFinding] = Field(default_factory=list, description="Itemized findings with evidence")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class InvoiceCheckRead(BaseModel):
    """Raw ORM schema for reading records from the invoice_checks table."""
    id: int
    invoice_id: int
    status: str
    mistake_types: str
    findings_json: str
    difference_amount: float
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class InvoiceCheckDetail(BaseModel):
    """Parsed check record returned to API clients."""
    id: int
    invoice_id: int
    status: str
    mistake_types: List[str]
    difference_amount: float
    findings: List[MatchFinding]
    created_at: datetime


# ==========================================
# Audit Log Schemas
# ==========================================
class AuditLogBase(BaseModel):
    who: str = "system"
    action: str
    details: Optional[str] = None


class AuditLogCreate(AuditLogBase):
    pass


class AuditLogRead(AuditLogBase):
    id: int
    time: datetime
    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Common Utility Responses
# ==========================================
class HealthResponse(BaseModel):
    status: str = "ok"


class UploadResponse(BaseModel):
    message: str
    invoice_id: int
    file_name: str
    status: str
    file_path: str


# ==========================================
# Phase 8: Human Approval Schemas
# ==========================================
class DecisionCreate(BaseModel):
    """Body for POST /invoices/{id}/decision. Only a human may send this."""
    decision: Literal["approved", "rejected"] = Field(..., description="approved or rejected")
    decided_by: str = Field(..., min_length=2, max_length=100, description="Full name of the finance person deciding")
    note: Optional[str] = Field(None, max_length=2000, description="Reason for the decision")


class DecisionRead(BaseModel):
    id: int
    invoice_id: int
    investigation_id: int
    decision: str
    decided_by: str
    note: Optional[str] = None
    agent_recommendation: str
    created_at: datetime
    invoice_number: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class ApprovalQueueItem(BaseModel):
    """An invoice whose latest investigation is waiting for a human decision."""
    invoice_id: int
    invoice_number: str
    supplier_name: Optional[str] = None
    grand_total: float
    investigation_id: int
    investigation_status: str
    recommended_next_action: str
    confidence: float
    investigated_at: datetime


# ==========================================
# Phase 2: Accounts and workspaces
# ==========================================
class SignupRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=72)
    load_sample: bool = Field(True, description="Start with a copy of the sample data")


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., max_length=72)


class AccountRead(BaseModel):
    email: str
    workspace_id: int
    workspace_name: str


class TokenResponse(AccountRead):
    access_token: str
    token_type: str = "bearer"


# ==========================================
# Phase 4: Ingest API for automation (n8n)
# ==========================================
class InvoiceSummary(BaseModel):
    """Short summary of a checked invoice, for alerts."""
    invoice_id: int
    invoice_number: str
    supplier_name: Optional[str] = None
    grand_total: float
    status: str = Field(..., description="verified, mismatch_detected or needs_review")
    mistakes: List[str] = Field(default_factory=list, description="e.g. price_mismatch, quantity_mismatch")
    difference_amount: float = 0.0
    recommended_action: Optional[str] = None
    dashboard_link: str
    human_approval_required: bool = True
    text: str = Field(..., description="Ready-to-send message for Telegram / email")


class IngestResponse(InvoiceSummary):
    """Answer of POST /api/invoices/ingest."""
    extraction_ok: bool = Field(..., description="False when the invoice could not be read (no AI key / unreadable)")
    extraction_confidence: float = 0.0
    extraction_error: Optional[str] = Field(None, description="Why the invoice could not be read (None when it was read)")
    message: str
