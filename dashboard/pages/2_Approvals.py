"""
VouchFlow AI — Approvals page (Phase 8)
A finance PERSON approves or rejects investigated invoices here.
The rules (human name, notes, one decision per report) are enforced by the backend.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import ui_common as ui  # noqa: E402

st.set_page_config(page_title="VouchFlow AI | Approvals", page_icon="✅", layout="wide")
ui.apply_page_style(
    "✅ Approvals",
    "Invoices the agent has investigated wait here. Only a named person can approve or reject them.",
)

from backend.database.schemas import DecisionCreate  # noqa: E402
from backend.services import approval_service, invoice_service  # noqa: E402

# Show the result of the last submit (kept across the rerun)
if "approval_flash" in st.session_state:
    kind, text = st.session_state.pop("approval_flash")
    (st.success if kind == "ok" else st.error)(text)

# ---------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------
ok, queue = ui.api_call("GET", "/approvals/queue", fallback=approval_service.get_approval_queue)
if not ok:
    st.error(f"Could not load the approval queue: {queue.get('detail')}")
    queue = []

st.subheader(f"Waiting for a decision ({len(queue)})")
if not queue:
    st.info("Nothing is waiting. Run an investigation on the Investigation page first.")
else:
    st.dataframe(
        pd.DataFrame([
            {
                "Invoice": q["invoice_number"],
                "Supplier": q.get("supplier_name") or "—",
                "Total": ui.money(q.get("grand_total")),
                "Check status": ui.status_label(q.get("investigation_status")),
                "Agent recommends": ui.action_label(q.get("recommended_next_action")),
                "Confidence": f'{float(q.get("confidence", 0)) * 100:.0f}%',
                "Investigated": str(q.get("investigated_at", ""))[:19].replace("T", " "),
            }
            for q in queue
        ]),
        width="stretch",
        hide_index=True,
    )

    by_id = {q["invoice_id"]: q for q in queue}
    invoice_id = st.selectbox(
        "Choose an invoice to decide",
        list(by_id.keys()),
        format_func=lambda i: f'{by_id[i]["invoice_number"]} · {by_id[i].get("supplier_name") or "—"} · {ui.money(by_id[i].get("grand_total"))}',
    )
    item = by_id[invoice_id]
    agent_action = item.get("recommended_next_action")

    # Short summary of the agent's report
    ok_r, report = ui.api_call(
        "GET", f"/invoices/{invoice_id}/investigation",
        fallback=lambda db: invoice_service.get_invoice_investigation(db=db, invoice_id=invoice_id),
    )
    ui.action_box(agent_action, f"**Agent recommendation:** {ui.action_label(agent_action)}")
    if ok_r:
        st.write(report.get("explanation") or "—")
        problems = [f for f in report.get("findings", []) if f.get("status") != "pass"]
        for f in problems:
            st.markdown(f'- **{f.get("check_name")}**: {f.get("message")} ({ui.money(f.get("difference_amount"))})')
        st.caption("Open the Investigation page for full evidence and contract quotes.")

    # Decision form
    note_needed = agent_action != "ready_for_human_approval"
    with st.form("decision_form", clear_on_submit=True):
        st.markdown("**Your decision**")
        decided_by = st.text_input("Your full name", placeholder="e.g. Priya Sharma")
        decision = st.radio("Decision", ["approved", "rejected"], horizontal=True,
                            format_func=lambda d: "Approve" if d == "approved" else "Reject")
        note = st.text_area(
            "Note" + (" (required — you are going against the agent's advice if you approve)" if note_needed
                      else " (required if you reject)"),
        )
        submitted = st.form_submit_button("Submit decision", type="primary")

    if submitted:
        body = {"decision": decision, "decided_by": decided_by, "note": note}
        ok_d, result = ui.api_call(
            "POST", f"/invoices/{invoice_id}/decision", json_body=body,
            fallback=lambda db: approval_service.record_decision(
                db=db, invoice_id=invoice_id, payload=DecisionCreate(**body)
            ),
        )
        if ok_d:
            st.session_state["approval_flash"] = (
                "ok", f'{item["invoice_number"]} was {result["decision"]} by {result["decided_by"]}.'
            )
            st.rerun()
        else:
            st.error(result.get("detail"))

# ---------------------------------------------------------------------
# History
# ---------------------------------------------------------------------
st.markdown("---")
st.subheader("Recent decisions")
ok_h, history = ui.api_call(
    "GET", "/approvals/decisions", params={"limit": 50},
    fallback=lambda db: approval_service.list_decisions(db=db, limit=50),
)
if ok_h and history:
    st.dataframe(
        pd.DataFrame([
            {
                "When": str(h.get("created_at", ""))[:19].replace("T", " "),
                "Invoice": h.get("invoice_number") or h.get("invoice_id"),
                "Decision": h.get("decision"),
                "By": h.get("decided_by"),
                "Agent advised": ui.action_label(h.get("agent_recommendation")),
                "Note": h.get("note") or "",
            }
            for h in history
        ]),
        width="stretch",
        hide_index=True,
    )
else:
    st.write("No decisions yet.")
