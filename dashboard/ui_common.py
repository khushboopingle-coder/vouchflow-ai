"""
Shared helpers for the VouchFlow AI dashboard.

- PALETTE: every colour of the dashboard lives here (change the theme in ONE place;
  keep .streamlit/config.toml in step — tests/test_theme.py checks that).
- apply_global_css(): the shared look, built from PALETTE. Called once at the top
  of app.py and of every page.
- Login session (Phase 2): current_account(), require_login(), logout().
- Data access: run_db() calls the services directly, always with the logged-in user's
  workspace_id (same rules and audit logs as the API, which needs a login token).
- Small formatting helpers, status pills, demo banner, sidebar brand, HTML table.
"""

import dataclasses
import html
import json
import os
import sys
from pathlib import Path
from string import Template
from typing import Any, Callable, Dict, List, Optional, Tuple

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

# ---------------------------------------------------------------------
# THEME — the only place with colours (warm cream + chrome + earthy brown)
# ---------------------------------------------------------------------
PALETTE: Dict[str, str] = {
    # surfaces
    "bg": "#F4EEE7",            # page background (warm cream)
    "sidebar": "#E9DFD3",       # sidebar background (soft chrome-beige)
    "card": "#FBF8F4",          # cards, table rows
    "card_alt": "#F7F1EA",      # alternate table rows
    "card_border": "#DCCFC1",   # card / table borders
    "input": "#FFFFFF",         # search box, selects, text areas
    # chrome / metallic accent (gradient from light to dark)
    "chrome_light": "#E6DDD3",
    "chrome_dark": "#BFB2A5",
    # brand colours
    "primary": "#8C4B32",       # buttons, heading accents, active menu item
    "accent": "#C0703F",        # hover, highlights, links
    "on_primary": "#FFFFFF",    # text on brown
    # text
    "text": "#3A2A22",
    "muted": "#8A7A6E",
    # status colours (soft, not neon)
    "verified": "#5E7F5A",
    "needs_review": "#C98A2E",
    "mismatch_detected": "#B5483A",
    "pending_approval": "#8C4B32",
    # shadow tint (from the main text colour)
    "shadow": "#3A2A22",
}
FONT_FAMILY = "'DM Sans', 'Inter', system-ui, sans-serif"
FONT_URL = "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap"

STATUS_KEYS = ("verified", "needs_review", "mismatch_detected", "pending_approval")
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


def tint(hex_color: str, alpha: float) -> str:
    """'#8C4B32', 0.15 -> 'rgba(140,75,50,0.15)' (soft background from a palette colour)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------------
# Login session (Phase 2)
# ---------------------------------------------------------------------
AUTH_KEY = "auth"


def current_account() -> Optional[Dict[str, Any]]:
    """The logged-in account {user_id, email, workspace_id, workspace_name}, or None."""
    return st.session_state.get(AUTH_KEY)


def set_account(account) -> None:
    """Store a backend.services.auth_service.Account in this browser session."""
    st.session_state[AUTH_KEY] = {
        "user_id": account.user_id,
        "email": account.email,
        "workspace_id": account.workspace_id,
        "workspace_name": account.workspace_name,
    }


def logout() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def workspace_id() -> int:
    account = current_account()
    if not account:
        raise RuntimeError("Not logged in.")
    return int(account["workspace_id"])


def require_login() -> Dict[str, Any]:
    """Stops the page (with a friendly note) when nobody is logged in."""
    account = current_account()
    if not account:
        st.info("Please log in to see your workspace.")
        st.stop()
    return account


# ---------------------------------------------------------------------
# Data access: the dashboard calls the services directly, ALWAYS with the
# logged-in user's workspace_id, so it can only ever see that workspace.
# ---------------------------------------------------------------------
def _to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def run_db(fn: Callable) -> Tuple[bool, Any]:
    """Runs fn(db) and returns (ok, data). Errors become {"detail": "..."} instead of a crash."""
    from fastapi import HTTPException

    from backend.database.db import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        return True, _to_jsonable(fn(db))
    except HTTPException as exc:
        return False, {"detail": exc.detail}
    except Exception as exc:  # show the error type instead of crashing the page
        return False, {"detail": f"{type(exc).__name__}: {exc}"}
    finally:
        db.close()


def list_invoices() -> list:
    from backend.services import invoice_service

    ws = workspace_id()
    ok, data = run_db(lambda db: invoice_service.list_invoices(db=db, workspace_id=ws, limit=500))
    return data if ok and isinstance(data, list) else []


# ---------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------
def money(value) -> str:
    try:
        return f"₹{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "—"


def action_label(action: Optional[str]) -> str:
    return ACTION_LABELS.get(action or "", action or "—")


def status_label(value: Optional[str]) -> str:
    return STATUS_LABELS.get(value or "", (value or "—").replace("_", " ").title())


def status_pill(status: Optional[str]) -> str:
    """HTML pill for an invoice status (colours from PALETTE, see .vf-pill in the CSS)."""
    key = status if status in STATUS_KEYS else "other"
    return f'<span class="vf-pill vf-{key}">{html.escape(status_label(status))}</span>'


# Finding result -> (palette status key, label) for the Match / Mismatch pill
RESULT_PILLS = {
    "pass": ("verified", "Match"),
    "fail": ("mismatch_detected", "Mismatch"),
    "warning": ("needs_review", "Check"),
}
_WORD_FIXES = {"po": "PO", "grn": "GRN", "gst": "GST", "18pct": "18%", "id": "ID", "pct": "%"}
_MONEY_WORDS = ("price", "total", "subtotal", "amount", "tax", "difference")
_EVIDENCE_META = ("values_compared", "sources", "raw_details", "difference_amount", "details")


def result_pill(status: Optional[str]) -> str:
    """Green "Match" for a passed check, red "Mismatch" for a failed one."""
    key, label = RESULT_PILLS.get(status or "", ("other", (status or "—").title()))
    return f'<span class="vf-pill vf-{key}">{html.escape(label)}</span>'


def humanize(key: str) -> str:
    """'po_unit_price' -> 'PO unit price'."""
    words = [_WORD_FIXES.get(w, w) for w in str(key).split("_") if w]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def format_evidence_value(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)) and any(w in str(key).lower() for w in _MONEY_WORDS):
        return money(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def evidence_rows(evidence: Any) -> List[Dict[str, str]]:
    """Turns a finding's evidence into rows: What we compared | Value | Source.
    Uses values_compared + sources when present, otherwise the plain keys."""
    if not isinstance(evidence, dict):
        return []
    compared = evidence.get("values_compared")
    sources = evidence.get("sources") if isinstance(evidence.get("sources"), dict) else {}
    if not isinstance(compared, dict) or not compared:
        compared = {k: v for k, v in evidence.items() if k not in _EVIDENCE_META}
    return [
        {
            "What we compared": humanize(k),
            "Value": format_evidence_value(k, v),
            "Source": sources.get(k) or "—",
        }
        for k, v in compared.items()
    ]


def render_evidence(finding: Dict[str, Any]) -> None:
    """Clean evidence view for one finding: result pill, difference, item, table."""
    evidence = finding.get("evidence") or {}
    raw = evidence.get("raw_details") if isinstance(evidence, dict) else None
    item = raw.get("item_name") if isinstance(raw, dict) else None
    diff = finding.get("difference_amount") or 0
    parts = [result_pill(finding.get("status"))]
    parts.append(f'<span class="evidence-meta">Difference: <b>{html.escape(money(diff))}</b></span>')
    if item:
        parts.append(f'<span class="evidence-meta">Item: <b>{html.escape(str(item))}</b></span>')
    st.markdown(f'<div class="evidence-head">{"".join(parts)}</div>', unsafe_allow_html=True)
    if finding.get("message"):
        st.markdown(f'<div class="evidence-msg">{html.escape(str(finding["message"]))}</div>',
                    unsafe_allow_html=True)
    rows = evidence_rows(evidence)
    if rows:
        render_html_table(rows, compact=True)
    else:
        st.caption("No values were recorded for this check.")


def action_box(action: Optional[str], text: str) -> None:
    """Shows a coloured box that matches the agent's recommendation."""
    if action == "ready_for_human_approval":
        st.success(text)
    elif action == "reject_and_escalate":
        st.error(text)
    else:
        st.warning(text)


# ---------------------------------------------------------------------
# Global CSS (built from PALETTE)
# ---------------------------------------------------------------------
_CSS = Template("""
<style>
@import url('$font_url');

/* ---------- base ---------- */
html, body, .stApp, .stMarkdown, p, li, label, input, textarea, button, td, th,
h1, h2, h3, h4, h5, h6, [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
    font-family: $font;
}
.stApp { background: $bg; color: $text; }
h1, h2, h3, h4, p, label, li { color: $text; }
h1, h2, h3 { letter-spacing: -.02em; font-weight: 750; }
h1 { font-size: 2rem !important; }
h2 { font-size: 1.3rem !important; }
h3 { font-size: 1.05rem !important; }
a, a:visited { color: $accent; }
[data-testid="stCaptionContainer"], small { color: $muted !important; }
#MainMenu, footer { visibility: hidden; }

/* Streamlit's fixed top bar: cream, so it blends with the page */
[data-testid="stHeader"] { background: $header_bg; backdrop-filter: blur(10px); }

/* Main area: enough top padding so the top bar never hides the demo banner */
.block-container, [data-testid="stMainBlockContainer"] {
    max-width: 1580px; padding-top: 4.75rem !important; padding-bottom: 3rem;
}

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] { background: $sidebar; border-right: 1px solid $chrome_dark; }
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span { color: $text; }
/* the header row only holds the collapse button: float it top-right instead of a full row */
[data-testid="stSidebarHeader"] {
    position: absolute; top: 0; right: 0; z-index: 5;
    height: auto; min-height: 0; padding: .55rem .55rem 0; margin: 0;
}
[data-testid="stSidebarHeader"] [data-testid="stLogoSpacer"] { display: none; }
[data-testid="stSidebarUserContent"] { padding-top: 1rem !important; }
[data-testid="stSidebarNav"] { display: none; }

.brand-lockup { display: flex; align-items: center; gap: 12px; margin: 0 0 .6rem; }
.brand-mark {
    width: 42px; height: 42px; display: flex; align-items: center; justify-content: center;
    border-radius: 14px; font-weight: 800; font-size: 1.25rem; color: $on_primary;
    background: linear-gradient(145deg, $accent, $primary);
    box-shadow: 0 6px 16px $shadow_soft;
}
.brand-name { font-weight: 800; font-size: 1.1rem; color: $text; }
.brand-name span { color: $primary; }
.brand-caption { color: $muted; font-size: .66rem; letter-spacing: .1em; text-transform: uppercase; margin-top: 3px; }
.sidebar-label {
    color: $muted; font-size: .68rem; font-weight: 800;
    letter-spacing: .13em; text-transform: uppercase; margin: 1.1rem 0 .6rem;
}
/* ---------- login page ---------- */
.login-hero { text-align: center; margin: .5rem 0 1.4rem; }
.login-mark { margin: 0 auto .8rem; width: 56px; height: 56px; font-size: 1.6rem; }
.login-title { font-weight: 800; font-size: 2rem; color: $text; letter-spacing: -.03em; }
.login-title span { color: $primary; }
.login-sub { color: $muted; font-size: .95rem; max-width: 460px; margin: .4rem auto 0; }
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 1.2rem; }
.account-box { margin: 0 0 .55rem; padding: 8px 11px; border-radius: 12px;
    background: $card; border: 1px solid $card_border; }
.account-email { color: $text; font-size: .8rem; font-weight: 700; overflow: hidden; text-overflow: ellipsis; }
.account-ws { color: $muted; font-size: .72rem; }
.demo-badge.live { color: $verified; border-color: $card_border; background: $card; }
.danger-note { color: $mismatch_detected; font-size: .78rem; font-weight: 700; }
.demo-badge {
    display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px; margin: .2rem 0 .9rem;
    border-radius: 999px; font-size: .72rem; font-weight: 700; letter-spacing: .02em;
    color: $primary; border: 1px solid $chrome_dark;
    background: linear-gradient(180deg, $chrome_light, $chrome_dark);
}
/* page menu (the open page is drawn as .nav-active by render_sidebar_brand) */
.nav-active {
    display: flex; align-items: center; gap: .55rem; padding: .42rem .6rem; margin: 0 0 .15rem;
    border-radius: 10px; background: $primary; color: $on_primary; font-weight: 650; font-size: .875rem;
    box-shadow: 0 3px 10px $shadow_soft;
}
[data-testid="stPageLink"] a { border-radius: 10px; padding: .35rem .6rem; background: transparent !important; }
[data-testid="stPageLink"] a:hover { background: $accent_soft; }
[data-testid="stPageLink"] a:hover span { color: $accent !important; }
/* same icon style for every menu item: rounded Material icons in brown */
[data-testid="stPageLink"] [data-testid="stIconMaterial"] { color: $primary !important; }
/* white text + icon on the brown active item (beats the general sidebar text colour) */
[data-testid="stSidebar"] .nav-active, [data-testid="stSidebar"] .nav-active span { color: $on_primary !important; }
.nav-icon { font-family: 'Material Symbols Rounded'; font-size: 1rem; line-height: 1;
    font-weight: normal; font-style: normal; color: $on_primary;
    -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga'; }

/* ---------- chrome accents ---------- */
hr { border: 0 !important; height: 1px; margin: 1.5rem 0 !important;
     background: linear-gradient(90deg, $chrome_light, $chrome_dark, $chrome_light) !important; }
.chrome-head {
    margin: -19px -20px 14px; padding: 10px 20px; border-radius: 16px 16px 0 0;
    background: linear-gradient(180deg, $chrome_light, $chrome_dark);
    color: $text; font-weight: 750; font-size: .85rem; letter-spacing: .02em;
}
.progress-track { height: 8px; border-radius: 20px; overflow: hidden;
    background: linear-gradient(180deg, $chrome_light, $chrome_dark); }
.progress-fill { height: 100%; border-radius: 20px; background: linear-gradient(90deg, $primary, $accent); }

/* demo banner */
.demo-banner {
    display: flex; gap: 10px; align-items: flex-start; padding: 12px 16px; margin-bottom: 1.2rem;
    border-radius: 14px; border: 1px solid $chrome_dark; border-left: 5px solid $primary;
    background: linear-gradient(180deg, $chrome_light, $card); color: $text; font-size: .92rem;
}
.demo-banner b { color: $primary; }

/* ---------- cards ---------- */
.metric-card, .surface, div[data-testid="stMetric"], [data-testid="stExpander"] details,
[data-testid="stForm"] {
    background: $card; border: 1px solid $card_border !important; border-radius: 16px;
    box-shadow: 0 4px 16px $shadow_soft;
}
div[data-testid="stMetric"] { padding: .8rem 1rem; }
.metric-card { min-height: 137px; padding: 20px 21px; }
.surface { padding: 19px 20px; }
.metric-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.metric-label { color: $muted; font-size: .81rem; font-weight: 600; }
.metric-icon { display: flex; align-items: center; justify-content: center;
    width: 34px; height: 34px; border-radius: 11px; font-size: 16px; }
.metric-value { color: $text; font-weight: 800; font-size: 1.9rem; margin-top: 13px; letter-spacing: -.03em; }
.metric-foot { color: $muted; font-size: .72rem; margin-top: 3px; }
.big-number { font-weight: 800; font-size: 1.8rem; margin: 5px 0; }
.card-label { color: $muted; font-size: .77rem; }
$metric_icon_rules

.eyebrow { color: $primary; font-size: .7rem; font-weight: 800; letter-spacing: .15em;
    text-transform: uppercase; margin-bottom: .55rem; }
.page-heading { font-weight: 800; font-size: 2rem; color: $text; letter-spacing: -.035em; }
.page-subtitle, .vf-sub { color: $muted; font-size: .94rem; margin-top: .4rem; }
.vf-sub { margin-top: -0.6rem; margin-bottom: 1rem; }
.topline { display: flex; justify-content: space-between; align-items: center;
    gap: 12px; flex-wrap: wrap; margin-bottom: 1.8rem; }
.live-pill { display: inline-flex; align-items: center; gap: 8px; padding: 8px 13px;
    border-radius: 999px; font-size: .75rem; font-weight: 700; color: $primary;
    border: 1px solid $chrome_dark; background: linear-gradient(180deg, $chrome_light, $chrome_dark); }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: $verified; }
.section-kicker { color: $muted; font-size: .72rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.surface-heading { font-weight: 750; font-size: 1.06rem; color: $text; }
.surface-caption, .muted-note { color: $muted; font-size: .81rem; margin-top: 4px; }
.muted-note { font-size: .76rem; }
.muted-note b { color: $text; }
.records { text-align: right; color: $muted; padding: 9px 2px; font-size: .8rem; }
.records b { color: $text; }
.amount { color: $text; }
.amount.total { color: $primary; }
.footer-note { text-align: center; color: $muted; font-size: .74rem; padding-top: 2rem; }

/* ---------- buttons ---------- */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
    background: $primary !important; color: $on_primary !important; border: 0 !important;
    border-radius: 10px !important; font-weight: 650 !important; transition: background .18s ease;
}
.stButton > button *, .stFormSubmitButton > button *, .stDownloadButton > button * { color: $on_primary !important; }
.stButton > button:hover, .stFormSubmitButton > button:hover, .stDownloadButton > button:hover,
.stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible {
    background: $accent !important; color: $on_primary !important;
}

/* ---------- inputs: white, chrome border, visible placeholder ---------- */
div[data-baseweb="input"], div[data-baseweb="textarea"], div[data-baseweb="select"] > div {
    background: $input !important; border: 1px solid $chrome_dark !important; border-radius: 10px !important;
}
div[data-baseweb="input"] > div, div[data-baseweb="textarea"] > div { background: $input !important; border: 0 !important; }
div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within,
div[data-baseweb="select"] > div:focus-within {
    border-color: $accent !important; box-shadow: 0 0 0 2px $accent_soft;
}
input, textarea { color: $text !important; }
input::placeholder, textarea::placeholder { color: $muted !important; opacity: 1 !important; }
[data-testid="stFileUploader"] section {
    border: 1px dashed $chrome_dark !important; border-radius: 13px; background: $card;
}
[data-testid="stDataFrame"] { border: 1px solid $card_border; border-radius: 12px; overflow: hidden; }
.stAlert { border-radius: 12px; }

/* ---------- invoice ledger table ---------- */
.vf-table-wrap { max-height: 430px; overflow: auto; border: 1px solid $card_border;
    border-radius: 16px; background: $card; box-shadow: 0 4px 16px $shadow_soft; }
table.vf-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: .84rem; }
table.vf-table thead th {
    position: sticky; top: 0; z-index: 1; text-align: left; white-space: nowrap;
    background: $primary; color: $on_primary; font-weight: 700; padding: 10px 12px;
    border-bottom: 2px solid $chrome_dark;
}
table.vf-table tbody td {
    padding: 9px 12px; color: $text; background: $card; white-space: nowrap;
    border-bottom: 1px solid $chrome_light;
}
table.vf-table tbody tr:nth-child(even) td { background: $card_alt; }
table.vf-table tbody tr:hover td { background: $accent_soft; }
table.vf-table td.num { text-align: right; font-variant-numeric: tabular-nums; }

.vf-table-wrap.compact { max-height: none; box-shadow: none; margin-bottom: .4rem; }
.vf-table-wrap.compact table.vf-table tbody td { white-space: normal; }

/* ---------- evidence (Investigation page) ---------- */
.evidence-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: .1rem 0 .5rem; }
.evidence-meta { color: $muted; font-size: .82rem; padding: 3px 10px; border-radius: 999px;
    border: 1px solid $chrome_dark; background: linear-gradient(180deg, $chrome_light, $card); }
.evidence-meta b { color: $text; }
.evidence-msg { color: $text; font-size: .88rem; margin: 0 0 .6rem; }

/* ---------- status pills ---------- */
.vf-pill { display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-size: .76rem; font-weight: 700; border: 1px solid transparent; }
$pill_rules
</style>
""")


def _status_rules() -> Tuple[str, str]:
    pills, icons = [], []
    for key in STATUS_KEYS:
        color = PALETTE[key]
        pills.append(
            f".vf-pill.vf-{key} {{ color: {color}; background: {tint(color, .13)}; border-color: {tint(color, .35)}; }}"
        )
    pills.append(
        f".vf-pill.vf-other {{ color: {PALETTE['muted']}; background: {PALETTE['chrome_light']}; "
        f"border-color: {PALETTE['chrome_dark']}; }}"
    )
    for kind, key in (("total", "primary"), ("verified", "verified"),
                      ("needs_review", "needs_review"), ("mismatch_detected", "mismatch_detected")):
        color = PALETTE[key]
        icons.append(f".metric-icon.k-{kind} {{ color: {color}; background: {tint(color, .13)}; }}")
    return "\n".join(pills), "\n".join(icons)


def build_global_css() -> str:
    pill_rules, metric_icon_rules = _status_rules()
    return _CSS.substitute(
        **PALETTE,
        font=FONT_FAMILY,
        font_url=FONT_URL,
        header_bg=tint(PALETTE["bg"], .88),
        shadow_soft=tint(PALETTE["shadow"], .06),
        accent_soft=tint(PALETTE["accent"], .14),
        pill_rules=pill_rules,
        metric_icon_rules=metric_icon_rules,
    )


def apply_global_css() -> None:
    """Shared look for every page. Call once at the top of app.py and of each page."""
    st.markdown(build_global_css(), unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Shared page parts
# ---------------------------------------------------------------------
def workspace_flags() -> Dict[str, Any]:
    """{"is_demo", "invoice_count", "sample_loaded", "has_user_data"} for the logged-in workspace.
    Demo = the sample copy and nothing the user added (Phase 3)."""
    from backend.services import workspace_service

    ws = workspace_id()

    def _read(db):
        w = workspace_service.get_workspace(db, ws)
        return {
            "is_demo": workspace_service.is_demo(w),
            "invoice_count": workspace_service.workspace_invoice_count(db, ws),
            "sample_loaded": bool(w and w.sample_loaded),
            "has_user_data": bool(w and w.has_user_data),
        }

    ok, flags = run_db(_read)
    return flags if ok else {"is_demo": False, "invoice_count": 0, "sample_loaded": False, "has_user_data": False}


def show_demo_banner() -> None:
    """The "Demo mode" banner, ONLY while the workspace holds nothing but the sample data."""
    if workspace_flags()["is_demo"]:
        st.markdown(f'<div class="demo-banner">🧪 <div>{demo_setup.DEMO_NOTE_HTML}</div></div>',
                    unsafe_allow_html=True)


def material_name(icon: Optional[str]) -> str:
    """':material/home:' -> 'home' (for drawing the icon in our own HTML)."""
    icon = icon or ""
    if icon.startswith(":material/") and icon.endswith(":"):
        return html.escape(icon[len(":material/"):-1])
    return html.escape(icon)


def render_sidebar_brand(pages: list, current=None) -> None:
    """Sidebar top: brand, logged-in email + workspace, data badge, page menu,
    workspace tools (load sample data) and Logout.
    The open page (`current`, from st.navigation) is drawn as a brown pill."""
    account = current_account() or {}
    with st.sidebar:
        st.markdown(
            """
            <div class="brand-lockup">
                <div class="brand-mark">V</div>
                <div>
                    <div class="brand-name">VouchFlow <span>AI</span></div>
                    <div class="brand-caption">Invoice management, made simple</div>
                </div>
            </div>
            """
            + f'<div class="account-box"><div class="account-email">{html.escape(account.get("email", ""))}</div>'
            + f'<div class="account-ws">{html.escape(account.get("workspace_name", ""))}</div></div>'
            + ('<span class="demo-badge">● Demo data</span>' if workspace_flags()["is_demo"]
               else '<span class="demo-badge live">● Live workspace</span>'),
            unsafe_allow_html=True,
        )
        for page in pages:
            if current is not None and page.url_path == current.url_path:
                st.markdown(
                    f'<div class="nav-active"><span class="nav-icon">{material_name(page.icon)}</span>'
                    f'{html.escape(page.title)}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.page_link(page)
        st.markdown("---")
        render_workspace_tools()
        if st.button("Log out", key="logout_button", icon=":material/logout:", width="stretch"):
            logout()
            st.rerun()
        st.markdown("---")


def render_workspace_tools() -> None:
    """Load / reset sample data and delete the workspace (each with a confirmation step)."""
    from backend.services import workspace_service

    ws = workspace_id()
    email = (current_account() or {}).get("email", "dashboard_user")
    flags = workspace_flags()
    with st.expander("Workspace tools", icon=":material/folder_managed:"):
        label = "Demo data" if flags["is_demo"] else "Live workspace"
        st.caption(f"{flags['invoice_count']} invoices · {label}")

        empty = flags["invoice_count"] == 0 and not flags["has_user_data"]
        if empty:
            go = st.button("Load sample data", key="load_sample_button", width="stretch")
        else:
            sure = st.checkbox("Replace ALL my data with the sample data", key="confirm_sample_reset")
            go = st.button("Reset to sample data", key="reset_sample_button", width="stretch", disabled=not sure)
        if go:
            with st.spinner("Copying the sample data into your workspace..."):
                done, result = run_db(lambda db: workspace_service.load_sample_data(db, ws, who=email))
            if done:
                st.session_state["flash"] = ("ok", f"Loaded {len(result['invoices'])} sample invoices.")
                st.rerun()
            else:
                st.error(result.get("detail"))

        st.markdown('<div class="danger-note">Delete my workspace</div>', unsafe_allow_html=True)
        st.caption("Deletes your account and ALL data in this workspace. This cannot be undone.")
        typed = st.text_input("Type DELETE to confirm", key="confirm_delete_text", label_visibility="collapsed",
                              placeholder="Type DELETE to confirm")
        if st.button("Delete my workspace", key="delete_workspace_button", width="stretch",
                     disabled=typed.strip() != "DELETE"):
            done, result = run_db(lambda db: workspace_service.delete_workspace(db, ws))
            if done:
                logout()
                st.rerun()
            else:
                st.error(result.get("detail"))


def render_html_table(rows: List[Dict[str, Any]], status_column: Optional[str] = None,
                      numeric_columns: Tuple[str, ...] = (), compact: bool = False) -> None:
    """Styled HTML table (cream rows, brown header, chrome borders, status pills).
    `rows` are dicts with display values; the status column holds raw status keys."""
    if not rows:
        return
    columns = list(rows[0].keys())
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in columns)
    body = []
    for row in rows:
        cells = []
        for c in columns:
            value = row.get(c)
            if c == status_column:
                cells.append(f"<td>{status_pill(value)}</td>")
            else:
                cls = ' class="num"' if c in numeric_columns else ""
                cells.append(f"<td{cls}>{html.escape('—' if value is None else str(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(
        f'<div class="vf-table-wrap{" compact" if compact else ""}"><table class="vf-table"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def apply_page_style(title: str, subtitle: str) -> None:
    """Page header. Also runs the one-time demo start-up,
    so it must be called before any backend import on the page."""
    demo_setup.ensure_demo_ready()
    require_login()
    st.title(title)
    st.markdown(f'<div class="vf-sub">{html.escape(subtitle)}</div>', unsafe_allow_html=True)
