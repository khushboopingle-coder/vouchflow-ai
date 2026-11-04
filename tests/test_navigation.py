"""
Router tests: every page opened through dashboard/app.py keeps the shared
sidebar (brand + menu) and the demo banner, also after a widget change.

Regression: pages used to live in dashboard/pages/, which Streamlit treats as its
old auto-multipage folder -> the router's sidebar and banner disappeared there.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")
VIEWS = ["views/investigation.py", "views/approvals.py", "views/evals.py"]


def _has_brand(at) -> bool:
    return any("brand-lockup" in str(getattr(e, "value", "")) for e in at.sidebar)


def _has_banner(at) -> bool:
    return any("demo-banner" in m.value for m in at.main.markdown)


@pytest.fixture(scope="module")
def app():
    at = AppTest.from_file(APP, default_timeout=180)
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


def test_sidebar_survives_widget_change(app):
    app.switch_page("views/investigation.py").run()
    app.selectbox(key="investigation_invoice").set_value(1).run()  # invoice ID 1
    assert _has_brand(app) and _has_banner(app)
