"""
VouchFlow AI — My data (Phase 3)
Upload your own invoices, purchase orders, goods received notes and contracts.
Everything goes into YOUR workspace only. CSV templates show the expected columns.
"""

import sys
from pathlib import Path

import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import ui_common as ui  # noqa: E402

st.set_page_config(page_title="VouchFlow AI | My data", page_icon="🧾", layout="wide")
ui.apply_global_css()  # shared theme (colours from ui_common.PALETTE)
ui.apply_page_style(
    "My data",
    "Upload your own invoices, purchase orders, goods received notes and contracts. "
    "Everything stays in your private workspace.",
)

from backend.services import ai_usage_service, invoice_service, upload_service  # noqa: E402

WS = ui.workspace_id()
ACCOUNT = ui.current_account()


def show_result(ok, result):
    """Green summary on success, a clear list of problems on failure."""
    if ok:
        st.success(result)
    else:
        message = str(result.get("detail", result)) if isinstance(result, dict) else str(result)
        head, _, rest = message.partition(" | ") if " | " in message else (message, "", "")
        st.error(head.split(": ", 1)[-1] if head.startswith("UploadError") else head)
        for problem in rest.split(" | ") if rest else []:
            st.markdown(f"- {problem}")


def run_upload(fn):
    """Runs an upload_service call; UploadError -> readable message + row list."""
    def wrapped(db):
        try:
            return True, fn(db)
        except upload_service.UploadError as exc:
            return False, str(exc)
    ok, value = ui.run_db(wrapped)
    if not ok:
        return False, value
    return value


def template_button(name: str):
    st.download_button(f"Download template: {name}", data=upload_service.TEMPLATES[name],
                       file_name=name, mime="text/csv", key=f"tpl_{name}", icon=":material/download:")


tab_inv, tab_po, tab_grn, tab_prices, tab_contracts = st.tabs(
    ["Invoices", "Purchase orders", "Goods received", "Contract prices", "Contract documents"])

# ---------------------------------------------------------------------
with tab_inv:
    st.markdown("**Invoice files** — PDF, PNG or JPG, up to 10 MB each.")
    files = st.file_uploader("Invoice files", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True,
                             key="up_invoices", label_visibility="collapsed")
    if st.button("Upload invoices", key="btn_invoices", type="primary", disabled=not files):
        new_ids = []
        for f in files:
            ok, result = run_upload(lambda db, f=f: upload_service.save_invoice_file(
                db, WS, f.name, f.getvalue(), who=ACCOUNT["email"]))
            if ok:
                new_ids.append(result.invoice_id)
                st.success(f"{f.name} → invoice #{result.invoice_id} (needs review)")
            else:
                show_result(False, f"{f.name}: {result}")
        st.session_state["uploaded_invoice_ids"] = new_ids

    pending = st.session_state.get("uploaded_invoice_ids") or []
    if pending:
        ok_left, left = ui.run_db(lambda db: ai_usage_service.remaining_today(db, ACCOUNT["user_id"]))
        left = left if ok_left else 0
        st.markdown("---")
        st.markdown(f"**Read the uploaded invoices with AI** (fills in number, supplier, PO and amounts). "
                    f"Uses one of your {ai_usage_service.DAILY_AI_LIMIT} daily AI actions per invoice — "
                    f"{left} left today.")
        if not ai_usage_service.ai_available():
            st.caption("AI reading is switched off on this server (no Gemini key). "
                       "The invoices stay in 'needs review' for a person to enter.")
        elif st.button("Read with AI", key="btn_extract", disabled=left == 0):
            for inv_id in pending[:left]:
                done, res = ui.run_db(lambda db, i=inv_id: invoice_service.extract_invoice_data(
                    db=db, invoice_id=i, workspace_id=WS, who=ACCOUNT["email"]))
                if done:
                    ui.run_db(lambda db: ai_usage_service.record_ai_use(db, ACCOUNT["user_id"]))
                    st.success(f"Invoice #{inv_id} read (confidence {res.get('confidence', 0):.0%}).")
                else:
                    st.warning(f"Invoice #{inv_id}: could not be read ({res.get('detail')}).")
            st.session_state["uploaded_invoice_ids"] = []

# ---------------------------------------------------------------------
with tab_po:
    st.markdown("**Purchase orders (CSV)** — one row per line item. Rows with the same "
                "`po_number` belong to one order. New suppliers are created automatically.")
    template_button("purchase_orders.csv")
    f = st.file_uploader("Purchase orders CSV", type=["csv"], key="up_po", label_visibility="collapsed")
    if st.button("Import purchase orders", key="btn_po", type="primary", disabled=f is None):
        ok, result = run_upload(lambda db: upload_service.import_purchase_orders(db, WS, f.getvalue(), ACCOUNT["email"]))
        show_result(ok, f"Imported {result.created} purchase orders." if ok else result)

with tab_grn:
    st.markdown("**Goods received notes (CSV)** — what the warehouse actually received. "
                "Each `po_number` must already be in your workspace.")
    template_button("goods_received_notes.csv")
    f = st.file_uploader("GRN CSV", type=["csv"], key="up_grn", label_visibility="collapsed")
    if st.button("Import goods received notes", key="btn_grn", type="primary", disabled=f is None):
        ok, result = run_upload(lambda db: upload_service.import_grns(db, WS, f.getvalue(), ACCOUNT["email"]))
        show_result(ok, f"Imported {result.created} goods received notes." if ok else result)

with tab_prices:
    st.markdown("**Contract prices (CSV)** — the agreed unit price per supplier and item. "
                "The price check compares invoices against these.")
    template_button("contract_prices.csv")
    f = st.file_uploader("Contract prices CSV", type=["csv"], key="up_prices", label_visibility="collapsed")
    if st.button("Import contract prices", key="btn_prices", type="primary", disabled=f is None):
        ok, result = run_upload(lambda db: upload_service.import_contract_prices(db, WS, f.getvalue(), ACCOUNT["email"]))
        show_result(ok, f"Imported {result.created} contract prices." if ok else result)

with tab_contracts:
    st.markdown("**Contract documents** — TXT or PDF with selectable text (not a scanned photo). "
                "They become searchable for the Investigation Agent, in your workspace only.")
    supplier = st.text_input("Supplier this contract belongs to", key="contract_supplier",
                             placeholder="e.g. Acme Office Supplies")
    f = st.file_uploader("Contract file", type=["txt", "pdf"], key="up_contract", label_visibility="collapsed")
    if st.button("Add contract", key="btn_contract", type="primary", disabled=f is None):
        ok, result = run_upload(lambda db: upload_service.save_contract_document(
            db, WS, f.name, f.getvalue(), supplier, ACCOUNT["email"]))
        show_result(ok, "Contract added to your contract search." if ok else result)
