"""
VouchFlow AI — Investigation page (Phase 8)
Run the Investigation Agent on an invoice and read its report.
The agent only ADVISES. Decisions happen on the Approvals page.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import ui_common as ui  # noqa: E402

st.set_page_config(page_title="VouchFlow AI | Investigation", page_icon="🔎", layout="wide")
ui.apply_global_css()  # shared theme (colours from ui_common.PALETTE)
ui.apply_page_style(
    "🔎 Investigation",
    "The agent checks an invoice against its PO, goods received note and contract, "
    "then explains what it found. It never approves or pays.",
)

from backend.services import invoice_service  # noqa: E402

# ---------------------------------------------------------------------
# Pick an invoice
# ---------------------------------------------------------------------
invoices = ui.list_invoices()
if not invoices:
    st.info("No invoices found. Generate and seed data first (see CLAUDE.md).")
    st.stop()

options = {
    inv["id"]: f'#{inv["id"]} · {inv["invoice_number"]} · {inv.get("supplier_name") or "Unknown supplier"} · {ui.money(inv.get("grand_total"))}'
    for inv in invoices
}
pick_col, button_col = st.columns([4, 1])
with pick_col:
    invoice_id = st.selectbox(
        "Invoice", list(options.keys()), format_func=lambda i: options[i], key="investigation_invoice"
    )
with button_col:
    st.write("")
    st.write("")
    run_clicked = st.button("Run investigation", type="primary", width="stretch")

if run_clicked:
    with st.spinner("Agent is investigating... this can take up to a minute."):
        ok, data = ui.api_call(
            "POST", f"/invoices/{invoice_id}/investigate", timeout=180,
            fallback=lambda db: invoice_service.investigate_invoice(db=db, invoice_id=invoice_id, who="dashboard_user"),
        )
    if ok:
        st.success("Investigation finished. It is now waiting on the Approvals page.")
    else:
        st.error(f"Investigation failed: {data.get('detail')}")

ok, report = ui.api_call(
    "GET", f"/invoices/{invoice_id}/investigation",
    fallback=lambda db: invoice_service.get_invoice_investigation(db=db, invoice_id=invoice_id),
)
if not ok:
    st.info("This invoice has not been investigated yet. Click **Run investigation**.")
    st.stop()

# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------
st.markdown("---")
m1, m2, m3, m4 = st.columns([2, 1, 1, 1])  # first box wider so "Mismatch detected" fits
SHORT_STATUS = {"verified": "Verified", "mismatch_detected": "Mismatch", "needs_review": "Needs review"}
m1.metric("Check status", SHORT_STATUS.get(report.get("status"), ui.status_label(report.get("status"))))
m2.metric("Confidence", f'{float(report.get("confidence", 0)) * 100:.0f}%')
m3.metric("Findings", len(report.get("findings", [])))
m4.metric("Contract quotes", len(report.get("contract_citations", [])))

action = report.get("recommended_next_action")
ui.action_box(action, f"**Agent recommendation:** {ui.action_label(action)} (advice only — a person decides)")

st.subheader("Explanation")
st.write(report.get("explanation") or "—")
st.caption(
    ("Written by the LLM and checked by the grounding guardrail."
     if report.get("llm_used") else "Written from a fixed template (LLM not used).")
    + f' Report time: {report.get("created_at", "—")}'
)

# ---------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------
st.subheader("Findings and evidence")
findings = report.get("findings", [])
if not findings:
    st.write("No findings.")
else:
    table = pd.DataFrame([
        {
            "Check": f.get("check_name"),
            "Result": f.get("status"),
            "Mistake": f.get("mistake_type") or "—",
            "Difference": ui.money(f.get("difference_amount")),
            "Message": f.get("message"),
        }
        for f in findings
    ])
    st.dataframe(table, width="stretch", hide_index=True)
    for f in findings:
        if f.get("evidence"):
            passed = f.get("status") == "pass"
            raw = f["evidence"].get("raw_details") if isinstance(f["evidence"], dict) else None
            item = raw.get("item_name") if isinstance(raw, dict) else None
            title = f'Evidence for "{ui.humanize(f.get("check_name") or "check")}"'
            with st.expander(
                f"{title} · {item}" if item else title,  # item name tells the line items apart
                icon=":material/check_circle:" if passed else ":material/error:",
                expanded=not passed,  # open the problems straight away
            ):
                ui.render_evidence(f)

    # Raw JSON stays available for developers, out of the way
    with st.expander("Show raw data", icon=":material/data_object:"):
        st.json({f"{i + 1}. {f.get('check_name')}": f.get("evidence") for i, f in enumerate(findings)},
                expanded=False)

# ---------------------------------------------------------------------
# Contract citations
# ---------------------------------------------------------------------
st.subheader("Contract quotes")
citations = report.get("contract_citations", [])
if not citations:
    st.write("No contract clauses were cited.")
for c in citations:
    heading = " · ".join(x for x in [c.get("file_name"), c.get("clause_number"), c.get("clause_title")] if x)
    with st.expander(f'{heading or "Contract clause"} ({c.get("status", "found")})',
                     icon=":material/description:"):
        st.markdown(f"> {c.get('text', '')}")
        if c.get("relevance_to_finding"):
            st.caption(f"Why it matters: {c['relevance_to_finding']}")

# ---------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------
st.subheader("Guardrails")
g1, g2, g3 = st.columns(3)
checked = int(report.get("grounding_checked", 0))
failed = int(report.get("grounding_failed", 0))
g1.metric("Grounding", f"{checked - failed}/{checked} verified" if checked else "Not needed",
          help="Numbers and clauses in the explanation that were checked against the evidence")
g2.metric("Prompt injection", "Detected ⚠️" if report.get("injection_detected") else "None found")
blocked = report.get("blocked_actions", [])
g3.metric("Blocked actions", len(blocked))
if report.get("injection_detected"):
    st.error("Instruction-like text was found inside this invoice. It was ignored, but please check the document.")
if blocked:
    st.warning("The agent tried these actions and was blocked: " + ", ".join(blocked))

with st.expander("Limitations"):
    for item in report.get("limitations", []):
        st.write(f"- {item}")
