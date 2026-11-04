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


GLOBAL_CSS = """
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
    /* Sidebar: no big empty gap at the top, brand first, menu below it */
    /* the header row only holds the collapse button: float it top-right instead of a full row */
    [data-testid="stSidebarHeader"] {
        position: absolute; top: 0; right: 0; z-index: 5;
        height: auto; min-height: 0; padding: .55rem .55rem 0; margin: 0;
    }
    [data-testid="stSidebarHeader"] [data-testid="stLogoSpacer"] { display: none; }
    [data-testid="stSidebarUserContent"] { padding-top: 1rem !important; }
    [data-testid="stSidebarNav"] { display: none; }
    [data-testid="stSidebar"] * { color: #34483d; }

    /* Main area: enough top padding so the fixed header never hides the demo banner */
    .block-container, [data-testid="stMainBlockContainer"] {
        max-width: 1580px;
        padding-top: 4.75rem !important;
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
    div[data-baseweb="select"] > div, div[data-baseweb="input"],
    div[data-baseweb="textarea"] {
        background:#fffefa !important; border:1px solid #b7c2b4 !important;
        border-radius:10px !important;
    }
    div[data-baseweb="input"] > div, div[data-baseweb="textarea"] > div {
        background:#fffefa !important; border:0 !important;
    }
    div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within {
        border-color:#557b68 !important; box-shadow:0 0 0 2px rgba(85,123,104,.15);
    }
    input::placeholder, textarea::placeholder { color:#8a958b !important; opacity:1 !important; }
    .demo-badge {
        display:inline-flex; align-items:center; gap:6px; padding:4px 10px; margin:.2rem 0 .9rem;
        border-radius:999px; font-size:.72rem; font-weight:700; letter-spacing:.02em;
        border:1px solid #eadfc9; background:#f7f0e2; color:#8a6430;
    }
    .demo-badge.live { border-color:#d9e8d9; background:#e7f0e7; color:#52765b; }
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
"""


def apply_global_css() -> None:
    """Shared light look for every page (called once by the router in app.py)."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def render_sidebar_brand(pages: list) -> None:
    """Sidebar top: brand, small data badge, then the page menu."""
    online = backend_online()
    with st.sidebar:
        st.markdown(
            """
            <div class="brand-lockup">
                <div class="brand-mark">V</div>
                <div>
                    <div class="brand-name">VouchFlow <span style="color:#557b68">AI</span></div>
                    <div class="brand-caption">Invoice management, made simple</div>
                </div>
            </div>
            """
            + (
                '<span class="demo-badge live">● API connected · demo data</span>'
                if online
                else '<span class="demo-badge">● Demo data</span>'
            ),
            unsafe_allow_html=True,
        )
        for page in pages:
            st.page_link(page)
        st.markdown("---")


def apply_page_style(title: str, subtitle: str) -> None:
    """Page header. Also runs the one-time demo start-up,
    so it must be called before any backend import on the page."""
    demo_setup.ensure_demo_ready()
    st.markdown(
        """
        <style>
        .vf-sub { opacity: 0.75; margin-top: -0.6rem; margin-bottom: 1rem; }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-radius: 12px; padding: 0.8rem 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title(title)
    st.markdown(f'<div class="vf-sub">{subtitle}</div>', unsafe_allow_html=True)
