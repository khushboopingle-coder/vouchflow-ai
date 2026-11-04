"""
VouchFlow AI — dashboard entry point (router)
=============================================
Streamlit Community Cloud starts this file (main file path: dashboard/app.py).

It sets up the page, runs the one-time demo start-up, shows the login page until
somebody is logged in (Phase 2), draws the shared sidebar (brand, account, "Demo data"
badge, page menu, workspace tools, Log out) and then opens the chosen page:

    Home           -> dashboard/home.py   (invoice ledger)
    Investigation  -> dashboard/views/investigation.py
    Approvals      -> dashboard/views/approvals.py
    Evals          -> dashboard/views/evals.py

The pages live in views/, NOT pages/: Streamlit treats a folder called pages/ as its
old automatic multipage mode, which hides this router's sidebar and banner on those
pages and shows "Page not found" for direct links on a fresh server.
"""

import importlib
import sys
from pathlib import Path

import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent
BASE_DIR = DASHBOARD_DIR.parent
for path in (BASE_DIR, DASHBOARD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

st.set_page_config(
    page_title="VouchFlow AI | Invoice Operations",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _fresh_module(name: str):
    """Import a helper module, reloading it if its file changed since it was loaded.
    Streamlit only reloads the page scripts, not helper modules, so after an update
    (e.g. a new push on Streamlit Cloud) the server could keep an OLD ui_common in
    memory and fail with "has no attribute ...". This prevents that."""
    module = importlib.import_module(name)
    mtime = Path(module.__file__).stat().st_mtime
    if getattr(module, "_vf_loaded_mtime", None) != mtime:
        module = importlib.reload(module)
        module._vf_loaded_mtime = mtime
    return module


# Addresses come from the file names: /investigation, /approvals, /evals.
# Registered before the slow demo start-up so the page is known straight away.
# One icon style for the whole menu: rounded Material icons (coloured by the theme).
PAGES = [
    st.Page("home.py", title="Home", icon=":material/home:", default=True),
    st.Page("views/investigation.py", title="Investigation", icon=":material/manage_search:"),
    st.Page("views/approvals.py", title="Approvals", icon=":material/task_alt:"),
    st.Page("views/evals.py", title="Evals", icon=":material/insights:"),
]
LOGGED_IN = st.session_state.get("auth") is not None


def _show_login():
    from views import login

    login.render()


def _go_home():
    st.switch_page(PAGES[0])


if LOGGED_IN:
    # /login while logged in just sends you Home
    current = st.navigation(PAGES + [st.Page(_go_home, title="Log in", url_path="login")],
                            position="hidden")  # menu is drawn below the brand instead
else:
    # Phase 2: logged out -> EVERY address shows the login screen. The same url paths are
    # registered (so a link like /approvals never says "Page not found"); after login the
    # real page opens at that same address.
    current = st.navigation(
        [st.Page(_show_login, title="Log in", icon=":material/login:", default=True, url_path="welcome")]
        + [st.Page(_show_login, title="Log in", url_path=path)
           for path in ("investigation", "approvals", "evals", "login")],
        position="hidden",
    )

demo_setup = _fresh_module("demo_setup")
ui = _fresh_module("ui_common")

ui.apply_global_css()
# Demo start-up: works without API / .env / Gemini key (seeds an empty database once)
demo_setup.ensure_demo_ready()

if not LOGGED_IN:
    current.run()
    st.stop()

ui.render_sidebar_brand(PAGES, current)
if "flash" in st.session_state:
    kind, text = st.session_state.pop("flash")
    (st.success if kind == "ok" else st.error)(text)
ui.show_demo_banner()
current.run()
