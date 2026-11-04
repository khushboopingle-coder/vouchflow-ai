"""
Shared helpers for the VouchFlow AI dashboard pages (Phase 8).

- Talks to the FastAPI backend first.
- If the backend is offline, falls back to calling the same service
  functions directly on the local database (same rules, same audit logs).
- Small formatting helpers and a light page style.
"""

import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

import requests
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
DASHBOARD_DIR = Path(__file__).resolve().parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import demo_setup  # noqa: E402

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
EVAL_DIR = BASE_DIR / "data" / "evaluation"

ACTION_LABELS = {
    "ready_for_human_approval": "Ready for human approval",
    "ask_supplier_for_clarification": "Ask supplier for clarification",
    "reject_and_escalate": "Reject and escalate",
    "needs_human_review": "Needs human review",
}
STATUS_LABELS = {
    "verified": "Verified",
    "needs_review": "Needs review",
    "mismatch_detected": "Mismatch detected",
    "pending_approval": "Pending approval",
}


# ---------------------------------------------------------------------
# Backend access
# ---------------------------------------------------------------------
@st.cache_data(ttl=10, show_spinner=False)
def backend_online() -> bool:
    """True if the API answers. Remembered for 10 seconds so pages stay fast."""
    try:
        return requests.get(f"{API_BASE_URL}/health", timeout=1.5).status_code == 200
    except requests.exceptions.RequestException:
        return False


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def _run_local(fallback: Callable) -> Tuple[bool, Any]:
    """Runs a service function on the local database when the API is offline."""
    from fastapi import HTTPException

    from backend.database.db import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        return True, _to_jsonable(fallback(db))
    except HTTPException as exc:
        return False, {"detail": exc.detail}
    except Exception as exc:  # show the error instead of crashing the page
        return False, {"detail": str(exc)}
    finally:
        db.close()


def api_call(
    method: str,
    path: str,
    fallback: Optional[Callable] = None,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: float = 10,
) -> Tuple[bool, Any]:
    """
    Calls the API and returns (ok, data). On connection failure uses `fallback(db)`.
    `data` is the JSON body, or {"detail": "..."} when something went wrong.
    """
    if not backend_online():
        if fallback is None:
            return False, {"detail": "Backend is offline."}
        return _run_local(fallback)
    try:
        response = requests.request(
            method, f"{API_BASE_URL}{path}", json=json_body, params=params, timeout=timeout
        )
        try:
            data = response.json()
        except ValueError:
            data = {"detail": response.text or "Unexpected server response"}
        if response.status_code == 200:
            return True, data
        detail = data.get("detail") if isinstance(data, dict) else data
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(str(d.get("msg", d)) for d in detail)
        return False, {"detail": detail}
    except requests.exceptions.RequestException:
        if fallback is None:
            return False, {"detail": "Backend is offline."}
        return _run_local(fallback)


def list_invoices() -> list:
    from backend.services import invoice_service

    ok, data = api_call(
        "GET", "/invoices", params={"limit": 500},
        fallback=lambda db: invoice_service.list_invoices(db=db, limit=500),
    )
    return data if ok and isinstance(data, list) else []


# ---------------------------------------------------------------------
# Formatting & style
# ---------------------------------------------------------------------
def money(value) -> str:
    try:
        return f"₹{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "—"


def action_label(action: Optional[str]) -> str:
    return ACTION_LABELS.get(action or "", action or "—")


def status_label(value: Optional[str]) -> str:
    return STATUS_LABELS.get(value or "", value or "—")


def action_box(action: Optional[str], text: str) -> None:
    """Shows a coloured box that matches the agent's recommendation."""
    if action == "ready_for_human_approval":
        st.success(text)
    elif action == "reject_and_escalate":
        st.error(text)
    else:
        st.warning(text)


def apply_page_style(title: str, subtitle: str) -> None:
    """Page header. Also runs the one-time demo start-up and shows the demo note,
    so it must be called before any backend import on the page."""
    demo_setup.ensure_demo_ready()
    st.markdown(
        """
        <style>
        /* Colours follow Streamlit's light/dark theme; only spacing and borders here. */
        .vf-sub { opacity: 0.75; margin-top: -0.6rem; margin-bottom: 1rem; }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-radius: 12px; padding: 0.8rem 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    demo_setup.show_demo_note()
    st.title(title)
    st.markdown(f'<div class="vf-sub">{subtitle}</div>', unsafe_allow_html=True)
    if not backend_online():
        st.caption("Standalone mode — running without the API, straight on the local database.")
