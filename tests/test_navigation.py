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
VIEWS = ["views/investigation.py", "views/approvals.py", "views/evals.py", "views/data.py"]


def _has_brand(at) -> bool:
    return any('class="brand-lockup"' in str(getattr(e, "value", "")) for e in at.sidebar)


def _has_banner(at) -> bool:
    return any('class="demo-banner"' in m.value for m in at.main.markdown)


@pytest.fixture(scope="module")
def api_user():
    """This module's OWN user (a fresh sample copy, so the "Demo data" banner shows). The shared
    session-wide api_user may already hold uploads from other tests and then counts as live."""
    from tests.helpers import temp_user

    with temp_user() as user:
        yield user


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


def test_banner_and_badge_follow_demo_vs_live():
    """Sample copy only -> "Demo data" + banner; after the user adds data -> "Live workspace", no banner."""
    from backend.database.db import SessionLocal
    from backend.services import upload_service
    from tests.helpers import temp_user

    badge = lambda at: " ".join(str(getattr(e, "value", "")) for e in at.sidebar)  # noqa: E731

    with temp_user() as user:
        at = AppTest.from_file(APP, default_timeout=180)
        at.session_state["auth"] = user.session_auth
        at.run()
        assert "Demo data" in badge(at) and _has_banner(at)

        db = SessionLocal()
        try:
            upload_service.save_invoice_file(db, user.workspace_id, "mine.pdf", b"%PDF-1.4 my own invoice")
        finally:
            db.close()
        at.run()
        assert "Live workspace" in badge(at) and "Demo data" not in badge(at)
        assert not _has_banner(at)

    with temp_user(load_sample=False) as empty:  # nothing loaded: also a live workspace
        at = AppTest.from_file(APP, default_timeout=180)
        at.session_state["auth"] = empty.session_auth
        at.run()
        assert "Live workspace" in badge(at) and not _has_banner(at)
