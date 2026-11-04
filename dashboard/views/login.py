"""
VouchFlow AI — Log in / Create account (Phase 2)
The router (dashboard/app.py) calls render() for EVERY address while nobody is logged in.
Passwords are checked and stored by backend/services/auth_service.py (bcrypt hashes only).
"""

import sys
from pathlib import Path

import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import ui_common as ui  # noqa: E402


def render() -> None:
    """The login / create-account screen (called by the router while logged out)."""
    from backend.services import auth_service

    st.set_page_config(page_title="VouchFlow AI | Log in", page_icon="🧾", layout="centered")
    ui.apply_global_css()  # shared theme (colours from ui_common.PALETTE)
    st.markdown('<style>[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],'
                '[data-testid="stExpandSidebarButton"] { display: none !important; }</style>',
                unsafe_allow_html=True)

    st.markdown(
        """
        <div class="login-hero">
            <div class="brand-mark login-mark">V</div>
            <div class="login-title">VouchFlow <span>AI</span></div>
            <div class="login-sub">AI checks every supplier invoice against the purchase order,
            goods received note and contract. A person always approves.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_tab, signup_tab = st.tabs(["Log in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="you@company.com", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Log in", type="primary", width="stretch")
        if submitted:
            ok, account = ui.run_db(lambda db: auth_service.login(db, email, password))
            if ok and account:
                ui.set_account(auth_service.Account(**account))
                st.rerun()
            else:
                st.error("Wrong email or password.")

    with signup_tab:
        with st.form("signup_form"):
            new_email = st.text_input("Email", placeholder="you@company.com", key="signup_email")
            new_password = st.text_input("Password (at least 8 characters)", type="password", key="signup_password")
            repeat = st.text_input("Repeat password", type="password", key="signup_repeat")
            with_sample = st.checkbox("Start with sample data (recommended)", value=True, key="signup_sample")
            created = st.form_submit_button("Create account", type="primary", width="stretch")
        if created:
            if new_password != repeat:
                st.error("The two passwords are not the same.")
            else:
                with st.spinner("Creating your private workspace..."):
                    ok, account = ui.run_db(
                        lambda db: auth_service.signup(db, new_email, new_password, load_sample=with_sample))
                if ok:
                    ui.set_account(auth_service.Account(**account))
                    st.rerun()
                else:
                    st.error(str(account.get("detail", "Could not create the account.")).split(": ", 1)[-1])

    st.markdown('<div class="footer-note">Your data stays in your own private workspace.</div>',
                unsafe_allow_html=True)
