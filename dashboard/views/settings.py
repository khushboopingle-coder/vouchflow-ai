"""
VouchFlow AI — Settings (Phase 4)
Create and revoke API keys that let automation (n8n) send invoices to YOUR workspace.
A key is shown ONCE, when it is created; only its hash is stored.
"""

import sys
from pathlib import Path

import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import ui_common as ui  # noqa: E402

st.set_page_config(page_title="VouchFlow AI | Settings", page_icon="🧾", layout="wide")
ui.apply_global_css()  # shared theme (colours from ui_common.PALETTE)
ui.apply_page_style(
    "Settings",
    "API keys for automation. A key lets n8n send invoices to your workspace only - never anyone else's.",
)

from backend.config import settings  # noqa: E402
from backend.services import api_key_service  # noqa: E402

WS = ui.workspace_id()
ACCOUNT = ui.current_account()

# ---------------------------------------------------------------------
# A freshly created key is shown exactly once (then removed from the session)
# ---------------------------------------------------------------------
new_key = st.session_state.pop("new_api_key", None)
if new_key:
    st.success(f"Key '{new_key['name']}' created. Copy it now - it will not be shown again.")
    st.code(new_key["key"], language=None)
    st.caption("Store it in n8n as the X-API-Key header value. If you lose it, revoke it and create a new one.")

# ---------------------------------------------------------------------
st.subheader("Create an API key")
with st.form("create_key_form", clear_on_submit=True):
    name = st.text_input("Name", placeholder="e.g. n8n Gmail", key="api_key_name")
    created = st.form_submit_button("Create key", type="primary")
if created:
    def _create(db):
        try:
            record, raw = api_key_service.create_api_key(db, WS, ACCOUNT["user_id"], name, who=ACCOUNT["email"])
            return {"name": record.name, "key": raw}
        except api_key_service.APIKeyError as exc:
            return {"error": str(exc)}

    ok, result = ui.run_db(_create)
    if ok and "key" in result:
        st.session_state["new_api_key"] = result
        st.rerun()
    else:
        st.error(result.get("error") or result.get("detail"))

# ---------------------------------------------------------------------
st.subheader("Your keys")
ok, keys = ui.run_db(lambda db: [
    {"id": k.id, "name": k.name, "prefix": k.key_prefix, "created": k.created_at, "used": k.last_used_at,
     "revoked": k.revoked_at}
    for k in api_key_service.list_api_keys(db, WS)
])
keys = keys if ok else []
if not keys:
    st.info("No keys yet.")
for key in keys:
    c1, c2, c3, c4 = st.columns([3, 2, 3, 1])
    c1.markdown(f"**{key['name']}**  \n`{key['prefix']}…`")
    c2.markdown("Revoked" if key["revoked"] else "Active")
    used = str(key["used"])[:16].replace("T", " ") if key["used"] else "never"
    c3.caption(f"Created {str(key['created'])[:10]} · last used {used}")
    if not key["revoked"]:
        if c4.button("Revoke", key=f"revoke_{key['id']}"):
            done, _ = ui.run_db(lambda db, i=key["id"]: api_key_service.revoke_api_key(db, WS, i, who=ACCOUNT["email"]))
            st.rerun()

# ---------------------------------------------------------------------
st.subheader("How n8n uses a key")
base = "https://YOUR-API-ADDRESS"
st.markdown(
    "Send the invoice file to the API with the key in the `X-API-Key` header. "
    "The answer says whether the invoice is verified, what is wrong and where a person can approve it. "
    "**Nothing is ever approved or paid automatically.**"
)
st.code(
    f'curl -X POST "{base}/api/invoices/ingest" \\\n'
    '     -H "X-API-Key: <your key>" \\\n'
    '     -F "file=@invoice.pdf"',
    language="bash",
)
st.caption(
    f"Limit: {settings.INGEST_RATE_LIMIT_PER_MINUTE} requests per minute per key. "
    "Reading invoices needs a Gemini key on the API server; without one the invoice is still saved and "
    "checked, but marked 'needs review'."
)
