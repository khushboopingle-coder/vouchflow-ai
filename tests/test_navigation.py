"""
Router tests: every page opened through dashboard/app.py keeps the shared
sidebar (brand + menu) and the demo banner, also after a widget change.

Regression: pages used to live in dashboard/pages/, which Streamlit treats as its
old auto-multipage folder -> the router's sidebar and banner disappeared there.
"""

import html
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")
VIEWS = ["views/investigation.py", "views/approvals.py", "views/evals.py"]


def _has_brand(at) -> bool:
    return any('class="brand-lockup"' in str(getattr(e, "value", "")) for e in at.sidebar)


def _has_banner(at) -> bool:
    return any('class="demo-banner"' in m.value for m in at.main.markdown)


@pytest.fixture(scope="module")
def app(api_user):
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["auth"] = api_user.session_auth  # logged in as the test user
    at.run()
    return at


def test_home_has_sidebar_and_banner(app):
    assert not app.exception
    assert _has_brand(app) and _has_banner(app)


@pytest.mark.parametrize("view", VIEWS)
def test_every_page_keeps_sidebar_and_banner(app, view):
    app.switch_page(view).run()
    assert not app.exception, [e.value for e in app.exception]
    assert _has_brand(app), f"sidebar brand missing on {view}"
    assert _has_banner(app), f"demo banner missing on {view}"


def test_sidebar_survives_widget_change(app, api_user):
    app.switch_page("views/investigation.py").run()
    app.selectbox(key="investigation_invoice").set_value(api_user.ids[1]).run()  # user's invoice 1
    assert _has_brand(app) and _has_banner(app)


def test_sidebar_shows_account_and_workspace(app, api_user):
    app.switch_page("home.py").run()
    sidebar_html = " ".join(str(getattr(e, "value", "")) for e in app.sidebar)
    assert api_user.email in sidebar_html
    assert html.escape(api_user.account.workspace_name) in sidebar_html
    assert any(b.label == "Log out" for b in app.sidebar.button)


@pytest.mark.parametrize("view", ["home.py", *VIEWS])
def test_logged_out_visitor_only_sees_login(view):
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    if view != "home.py":
        at.switch_page(view).run()
    assert not at.exception
    assert not _has_brand(at) and not _has_banner(at)  # no workspace content at all
    assert [t.label for t in at.tabs] == ["Log in", "Create account"]
