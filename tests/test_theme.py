"""
Theme tests: every dashboard colour lives in ui_common.PALETTE.

- .streamlit/config.toml uses the same colours as PALETTE
- the global CSS builds with no unfilled placeholders
- no other dashboard file hard-codes a colour
- app.py, home.py and every page call ui.apply_global_css() exactly once
"""

import re
import sys
import tomllib
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
DASHBOARD = BASE_DIR / "dashboard"
sys.path.insert(0, str(DASHBOARD))

import ui_common  # noqa: E402

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
PAGE_FILES = [DASHBOARD / "app.py", DASHBOARD / "home.py", *sorted((DASHBOARD / "pages").glob("*.py"))]


def test_config_toml_matches_palette():
    cfg = tomllib.loads((BASE_DIR / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    theme, P = cfg["theme"], ui_common.PALETTE
    assert theme["base"] == "light"
    expected = {
        "primaryColor": P["primary"],
        "backgroundColor": P["bg"],
        "secondaryBackgroundColor": P["sidebar"],
        "textColor": P["text"],
        "linkColor": P["accent"],
        "borderColor": P["card_border"],
        "dataframeBorderColor": P["chrome_light"],
        "dataframeHeaderBackgroundColor": P["chrome_light"],
    }
    for key, value in expected.items():
        assert theme[key].upper() == value.upper(), key
    assert theme["sidebar"]["backgroundColor"].upper() == P["sidebar"].upper()
    assert theme["sidebar"]["secondaryBackgroundColor"].upper() == P["card"].upper()


def test_global_css_builds_completely():
    css = ui_common.build_global_css()
    assert "$" not in css  # every $placeholder was filled
    for key in ("primary", "accent", "bg", "sidebar", "card", "chrome_light", "chrome_dark"):
        assert ui_common.PALETTE[key] in css
    for status in ui_common.STATUS_KEYS:
        assert f".vf-pill.vf-{status}" in css


@pytest.mark.parametrize("path", PAGE_FILES + [DASHBOARD / "demo_setup.py"], ids=lambda p: p.name)
def test_no_hard_coded_colours_outside_palette(path):
    assert HEX.findall(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", PAGE_FILES, ids=lambda p: p.name)
def test_every_page_applies_global_css_once(path):
    assert path.read_text(encoding="utf-8").count("apply_global_css()") == 1


def test_status_pill_escapes_and_classifies():
    assert 'vf-pill vf-mismatch_detected' in ui_common.status_pill("mismatch_detected")
    assert 'vf-other' in ui_common.status_pill("<b>odd</b>")
    assert "<b>" not in ui_common.status_pill("<b>odd</b>")
