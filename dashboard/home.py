"""
VouchFlow AI — Home (invoice ledger)
The overview page: KPI cards, searchable invoice ledger and invoice inspection.
Opened through the router in dashboard/app.py (st.navigation, title "Home").
All colours come from ui_common.PALETTE (via CSS classes); none are written here.
"""

import hashlib
import html
import io
import sys
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = Path(__file__).resolve().parent
for _path in (BASE_DIR, DASHBOARD_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import ui_common as ui  # noqa: E402

ui.apply_global_css()  # shared theme (colours from ui_common.PALETTE)

ACCOUNT = ui.require_login()  # stops here when nobody is logged in
WS = ui.workspace_id()         # every query below is limited to this workspace

# ---------------------------------------------------------------------
# Data helpers (services called directly, always with this workspace)
# ---------------------------------------------------------------------
def fetch_invoices():
    return ui.list_invoices()


def fetch_single_invoice(invoice_id):
    from backend.services import invoice_service

    ok, data = ui.run_db(lambda db: invoice_service.get_invoice_by_id(db=db, invoice_id=invoice_id, workspace_id=WS))
    return data if ok else None


def upload_invoice_file(file_obj):
    """Save an uploaded invoice into this workspace (same rules as POST /invoices/upload), then
    try to READ it with the AI reader. Returns (saved, info). `info["read_ok"]` / `info["read_reason"]`
    say whether reading worked; a failed read never loses the invoice (it stays in 'needs review')."""
    from backend.services import ingest_service, invoice_service

    upload = SimpleNamespace(filename=file_obj.name, file=io.BytesIO(file_obj.getvalue()))
    saved, info = ui.run_db(lambda db: invoice_service.save_uploaded_invoice(
        db=db, file=upload, workspace_id=WS, who=ACCOUNT["email"]))
    if not saved:
        return False, info

    def read(db):
        outcome = ingest_service.read_saved_invoice(db, WS, info["invoice_id"], who=ACCOUNT["email"])
        return {"read_ok": outcome.ok, "read_reason": outcome.reason}

    ok, result = ui.run_db(read)
    info.update(result if ok else {"read_ok": False, "read_reason": result.get("detail", "unknown error")})
    return True, info


money = ui.money


def render_metric(label, value, icon, kind, foot):
    """KPI card. `kind` picks the icon colour: total, verified, needs_review, mismatch_detected."""
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-top">
                <div class="metric-label">{label}</div>
                <div class="metric-icon k-{kind}">{icon}</div>
            </div>
            <div class="metric-value">{value}</div>
            <div class="metric-foot">{foot}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------
# Sidebar (brand, badge and page menu are drawn by app.py above this)
# ---------------------------------------------------------------------
with st.sidebar:
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
        format_func=lambda value: "All invoices" if value == "All" else ui.status_label(value),
        label_visibility="collapsed",
    )

    if st.button("↻  Refresh workspace", width="stretch"):
        st.rerun()

    st.markdown("---")
    st.markdown('<div class="sidebar-label">Add to your ledger</div>', unsafe_allow_html=True)
    st.markdown("**Quick invoice upload**")
    # Result of the last upload (shown after the page reloads, because the uploader is cleared)
    notice = st.session_state.pop("upload_notice", None)
    if notice:
        if notice["kind"] == "success":
            st.success(notice["text"])
        else:
            st.warning(notice["text"])

    # A new key after every submit empties the uploader, so one file cannot be saved twice
    uploaded_file = st.file_uploader(
        "PDF or image",
        type=["pdf", "png", "jpg", "jpeg"],
        help="Supported formats: PDF, PNG and JPG.",
        label_visibility="collapsed",
        key=f"quick_upload_{st.session_state.get('upload_round', 0)}",
    )
    if uploaded_file is not None:
        st.caption(f"Selected: {uploaded_file.name}")
        file_hash = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
        submitted = st.session_state.setdefault("submitted_hashes", set())
        if file_hash in submitted:
            st.info("This file was already submitted in this session.")
        elif st.button("↑  Submit invoice", type="primary", width="stretch"):
            submitted.add(file_hash)  # marked BEFORE saving: a second click cannot save it again
            with st.spinner("Saving and reading the invoice (this can take up to a minute)..."):
                success, response = upload_invoice_file(uploaded_file)
            if not success:
                submitted.discard(file_hash)  # nothing was saved, so the user may try again
                st.error(response.get("detail", "Upload failed."))
            else:
                inv_id = response.get("invoice_id", "assigned")
                if response.get("read_ok"):
                    st.session_state["upload_notice"] = {
                        "kind": "success", "text": f"Invoice read and saved · ID {inv_id}"}
                else:
                    st.session_state["upload_notice"] = {
                        "kind": "warning",
                        "text": (f"Could not read this invoice, saved for manual review (ID {inv_id}). "
                                 f"Reason: {response.get('read_reason') or 'unknown'}")}
                st.session_state["upload_round"] = st.session_state.get("upload_round", 0) + 1
                st.rerun()

    st.markdown("---")
    st.markdown(
        """
        <div class="muted-note">
            <b>VouchFlow AI</b><br>
            Accounts payable · Invoice audit<br><br>
            ● Secure workflow interface
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------
# Main workspace header
# ---------------------------------------------------------------------
st.markdown(
    f"""
    <div class="topline">
        <div>
            <div class="eyebrow">ACCOUNTS PAYABLE / OVERVIEW</div>
            <div class="page-heading">Invoice overview</div>
            <div class="page-subtitle">
                A calmer, clearer view of your invoices and payment checks.
            </div>
        </div>
        <div class="live-pill"><span class="live-dot"></span>
            {html.escape(ACCOUNT["workspace_name"]).upper()}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

all_invoices = fetch_invoices() or []

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
    render_metric("Total invoices", f"{total_count:,}", "▤", "total", "Invoices in your ledger")
with kpi_cols[1]:
    render_metric("Verified", f"{verified_count:,}", "✓", "verified", f"{verified_pct}% of all invoices")
with kpi_cols[2]:
    render_metric("Needs review", f"{needs_review_count:,}", "◷", "needs_review", "Require a closer look")
with kpi_cols[3]:
    render_metric("Mismatches", f"{mismatch_count:,}", "!", "mismatch_detected", "Exceptions to investigate")

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
            f'<div class="records"><b>{len(filtered_invoices)}</b> records</div>',
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

    if not all_invoices:
        st.caption("No invoices yet — use **Workspace tools → Load sample data** in the sidebar, "
                   "or upload an invoice.")
    elif not filtered_invoices:
        st.info("No invoices match the current filter. Try another status or search term.")
    else:
        ui.render_html_table(
            [
                {
                    "ID": inv.get("id"),
                    "Invoice number": inv.get("invoice_number", "—"),
                    "Supplier": inv.get("supplier_name", "—"),
                    # status and total first, so they are visible without scrolling sideways
                    "Status": inv.get("status", "unknown"),
                    "Grand total": money(inv.get("grand_total")),
                    "PO reference": inv.get("po_number") or "—",
                    "Invoice date": inv.get("invoice_date", "—"),
                    "File": Path(str(inv.get("file_path", ""))).name or "—",
                }
                for inv in filtered_invoices
            ],
            status_column="Status",
            numeric_columns=("ID", "Grand total"),
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
        <div class="surface" style="margin-bottom:12px">
            <div class="chrome-head">Clean invoices</div>
            <div class="big-number amount total">{verified_pct}%</div>
            <div class="progress-track"><div class="progress-fill" style="width:{verified_pct}%"></div></div>
            <div class="muted-note" style="margin-top:9px">Verified share of total invoices</div>
        </div>
        <div class="surface" style="margin-bottom:12px">
            <div class="chrome-head">Attention required</div>
            <div class="big-number amount">{needs_review_count + mismatch_count:,}</div>
            <div class="muted-note">Review and mismatch cases</div>
        </div>
        <div class="surface">
            <div class="chrome-head">Workspace</div>
            <div style="margin-top:4px"><span class="vf-pill vf-verified">Private</span></div>
            <div class="muted-note" style="margin-top:8px">Only you can see this data</div>
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
                st.markdown(ui.status_pill(details.get("status", "unknown")), unsafe_allow_html=True)

            st.write("")
            amount1, amount2 = st.columns(2)
            with amount1:
                st.markdown("**Subtotal**")
                st.markdown(f"<h3 class='amount'>{html.escape(money(details.get('subtotal')))}</h3>", unsafe_allow_html=True)
            with amount2:
                st.markdown("**Grand total**")
                st.markdown(f"<h3 class='amount total'>{html.escape(money(details.get('grand_total')))}</h3>", unsafe_allow_html=True)

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
                st.dataframe(items_df, width="stretch", hide_index=True)
            else:
                st.info("No line items have been extracted for this invoice yet.")
        else:
            st.warning("Invoice details could not be loaded.")
else:
    st.info("Your invoice ledger is empty. Upload a PDF or image from the left panel to get started.")

st.markdown(
    '<div class="footer-note">VouchFlow AI · Intelligent accounts payable · Built for clarity and control</div>',
    unsafe_allow_html=True,
)
