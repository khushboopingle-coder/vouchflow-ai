"""
VouchFlow AI — Evals page (Phase 8)
Shows the saved evaluation results from data/evaluation/*.csv.
READ-ONLY: this page never writes to any file (ground truth is never touched).
To refresh the numbers, re-run the scripts in scripts/ (see CLAUDE.md).
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import ui_common as ui  # noqa: E402

st.set_page_config(page_title="VouchFlow AI | Evals", page_icon="📊", layout="wide")
ui.apply_global_css()  # shared theme (colours from ui_common.PALETTE)
ui.apply_page_style(
    "📊 Evals",
    "How well each part of VouchFlow AI scores against the answer key. Numbers come from the saved result files.",
)


def load(name: str):
    path = ui.EVAL_DIR / name
    if not path.exists():
        return None, None
    updated = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return pd.read_csv(path), updated


def score(df: pd.DataFrame, column: str):
    """Returns ("97.9%", "47 of 48 correct") for a True/False result column."""
    if df is None or column not in df.columns or len(df) == 0:
        return "—", None
    values = df[column].astype(str).str.lower() == "true"
    return f"{values.mean() * 100:.1f}%", f"{values.sum()} of {len(df)} correct"


def score_grid(items, per_row: int = 3) -> None:
    """Draws score boxes, a few per row so the numbers always fit.
    items = list of (label, df, column)."""
    for start in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for col, (label, df, column) in zip(cols, items[start:start + per_row]):
            value, detail = score(df, column)
            col.metric(label, value, delta=detail, delta_color="off", delta_arrow="off")


def missing(name: str, script: str) -> None:
    st.info(f"`{name}` not found. Run `python scripts/{script}` to create it.")


SECTIONS = [
    ("Invoice reader", "extraction_results.csv", "run_extraction_eval.py"),
    ("3-way checker (normal)", "matching_results.csv", "run_matching_eval.py"),
    ("3-way checker (hard)", "hard_matching_results.csv", "run_matching_eval.py"),
    ("3-way checker (hard v2)", "hard_v2_matching_results.csv", "eval_hard_v2.py"),
    ("Contract search", "contract_rag_results.csv", "run_contract_rag_eval.py"),
    ("Investigation agent", "agent_results.csv", "run_agent_eval.py"),
]
HEADLINE_COLUMN = {
    "extraction_results.csv": "all_fields_match",
    "matching_results.csv": "multilabel_mistake_match",
    "hard_matching_results.csv": "multilabel_mistake_match",
    "hard_v2_matching_results.csv": "multilabel_mistake_match",
    "contract_rag_results.csv": "is_correct",
    "agent_results.csv": "overall_pass",
}

# ---------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------
data = {name: load(name) for _, name, _ in SECTIONS}
st.subheader("Overview")
score_grid([(label, data[name][0], HEADLINE_COLUMN[name]) for label, name, _ in SECTIONS])
st.caption("Each score = cases fully correct out of cases tested.")

tabs = st.tabs([label for label, _, _ in SECTIONS])

# ---------------------------------------------------------------------
# Invoice reader
# ---------------------------------------------------------------------
with tabs[0]:
    df, updated = data["extraction_results.csv"]
    if df is None:
        missing("extraction_results.csv", "run_extraction_eval.py")
    else:
        st.caption(f"{len(df)} invoices · last updated {updated}")
        fields = ["vendor_match", "invoice_number_match", "date_match", "total_match", "item_count_match", "all_fields_match"]
        score_grid([(f.replace("_match", "").replace("_", " ").title(), df, f) for f in fields])
        failed = df[df["all_fields_match"].astype(str).str.lower() != "true"]
        if len(failed):
            st.markdown("**Invoices not read perfectly**")
            st.dataframe(failed, width="stretch", hide_index=True)
        with st.expander("All rows"):
            st.dataframe(df, width="stretch", hide_index=True)

# ---------------------------------------------------------------------
# Matching (three result files with the same columns)
# ---------------------------------------------------------------------
for tab, name in zip(tabs[1:4], ["matching_results.csv", "hard_matching_results.csv", "hard_v2_matching_results.csv"]):
    with tab:
        df, updated = data[name]
        if df is None:
            missing(name, "run_matching_eval.py")
            continue
        st.caption(f"{len(df)} invoices · last updated {updated}")
        score_grid([
            ("Status correct", df, "status_match"),
            ("Main mistake correct", df, "strict_mistake_match"),
            ("All mistakes found", df, "multilabel_mistake_match"),
        ])
        st.markdown("**Confusion matrix** (rows = expected, columns = predicted)")
        st.dataframe(
            pd.crosstab(df["expected_status"], df["predicted_status"]),
            width="stretch",
        )
        st.markdown("**Mistake types in this set**")
        st.bar_chart(df["expected_mistake_type"].value_counts(), color=ui.PALETTE["primary"])
        with st.expander("All rows"):
            st.dataframe(df, width="stretch", hide_index=True)

# ---------------------------------------------------------------------
# Contract search
# ---------------------------------------------------------------------
with tabs[4]:
    df, updated = data["contract_rag_results.csv"]
    if df is None:
        missing("contract_rag_results.csv", "run_contract_rag_eval.py")
    else:
        st.caption(f"{len(df)} questions · last updated {updated}")
        score_grid([
            ("Found / not found correct", df, "status_match"),
            ("Right contract", df, "source_match"),
            ("Right keywords", df, "keyword_match"),
            ("Fully correct", df, "is_correct"),
        ], per_row=4)
        st.dataframe(
            df[["question_id", "question", "expected_source", "actual_source", "is_correct", "distance"]],
            width="stretch", hide_index=True,
        )

# ---------------------------------------------------------------------
# Investigation agent
# ---------------------------------------------------------------------
with tabs[5]:
    df, updated = data["agent_results.csv"]
    if df is None:
        missing("agent_results.csv", "run_agent_eval.py")
    else:
        st.caption(f"{len(df)} invoices · last updated {updated}")
        score_grid([
            ("Overall pass", df, "overall_pass"),
            ("Right action", df, "action_correct"),
            ("Right tools", df, "tools_correct"),
            ("Right citations", df, "citations_correct"),
            ("Safety passed", df, "safety_passed"),
        ])
        checked = int(df["grounding_checked"].sum())
        failed_claims = int(df["grounding_failed"].sum())
        st.caption(
            f"Grounding: {checked - failed_claims}/{checked} claims verified · "
            f"LLM used on {int((df['llm_used'].astype(str).str.lower() == 'true').sum())}/{len(df)} invoices"
        )
        st.markdown("**By dataset**")
        by_set = df.assign(passed=df["overall_pass"].astype(str).str.lower() == "true").groupby("dataset")["passed"].agg(["sum", "count"])
        by_set.columns = ["passed", "tested"]
        st.dataframe(by_set, width="stretch")
        st.dataframe(
            df[["invoice_id", "dataset", "supplier_name", "expected_status", "predicted_status",
                "predicted_action", "overall_pass", "failure_reason"]],
            width="stretch", hide_index=True,
        )
