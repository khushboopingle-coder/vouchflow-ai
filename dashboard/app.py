"""
VouchFlow AI — Invoice Operations Workspace
A polished Streamlit interface for invoice review, verification and 3-way matching.
Backend integration and API endpoints are preserved.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

st.set_page_config(
    page_title="VouchFlow AI | Invoice Operations",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Demo start-up: works without API / .env / Gemini key (seeds an empty database once)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_setup  # noqa: E402

demo_setup.ensure_demo_ready()
demo_setup.show_demo_note()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

# ---------------------------------------------------------------------
# Premium finance-tech styling
# ---------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');

    :root {
        --bg: #f5f4ef;
        --panel: #fffefa;
        --panel-soft: #f8f8f3;
        --line: #e8e8df;
        --text: #26372f;
        --muted: #7c8980;
        --green: #557b68;
        --green-soft: #e8f0e9;
        --sage: #9eafa0;
        --blue: #788da5;
        --amber: #b58a4e;
        --red: #b96d68;
    }

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }
    .stApp {
        background:
          radial-gradient(ellipse at 85% 0%, rgba(212,224,211,.32), transparent 34%),
          linear-gradient(180deg, #f8f7f2 0%, #f3f3ed 100%);
        color: var(--text);
    }
    [data-testid="stHeader"] {
        background: rgba(248,247,242,.86);
        backdrop-filter: blur(12px);
    }
    [data-testid="stSidebar"] {
        background: #eeefe8;
        border-right: 1px solid #e2e5dc;
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.35rem; }
    [data-testid="stSidebar"] * { color: #34483d; }

    .block-container {
        max-width: 1580px;
        padding-top: 2.2rem;
        padding-bottom: 3rem;
    }
    h1, h2, h3, p, label { color: var(--text); }
    h1, h2, h3 { font-family: 'Manrope', sans-serif; letter-spacing: -.035em; }
    h1 { font-size: 2rem !important; font-weight: 750 !important; }
    h2 { font-size: 1.3rem !important; font-weight: 700 !important; }
    h3 { font-size: 1.03rem !important; font-weight: 700 !important; }

    .brand-lockup { display:flex; align-items:center; gap:12px; margin:0 0 1.8rem; }
    .brand-mark {
        width:42px; height:42px; display:flex; align-items:center; justify-content:center;
        border-radius:14px; font:800 1.25rem 'Manrope',sans-serif; color:#fff;
        background:linear-gradient(145deg,#78927d,#526f5d);
        box-shadow:0 6px 16px rgba(77,105,83,.16);
    }
    .brand-name { font:800 1.1rem 'Manrope',sans-serif; color:#2e4337; }
    .brand-caption { color:#89948a; font-size:.68rem; letter-spacing:.1em; text-transform:uppercase; margin-top:3px; }

    .eyebrow {
        color:#718b76; font-size:.7rem; font-weight:700;
        letter-spacing:.15em; text-transform:uppercase; margin-bottom:.55rem;
    }
    .page-heading { font:800 2rem 'Manrope',sans-serif; color:#293c31; letter-spacing:-.045em; }
    .page-subtitle { color:#7d8980; font-size:.94rem; margin-top:.4rem; }
    .topline {
        display:flex; justify-content:space-between; align-items:center;
        gap:12px; flex-wrap:wrap; margin-bottom:1.8rem;
    }
    .live-pill {
        display:inline-flex; align-items:center; gap:8px; padding:8px 13px;
        border:1px solid #dce7dc; border-radius:999px;
        color:#557760; background:#edf3ec; font-size:.75rem; font-weight:700;
    }
    .live-dot { width:7px;height:7px;border-radius:50%;background:#6e9a78; }

    .section-kicker { color:#8a958b; font-size:.72rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }
    .metric-card {
        min-height:137px; padding:20px 21px;
        border:1px solid #e8e9e1; border-radius:17px;
        background:rgba(255,254,250,.92);
        box-shadow:0 5px 18px rgba(47,63,48,.035);
    }
    .metric-top { display:flex; align-items:center; justify-content:space-between; gap:8px; }
    .metric-label { color:#7d8980; font-size:.81rem; font-weight:600; }
    .metric-icon {
        display:flex;align-items:center;justify-content:center;width:34px;height:34px;
        border-radius:11px;background:var(--icon-bg);color:var(--accent);font-size:16px;
    }
    .metric-value { color:#2d4034; font:800 1.9rem 'Manrope',sans-serif; margin-top:13px; letter-spacing:-.04em; }
    .metric-foot { color:#9aa39a; font-size:.72rem; margin-top:3px; }

    .surface {
        background:rgba(255,254,250,.9);
        border:1px solid #e8e9e1; border-radius:17px; padding:19px 20px;
        box-shadow:0 5px 18px rgba(47,63,48,.025);
    }
    .surface-heading { font:750 1.06rem 'Manrope',sans-serif; color:#304338; }
    .surface-caption { color:#89948b; font-size:.81rem; margin-top:4px; }

    .stButton > button {
        border-radius:10px !important; border:1px solid #d9e0d7 !important;
        background:#fffefa !important; color:#526b59 !important;
        font-weight:650 !important; transition:all .18s ease;
    }
    .stButton > button:hover {
        border-color:#a9bda9 !important; background:#f2f6ef !important;
        color:#405b48 !important;
    }
    .stButton > button[kind="primary"] {
        background:#5d7d66 !important; color:#fff !important; border:0 !important;
    }
    div[data-baseweb="select"] > div, div[data-baseweb="input"] > div,
    div[data-baseweb="textarea"] > div {
        background:#fffefa !important; border-color:#dfe3da !important;
        border-radius:10px !important;
    }
    [data-testid="stFileUploader"] {
        border:1px dashed #bdcbbb; border-radius:13px;
        background:#f8faf5; padding:10px;
    }
    [data-testid="stFileUploader"] section { border:0 !important; }
    [data-testid="stFileUploader"] small { color:#89948b !important; }
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        border:1px solid #e7e9e1; border-radius:12px; overflow:hidden;
    }
    [data-testid="stDataFrame"] * { font-size:.83rem; }
    [data-testid="stMetric"] { background:transparent; border:0; padding:0; }
    hr { border-color:#e5e8df !important; margin:1.5rem 0 !important; }
    .muted-note { color:#929b91; font-size:.76rem; }
    .sidebar-label {
        color:#89958a; font-size:.68rem; font-weight:800;
        letter-spacing:.13em; text-transform:uppercase; margin:1.1rem 0 .6rem;
    }
    .sidebar-status {
        padding:11px 13px; border-radius:11px; font-size:.8rem; font-weight:650;
        border:1px solid #d9e8d9; background:#e7f0e7; color:#52765b;
    }
    .sidebar-status.offline {
        border-color:#eadfc9; background:#f7f0e2; color:#987442;
    }
    .stAlert { border-radius:11px; }
    footer {visibility:hidden;}
    #MainMenu {visibility:hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------
def fetch_health():
    """Check whether the FastAPI backend is online."""
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def fetch_invoices(status_filter=None):
    """Fetch invoices from the API, with a local database fallback."""
    try:
        params = {}
        if status_filter and status_filter != "All":
            params["status"] = status_filter
        response = requests.get(f"{API_BASE_URL}/invoices", params=params, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, list) else data.get("invoices", [])
    except requests.exceptions.RequestException:
        pass

    try:
        from backend.database.db import SessionLocal
        from backend.services import invoice_service

        db = SessionLocal()
        try:
            status_param = status_filter if status_filter != "All" else None
            invoices = invoice_service.list_invoices(
                db=db, status_filter=status_param
            )
            return [invoice.model_dump() for invoice in invoices]
        finally:
            db.close()
    except Exception as exc:
        st.error(f"Could not load invoices: {exc}")
        return []


def fetch_single_invoice(invoice_id):
    """Fetch one invoice from the API, then fall back to the local database."""
    try:
        response = requests.get(f"{API_BASE_URL}/invoices/{invoice_id}", timeout=3)
        if response.status_code == 200:
            return response.json()
    except requests.exceptions.RequestException:
        pass

    try:
        from backend.database.db import SessionLocal
        from backend.services import invoice_service

        db = SessionLocal()
        try:
            invoice = invoice_service.get_invoice_by_id(
                db=db, invoice_id=invoice_id
            )
            return invoice.model_dump() if invoice else None
        finally:
            db.close()
    except Exception:
        return None


def upload_invoice_file(file_obj):
    """Send an uploaded invoice to the FastAPI endpoint."""
    try:
        files = {
            "file": (
                file_obj.name,
                file_obj.getvalue(),
                file_obj.type or "application/pdf",
            )
        }
        response = requests.post(
            f"{API_BASE_URL}/invoices/upload", files=files, timeout=30
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text or "Unexpected server response"}
        return response.status_code == 200, payload
    except requests.exceptions.RequestException as exc:
        return False, {"detail": str(exc)}


def money(value):
    try:
        return f"₹{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "—"


def status_color(status):
    return {
        "verified": ("#123e38", "#75e6bd"),
        "needs_review": ("#49371c", "#ffd17a"),
        "mismatch_detected": ("#4a252d", "#ff929a"),
        "pending_approval": ("#292e55", "#b6baff"),
    }.get(status, ("#263449", "#c3d2e6"))


def render_metric(label, value, icon, accent, icon_bg, foot):
    st.markdown(
        f"""
        <div class="metric-card" style="--accent:{accent};--glow:{accent};--icon-bg:{icon_bg}">
            <div class="metric-top">
                <div class="metric-label">{label}</div>
                <div class="metric-icon">{icon}</div>
            </div>
            <div class="metric-value">{value}</div>
            <div class="metric-foot">{foot}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------
api_status = fetch_health()

with st.sidebar:
    st.markdown(
        """
        <div class="brand-lockup">
            <div class="brand-mark">V</div>
            <div>
                <div class="brand-name">VouchFlow <span style="color:#42e0c2">AI</span></div>
                <div class="brand-caption">Invoice management, made simple</div>
            </div>
        </div>
        <div class="sidebar-label">Workspace</div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        (
            '<div class="sidebar-status">● Backend connected</div>'
            if api_status
            else '<div class="sidebar-status offline">● Standalone mode</div>'
        ),
        unsafe_allow_html=True,
    )
    if not api_status:
        st.caption(
            "Running without the API, straight on the local database. "
            "To use the API locally: `uvicorn backend.main:app --reload`."
        )

    st.markdown('<div class="sidebar-label">Filter ledger</div>', unsafe_allow_html=True)
    status_options = [
        "All",
        "verified",
        "needs_review",
        "mismatch_detected",
        "pending_approval",
    ]
    selected_status = st.selectbox(
        "Invoice status",
        status_options,
        index=0,
        format_func=lambda value: {
            "All": "All invoices",
            "verified": "Verified",
            "needs_review": "Needs review",
            "mismatch_detected": "Mismatch detected",
            "pending_approval": "Pending approval",
        }.get(value, value),
        label_visibility="collapsed",
    )

    if st.button("↻  Refresh workspace", use_container_width=True):
        st.rerun()

    st.markdown("---")
    st.markdown('<div class="sidebar-label">Add to your ledger</div>', unsafe_allow_html=True)
    st.markdown("**Quick invoice upload**")
    uploaded_file = st.file_uploader(
        "PDF or image",
        type=["pdf", "png", "jpg", "jpeg"],
        help="Supported formats: PDF, PNG and JPG.",
        label_visibility="collapsed",
    )
    if uploaded_file is not None:
        st.caption(f"Selected: {uploaded_file.name}")
        if st.button("↑  Submit invoice", type="primary", use_container_width=True):
            with st.spinner("Uploading invoice..."):
                success, response = upload_invoice_file(uploaded_file)
            if success:
                st.success(
                    f"Invoice received · ID {response.get('invoice_id', 'assigned')}"
                )
                st.rerun()
            else:
                st.error(response.get("detail", "Upload failed."))

    st.markdown("---")
    st.markdown(
        """
        <div class="muted-note">
            <b style="color:#dce8f8">VouchFlow AI</b><br>
            Accounts payable · Invoice audit<br><br>
            <span style="color:#42e0c2">●</span> Secure workflow interface
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------
# Main workspace header
# ---------------------------------------------------------------------
st.markdown(
    """
    <div class="topline">
        <div>
            <div class="eyebrow">ACCOUNTS PAYABLE / OVERVIEW</div>
            <div class="page-heading">Invoice overview</div>
            <div class="page-subtitle">
                A calmer, clearer view of your invoices and payment checks.
            </div>
        </div>
        <div class="live-pill"><span class="live-dot"></span> WORKSPACE ONLINE</div>
    </div>
    """,
    unsafe_allow_html=True,
)

all_invoices = fetch_invoices(status_filter=None) or []

# ---------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------
total_count = len(all_invoices)
verified_count = sum(1 for inv in all_invoices if inv.get("status") == "verified")
needs_review_count = sum(1 for inv in all_invoices if inv.get("status") == "needs_review")
mismatch_count = sum(
    1 for inv in all_invoices if inv.get("status") == "mismatch_detected"
)
verified_pct = round(verified_count / total_count * 100) if total_count else 0

st.markdown('<div class="section-kicker">Your invoice portfolio</div>', unsafe_allow_html=True)
st.write("")
kpi_cols = st.columns(4, gap="medium")
with kpi_cols[0]:
    render_metric("Total invoices", f"{total_count:,}", "▤", "#788da5", "rgba(120,141,165,.12)", "Invoices in your ledger")
with kpi_cols[1]:
    render_metric("Verified", f"{verified_count:,}", "✓", "#6d9476", "rgba(109,148,118,.13)", f"{verified_pct}% of all invoices")
with kpi_cols[2]:
    render_metric("Needs review", f"{needs_review_count:,}", "◷", "#b58a4e", "rgba(181,138,78,.12)", "Require a closer look")
with kpi_cols[3]:
    render_metric("Mismatches", f"{mismatch_count:,}", "!", "#b96d68", "rgba(185,109,104,.12)", "Exceptions to investigate")

st.write("")
st.markdown("---")

# ---------------------------------------------------------------------
# Invoice ledger
# ---------------------------------------------------------------------
ledger_col, insight_col = st.columns([3.25, 1], gap="large")

filtered_invoices = (
    all_invoices
    if selected_status == "All"
    else [inv for inv in all_invoices if inv.get("status") == selected_status]
)

with ledger_col:
    st.markdown(
        """
        <div class="surface-heading">Invoice ledger</div>
        <div class="surface-caption">Search, filter and inspect every invoice received by your team.</div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    search_col, count_col = st.columns([3, 1])
    with search_col:
        search_text = st.text_input(
            "Search invoices",
            placeholder="Search invoice number, supplier or PO reference...",
            label_visibility="collapsed",
        )
    with count_col:
        st.markdown(
            f'<div style="text-align:right;color:#91a2bb;padding:9px 2px;font-size:.8rem">'
            f'<b style="color:#edf4ff">{len(filtered_invoices)}</b> records</div>',
            unsafe_allow_html=True,
        )

    if search_text.strip():
        query = search_text.strip().lower()
        filtered_invoices = [
            inv for inv in filtered_invoices
            if query in str(inv.get("invoice_number", "")).lower()
            or query in str(inv.get("supplier_name", "")).lower()
            or query in str(inv.get("po_number", "")).lower()
        ]

    if not filtered_invoices:
        st.info("No invoices match the current filter. Try another status or search term.")
    else:
        table_data = []
        for inv in filtered_invoices:
            status = inv.get("status", "unknown")
            table_data.append(
                {
                    "ID": inv.get("id"),
                    "Invoice number": inv.get("invoice_number", "—"),
                    "Supplier": inv.get("supplier_name", "—"),
                    "PO reference": inv.get("po_number") or "—",
                    "Invoice date": inv.get("invoice_date", "—"),
                    "Grand total": money(inv.get("grand_total")),
                    "Status": status.replace("_", " ").title(),
                    "File": Path(str(inv.get("file_path", ""))).name or "—",
                }
            )

        df = pd.DataFrame(table_data)

        def style_status(value):
            key = value.lower().replace(" ", "_")
            bg, fg = status_color(key)
            return f"background-color:{bg};color:{fg};font-weight:700;border-radius:5px;"

        styled_df = df.style.map(style_status, subset=["Status"])
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            height=430,
        )

with insight_col:
    st.markdown(
        """
        <div class="surface-heading">Review snapshot</div>
        <div class="surface-caption">A quick pulse on your invoice queue.</div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    st.markdown(
        f"""
        <div class="surface" style="padding:17px;margin-bottom:12px">
            <div style="color:#91a2bb;font-size:.77rem">Clean invoices</div>
            <div style="font:800 1.8rem Manrope;color:#75e6bd;margin:5px 0">{verified_pct}%</div>
            <div style="height:7px;background:#26364c;border-radius:20px;overflow:hidden">
                <div style="height:100%;width:{verified_pct}%;background:linear-gradient(90deg,#35c9a8,#78d9d0);border-radius:20px"></div>
            </div>
            <div class="muted-note" style="margin-top:9px">Verified share of total invoices</div>
        </div>
        <div class="surface" style="padding:17px;margin-bottom:12px">
            <div style="color:#91a2bb;font-size:.77rem">Attention required</div>
            <div style="font:800 1.8rem Manrope;color:#ffd17a;margin:5px 0">{needs_review_count + mismatch_count:,}</div>
            <div class="muted-note">Review and mismatch cases</div>
        </div>
        <div class="surface" style="padding:17px">
            <div style="color:#91a2bb;font-size:.77rem">Workflow status</div>
            <div style="color:{'#75e6bd' if api_status else '#ffd17a'};font-weight:800;margin-top:7px">
                {'● Connected' if api_status else '● Local / offline'}
            </div>
            <div class="muted-note" style="margin-top:5px">Backend service connection</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------
# Invoice detail drill-down
# ---------------------------------------------------------------------
st.markdown("---")
st.markdown(
    """
    <div class="eyebrow">Invoice intelligence</div>
    <div class="surface-heading">Invoice inspection</div>
    <div class="surface-caption">Open an invoice to review extracted details and line items.</div>
    """,
    unsafe_allow_html=True,
)

if all_invoices:
    invoice_options = [inv.get("id") for inv in all_invoices if inv.get("id") is not None]
    if invoice_options:
        selected_id = st.selectbox(
            "Choose invoice",
            invoice_options,
            format_func=lambda value: next(
                (
                    f"{inv.get('invoice_number', 'Invoice')}  ·  "
                    f"{inv.get('supplier_name', 'Unknown supplier')}"
                    for inv in all_invoices if inv.get("id") == value
                ),
                f"Invoice ID {value}",
            ),
        )
        details = fetch_single_invoice(selected_id)

        if details:
            st.write("")
            info1, info2, info3, info4 = st.columns(4)
            with info1:
                st.markdown("**Supplier**")
                st.write(details.get("supplier_name") or "—")
            with info2:
                st.markdown("**PO reference**")
                st.write(details.get("po_number") or "—")
            with info3:
                st.markdown("**Invoice date**")
                st.write(details.get("invoice_date") or "—")
            with info4:
                st.markdown("**Status**")
                status = details.get("status", "unknown")
                bg, fg = status_color(status)
                st.markdown(
                    f'<span style="display:inline-block;padding:6px 10px;border-radius:7px;'
                    f'background:{bg};color:{fg};font-weight:700;font-size:.82rem">'
                    f'{status.replace("_", " ").title()}</span>',
                    unsafe_allow_html=True,
                )

            st.write("")
            amount1, amount2 = st.columns(2)
            with amount1:
                st.markdown("**Subtotal**")
                st.markdown(f"<h3>{money(details.get('subtotal'))}</h3>", unsafe_allow_html=True)
            with amount2:
                st.markdown("**Grand total**")
                st.markdown(f"<h3 style='color:#75e6bd'>{money(details.get('grand_total'))}</h3>", unsafe_allow_html=True)

            items = details.get("items", [])
            st.markdown("**Extracted line items**")
            if items:
                items_df = pd.DataFrame(
                    [
                        {
                            "Item description": item.get("item_name", "—"),
                            "Quantity": item.get("quantity", "—"),
                            "Unit price": money(item.get("unit_price")),
                            "Total": money(item.get("total_price")),
                        }
                        for item in items
                    ]
                )
                st.dataframe(items_df, use_container_width=True, hide_index=True)
            else:
                st.info("No line items have been extracted for this invoice yet.")
        else:
            st.warning("Invoice details could not be loaded.")
else:
    st.info("Your invoice ledger is empty. Upload a PDF or image from the left panel to get started.")

st.markdown(
    """
    <div style="text-align:center;color:#647792;font-size:.74rem;padding-top:2rem">
        VouchFlow AI · Intelligent accounts payable · Built for clarity and control
    </div>
    """,
    unsafe_allow_html=True,
)
