"""
VouchFlow AI - FastAPI Backend API
==================================
Open:
- GET  /health                      : Health check
- POST /auth/signup                 : New account + private workspace (+ sample data)
- POST /auth/login                  : Email + password -> Bearer token

Needs "Authorization: Bearer <token>" and only ever shows the caller's own workspace
(Phase 2). Another workspace's invoice answers 404, exactly like a missing one:
- GET  /auth/me                     : Who am I, which workspace
- GET  /invoices                    : Lists the workspace's invoices
- GET  /invoices/{id}               : One invoice with its line items
- POST /invoices/upload             : Upload invoice PDF/image ('needs_review') + audit log
- POST /invoices/{id}/extract       : AI/OCR extraction -> invoice_extractions
- GET  /invoices/{id}/extraction    : Saved extraction
- POST /invoices/{id}/check         : 3-way matching check
- GET  /invoices/{id}/check         : Saved check
- GET  /audit-logs                  : Recent audit log records of the workspace
- POST /invoices/{id}/investigate   : Run the Investigation Agent
- GET  /invoices/{id}/investigation : Latest Investigation Agent report
- POST /invoices/{id}/decision      : HUMAN approve / reject
- GET  /approvals/queue             : Investigated invoices waiting for a human decision
- GET  /approvals/decisions         : Recent human decisions

Automation (Phase 4) - header "X-API-Key: vf_..." (create keys on the dashboard's Settings page).
The key identifies ONE workspace; wrong/missing/revoked key -> 401; nothing is ever approved:
- POST /api/invoices/ingest         : file -> save, extract, match, investigate -> JSON
- GET  /api/invoices/{id}/summary   : short summary for alerts
"""

from typing import List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.auth import rate_limit
from backend.auth.dependencies import APIKeyAccount, api_key_account, current_account
from backend.auth.tokens import create_token
from backend.database.db import get_db, init_db
from backend.database import schemas
from backend.database.models import AuditLog
from backend.agent.state import InvestigationReport
from backend.services import invoice_service, approval_service, auth_service, ingest_service, upload_service
from backend.services.auth_service import Account, AuthError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes tables on server startup."""
    init_db()
    yield


app = FastAPI(
    title="VouchFlow AI API",
    description="Intelligent Accounts Payable & 3-Way Matching API with private workspaces",
    version="1.2.0",
    lifespan=lifespan
)

# Enable CORS for local development and dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/health",
    response_model=schemas.HealthResponse,
    summary="Health check",
    tags=["System"]
)
def health_check():
    """Returns system operational health status."""
    return {"status": "ok"}


# ---------------------------------------------------------------------
# Accounts (Phase 2)
# ---------------------------------------------------------------------
def _token_response(account: Account) -> schemas.TokenResponse:
    return schemas.TokenResponse(
        access_token=create_token(account.user_id, account.workspace_id),
        email=account.email,
        workspace_id=account.workspace_id,
        workspace_name=account.workspace_name,
    )


@app.post("/auth/signup", response_model=schemas.TokenResponse, summary="Create an account", tags=["Auth"])
def signup(payload: schemas.SignupRequest, db: Session = Depends(get_db)):
    """Creates a user and their private workspace (with a copy of the sample data by default)."""
    try:
        account = auth_service.signup(db, payload.email, payload.password, load_sample=payload.load_sample)
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return _token_response(account)


@app.post("/auth/login", response_model=schemas.TokenResponse, summary="Log in", tags=["Auth"])
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    """Email + password -> Bearer token (valid 12 hours). Wrong details -> 401."""
    account = auth_service.login(db, payload.email, payload.password)
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password.")
    return _token_response(account)


@app.get("/auth/me", response_model=schemas.AccountRead, summary="Current account", tags=["Auth"])
def me(account: Account = Depends(current_account)):
    return schemas.AccountRead(email=account.email, workspace_id=account.workspace_id,
                               workspace_name=account.workspace_name)


# ---------------------------------------------------------------------
# Invoices (all scoped to the caller's workspace)
# ---------------------------------------------------------------------
@app.get(
    "/invoices",
    response_model=List[schemas.InvoiceRead],
    summary="List the workspace's invoices",
    tags=["Invoices"]
)
def list_invoices(
    status_filter: str = Query(
        None,
        alias="status",
        description="Filter by invoice status: verified, needs_review, mismatch_detected, pending_approval"
    ),
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(100, ge=1, le=500, description="Number of invoices to return"),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    """Returns the invoices of the caller's workspace with supplier name, PO number and status."""
    return invoice_service.list_invoices(
        db=db,
        workspace_id=account.workspace_id,
        status_filter=status_filter,
        skip=skip,
        limit=limit
    )


@app.get(
    "/invoices/{invoice_id}",
    response_model=schemas.InvoiceDetail,
    summary="Get single invoice details",
    tags=["Invoices"]
)
def get_invoice(invoice_id: int, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    """Full details of one invoice of the caller's workspace (404 otherwise)."""
    return invoice_service.get_invoice_by_id(db=db, invoice_id=invoice_id, workspace_id=account.workspace_id)


@app.post(
    "/invoices/upload",
    response_model=schemas.UploadResponse,
    summary="Upload an invoice file (PDF/Image)",
    tags=["Invoices"]
)
def upload_invoice(
    file: UploadFile = File(..., description="Invoice document (PDF, PNG, JPG)"),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    """Saves the file to data/invoices/, creates an invoice ('needs_review') in the caller's
    workspace, and logs an audit entry."""
    return invoice_service.save_uploaded_invoice(
        db=db, file=file, workspace_id=account.workspace_id, who=account.email
    )


@app.post(
    "/invoices/{invoice_id}/extract",
    response_model=schemas.ExtractedInvoice,
    summary="Extract structured data from an invoice document using AI/OCR",
    tags=["Extraction"]
)
def extract_invoice(invoice_id: int, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    """Runs the Invoice Reader (pdfplumber + Gemini). Invoice status is NOT modified."""
    return invoice_service.extract_invoice_data(
        db=db, invoice_id=invoice_id, workspace_id=account.workspace_id, who=account.email
    )


@app.get(
    "/invoices/{invoice_id}/extraction",
    response_model=schemas.InvoiceExtractionDetail,
    summary="Get saved extraction for an invoice",
    tags=["Extraction"]
)
def get_extraction(invoice_id: int, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    """The most recent extraction record for an invoice of the caller's workspace."""
    return invoice_service.get_invoice_extraction(db=db, invoice_id=invoice_id, workspace_id=account.workspace_id)


@app.post(
    "/invoices/{invoice_id}/check",
    response_model=schemas.InvoiceCheckDetail,
    summary="Run 3-way matching check on an invoice",
    tags=["Matching"]
)
def check_invoice(invoice_id: int, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    """3-way matching (Invoice vs PO vs GRN vs Contract). Invoice status is NOT modified."""
    return invoice_service.check_invoice_matching(
        db=db, invoice_id=invoice_id, workspace_id=account.workspace_id, who=account.email
    )


@app.get(
    "/invoices/{invoice_id}/check",
    response_model=schemas.InvoiceCheckDetail,
    summary="Get saved 3-way matching check for an invoice",
    tags=["Matching"]
)
def get_invoice_check(invoice_id: int, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    """The most recent 3-way matching check result."""
    return invoice_service.get_invoice_check(db=db, invoice_id=invoice_id, workspace_id=account.workspace_id)


@app.get(
    "/audit-logs",
    response_model=List[schemas.AuditLogRead],
    summary="List recent audit log entries of the workspace",
    tags=["Audit"]
)
def list_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    """Recent audit log events of the caller's workspace."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.workspace_id == account.workspace_id)
        .order_by(AuditLog.time.desc())
        .limit(limit)
        .all()
    )


@app.post(
    "/invoices/{invoice_id}/investigate",
    response_model=InvestigationReport,
    summary="Run Investigation Agent workflow on an invoice",
    tags=["Investigation"]
)
def investigate_invoice_endpoint(
    invoice_id: int,
    use_ai: bool = Query(False, description="Ask Gemini to write the explanation (max 5 per user per day; "
                                            "otherwise the deterministic template is used)"),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    """Runs the Investigation Agent (LangGraph). The agent never approves or pays."""
    return invoice_service.investigate_invoice(
        db=db, invoice_id=invoice_id, workspace_id=account.workspace_id, who=account.email,
        use_ai=use_ai, user_id=account.user_id,
    )


@app.get(
    "/invoices/{invoice_id}/investigation",
    response_model=InvestigationReport,
    summary="Get saved Investigation Agent report for an invoice",
    tags=["Investigation"]
)
def get_invoice_investigation_endpoint(invoice_id: int, db: Session = Depends(get_db),
                                       account: Account = Depends(current_account)):
    """The most recent Investigation Agent report for an invoice of the caller's workspace."""
    return invoice_service.get_invoice_investigation(
        db=db, invoice_id=invoice_id, workspace_id=account.workspace_id
    )


# ---------------------------------------------------------------------
# Human approvals (scoped to the caller's workspace)
# ---------------------------------------------------------------------
@app.post(
    "/invoices/{invoice_id}/decision",
    response_model=schemas.DecisionRead,
    summary="Record a HUMAN approve / reject decision",
    tags=["Approvals"]
)
def record_decision_endpoint(
    invoice_id: int,
    payload: schemas.DecisionCreate,
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    """Saves a finance person's decision on the latest investigation of an invoice of the
    caller's workspace. Refuses software names, requires an investigation first, and
    requires a note for rejections or when overriding the agent's advice."""
    return approval_service.record_decision(
        db=db, invoice_id=invoice_id, payload=payload, workspace_id=account.workspace_id
    )


@app.get(
    "/approvals/queue",
    response_model=List[schemas.ApprovalQueueItem],
    summary="Invoices waiting for a human decision",
    tags=["Approvals"]
)
def approval_queue_endpoint(db: Session = Depends(get_db), account: Account = Depends(current_account)):
    """Invoices of the caller's workspace whose latest investigation is not decided yet."""
    return approval_service.get_approval_queue(db=db, workspace_id=account.workspace_id)


@app.get(
    "/approvals/decisions",
    response_model=List[schemas.DecisionRead],
    summary="Recent human decisions",
    tags=["Approvals"]
)
def list_decisions_endpoint(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    """Recent approve / reject decisions of the caller's workspace, newest first."""
    return approval_service.list_decisions(db=db, workspace_id=account.workspace_id, limit=limit)


# ---------------------------------------------------------------------
# Automation (Phase 4): X-API-Key instead of a login token
# ---------------------------------------------------------------------
@app.post(
    "/api/invoices/ingest",
    response_model=schemas.IngestResponse,
    summary="Ingest an invoice file: save, extract, match, investigate",
    tags=["Automation"]
)
def ingest_invoice_endpoint(
    file: UploadFile = File(..., description="Invoice document (PDF, PNG, JPG), up to 10 MB"),
    db: Session = Depends(get_db),
    key: APIKeyAccount = Depends(api_key_account),
):
    """
    Saves the invoice in the key's workspace, reads it (needs a Gemini key on the server),
    runs the 3-way match and the Investigation Agent, and returns the result as JSON with a
    dashboard link. Rate limited per key (429). It NEVER approves or pays: a person decides.
    """
    rate_limit.check_rate_limit(key.key_id)
    data = file.file.read(upload_service.MAX_UPLOAD_BYTES + 1)
    try:
        return ingest_service.ingest_invoice(
            db, key.workspace_id, file.filename or "invoice.pdf", data, who=f"api_key:{key.key_prefix}"
        )
    except upload_service.UploadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@app.get(
    "/api/invoices/{invoice_id}/summary",
    response_model=schemas.InvoiceSummary,
    summary="Short summary of an invoice, for alerts",
    tags=["Automation"]
)
def invoice_summary_endpoint(
    invoice_id: int,
    db: Session = Depends(get_db),
    key: APIKeyAccount = Depends(api_key_account),
):
    """Status, problems, recommended action, dashboard link and a ready-to-send text.
    An invoice of another workspace answers 404."""
    return ingest_service.build_summary(db, key.workspace_id, invoice_id)
