"""
Demo start-up for VouchFlow AI (Streamlit Community Cloud).

Makes the dashboard work with NO FastAPI server, NO .env file and NO Gemini key:

1. If a Gemini key is stored in Streamlit secrets, hand it to the backend
   (through an environment variable). The key is never printed or shown.
2. If the database is missing or empty, fill it from data/evaluation/mock_data.json
   (invoices 1-50: 35 clean, 15 with planted mistakes).
3. Run a few demo invoices through the checker and the Investigation Agent
   so the Investigation and Approvals pages show real results.
   Extraction (Gemini) only runs when a key exists; without a key the checker
   uses the database line items instead.

SAFETY: this file never runs the data generator scripts, because they rewrite
the ground truth CSVs. Ground truth files are only READ here.

Run by hand (optional):  python -m dashboard.demo_setup
"""

import contextlib
import io
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

MOCK_DATA_PATH = BASE_DIR / "data" / "evaluation" / "mock_data.json"
GROUND_TRUTH_PATH = BASE_DIR / "data" / "evaluation" / "ground_truth.csv"
SECRET_KEYS = ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_MODEL_LIST")
# Used only if ground_truth.csv cannot be read: 1 clean + one of each mistake type
FALLBACK_DEMO_IDS = [1, 19, 15, 21, 6, 24]
DEMO_WHO = "demo_setup"

DEMO_NOTE_HTML = (
    "<b>Demo mode: all data is fake.</b> Suppliers, invoices and contracts are generated "
    "test data. The AI only advises — a person always approves."
)


# ---------------------------------------------------------------------
# Step 1: secrets -> environment (must run before any backend import)
# ---------------------------------------------------------------------
def load_secrets_into_env() -> None:
    """Copies Gemini settings from Streamlit secrets into env vars, if present.
    An existing env var or .env value is never overwritten. Nothing is printed."""
    try:
        secrets = st.secrets
        for key in SECRET_KEYS:
            if key in secrets and not os.environ.get(key):
                os.environ[key] = str(secrets[key])
    except Exception:
        # No secrets file (normal on a laptop) -> nothing to do
        pass


# ---------------------------------------------------------------------
# Step 2 and 3: database + demo runs (plain Python, testable)
# ---------------------------------------------------------------------
def pick_demo_invoice_ids() -> List[int]:
    """One clean invoice plus the first invoice of each planted mistake type.
    Reads ground_truth.csv (read-only)."""
    try:
        import pandas as pd

        gt = pd.read_csv(GROUND_TRUTH_PATH)
        firsts = gt.sort_values("invoice_id").groupby("mistake_type")["invoice_id"].first()
        order = ["none", "price_mismatch", "quantity_mismatch", "wrong_total", "duplicate_invoice", "missing_po"]
        ids = [int(firsts[m]) for m in order if m in firsts.index]
        return ids or list(FALLBACK_DEMO_IDS)
    except Exception:
        return list(FALLBACK_DEMO_IDS)


def _invoice_count() -> int:
    from backend.database.db import SessionLocal, init_db
    from backend.database.models import Invoice

    init_db()
    db = SessionLocal()
    try:
        return db.query(Invoice).count()
    finally:
        db.close()


def prepare_demo_data(log: Callable[[str], None] = print) -> Dict:
    """Seeds an empty database and runs the demo invoices. Safe to call many times:
    if the database already has invoices, it does nothing."""
    from backend.config import settings

    result = {
        "seeded": False,
        "demo_invoice_ids": [],
        "extraction_used": bool(settings.GEMINI_API_KEY),
        "errors": [],
    }

    if _invoice_count() > 0:
        return result

    if not MOCK_DATA_PATH.exists():
        # Never fall back to the generators: they would rewrite ground truth files.
        raise RuntimeError(
            f"{MOCK_DATA_PATH.name} is missing, so demo data cannot be loaded. "
            "Make sure data/evaluation/mock_data.json is committed to the repository."
        )

    log("Demo setup: filling the empty database from mock_data.json ...")
    from scripts.seed_db import seed_database

    with contextlib.redirect_stdout(io.StringIO()):  # keep the logs short
        seed_database()
    result["seeded"] = True

    from backend.database.db import SessionLocal
    from backend.services import invoice_service

    ids = pick_demo_invoice_ids()
    result["demo_invoice_ids"] = ids
    db = SessionLocal()
    try:
        for invoice_id in ids:
            try:
                if result["extraction_used"]:
                    invoice_service.extract_invoice_data(db=db, invoice_id=invoice_id, who=DEMO_WHO)
                invoice_service.check_invoice_matching(db=db, invoice_id=invoice_id, who=DEMO_WHO)
                invoice_service.investigate_invoice(db=db, invoice_id=invoice_id, who=DEMO_WHO)
                log(f"Demo setup: invoice {invoice_id} checked and investigated.")
            except Exception as exc:  # one bad invoice must not stop the demo
                db.rollback()
                result["errors"].append(f"invoice {invoice_id}: {type(exc).__name__}")
                log(f"Demo setup: invoice {invoice_id} failed ({type(exc).__name__}).")
    finally:
        db.close()
    return result


# ---------------------------------------------------------------------
# Streamlit entry points
# ---------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _prepare_once() -> Dict:
    return prepare_demo_data()


def ensure_demo_ready() -> Dict:
    """Call at the top of every dashboard page (before any backend import).
    Runs the start-up only once per server process."""
    load_secrets_into_env()
    with st.spinner("Setting up demo data (first start only, about 1–2 minutes)..."):
        try:
            return _prepare_once()
        except Exception as exc:
            st.error(f"Demo setup failed: {exc}")
            st.stop()


if __name__ == "__main__":
    load_secrets_into_env()
    print(prepare_demo_data())
