"""
VouchFlow AI — dashboard entry point (router)
=============================================
Streamlit Community Cloud starts this file (main file path: dashboard/app.py).

It sets up the page, runs the one-time demo start-up, draws the shared sidebar
(brand, "Demo data" badge, page menu) and then opens the chosen page:

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
current = st.navigation(PAGES, position="hidden")  # menu is drawn below the brand instead

demo_setup = _fresh_module("demo_setup")
ui = _fresh_module("ui_common")

ui.apply_global_css()
# Demo start-up: works without API / .env / Gemini key (seeds an empty database once)
demo_setup.ensure_demo_ready()

ui.render_sidebar_brand(PAGES, current)
ui.show_demo_banner()
current.run()
