"""
Shared helpers for the VouchFlow AI dashboard.

- PALETTE: every colour of the dashboard lives here (change the theme in ONE place;
  keep .streamlit/config.toml in step — tests/test_theme.py checks that).
- apply_global_css(): the shared look, built from PALETTE. Called once at the top
  of app.py and of every page.
- Backend access: talks to the FastAPI backend first; if it is offline, calls the
  same service functions directly on the local database (same rules, same audit logs).
- Small formatting helpers, status pills, demo banner, sidebar brand, HTML table.
"""

import html
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
def show_demo_banner() -> None:
    st.markdown(f'<div class="demo-banner">🧪 <div>{demo_setup.DEMO_NOTE_HTML}</div></div>',
                unsafe_allow_html=True)


def render_sidebar_brand(pages: list, current=None) -> None:
    """Sidebar top: brand, small data badge, then the page menu.
    The open page (`current`, from st.navigation) is drawn as a brown pill."""
    online = backend_online()
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
            + (
                '<span class="demo-badge">● API connected · demo data</span>'
                if online
                else '<span class="demo-badge">● Demo data</span>'
            ),
            unsafe_allow_html=True,
        )
        for page in pages:
            if current is not None and page.url_path == current.url_path:
                st.markdown(
                    f'<div class="nav-active"><span>{page.icon}</span>{html.escape(page.title)}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.page_link(page)
        st.markdown("---")


def render_html_table(rows: List[Dict[str, Any]], status_column: Optional[str] = None,
                      numeric_columns: Tuple[str, ...] = ()) -> None:
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
        f'<div class="vf-table-wrap"><table class="vf-table"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def apply_page_style(title: str, subtitle: str) -> None:
    """Page header. Also runs the one-time demo start-up,
    so it must be called before any backend import on the page."""
    demo_setup.ensure_demo_ready()
    st.title(title)
    st.markdown(f'<div class="vf-sub">{html.escape(subtitle)}</div>', unsafe_allow_html=True)
