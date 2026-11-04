"""
Demo start-up tests (Streamlit Community Cloud mode).

The start-up runs in a separate Python process on a TEMPORARY database, with
no Gemini key, so the real vouchflow.db is never touched. Checks:
- an empty database is filled from mock_data.json (50 invoices)
- 6 demo invoices are checked and investigated, without extraction (no key)
- the agent writes the template explanation (LLM not used)
- running it again does nothing
- ground truth files and mock_data.json are not changed
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BASE_DIR / "data" / "evaluation"
PROTECTED = sorted(EVAL_DIR.glob("*ground_truth*.csv")) + [EVAL_DIR / "mock_data.json"]

RUN_SNIPPET = (
    "import json; from dashboard.demo_setup import prepare_demo_data; "
    "print('RESULT=' + json.dumps(prepare_demo_data(log=lambda m: None)))"
)


def _hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED}


def _run_setup(db_path: Path) -> dict:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["GEMINI_API_KEY"] = ""  # simulate Streamlit Cloud with no key (overrides .env)
    env["VOUCHFLOW_DISABLE_LLM"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", RUN_SNIPPET],
        cwd=str(BASE_DIR), env=env, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    line = next(l for l in proc.stdout.splitlines() if l.startswith("RESULT="))
    return json.loads(line[len("RESULT="):])


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("demo") / "demo.db"
    before = _hashes()
    first = _run_setup(db_path)
    second = _run_setup(db_path)
    return {"db": db_path, "first": first, "second": second, "before": before, "after": _hashes()}


def test_pick_demo_invoices_covers_every_mistake_type():
    sys.path.insert(0, str(BASE_DIR))
    from dashboard.demo_setup import pick_demo_invoice_ids

    assert pick_demo_invoice_ids() == [1, 19, 15, 21, 6, 24]


def test_first_start_seeds_and_runs_demo_invoices(demo_run):
    first = demo_run["first"]
    assert first["seeded"] is True
    assert first["extraction_used"] is False
    assert first["demo_invoice_ids"] == [1, 19, 15, 21, 6, 24]
    assert first["errors"] == []


def test_database_contents(demo_run):
    con = sqlite3.connect(demo_run["db"])
    try:
        count = lambda table: con.execute(f"select count(*) from {table}").fetchone()[0]
        assert count("invoices") == 50
        assert count("invoice_checks") == 6
        assert count("invoice_investigations") == 6
        assert count("invoice_extractions") == 0  # no key -> no extraction
        assert count("invoice_decisions") == 0  # nothing is ever auto-approved
        reports = [json.loads(r[0]) for r in con.execute("select report_json from invoice_investigations")]
    finally:
        con.close()
    assert all(r["llm_used"] is False for r in reports)
    by_id = {r["invoice_id"]: r for r in reports}
    assert by_id[1]["status"] == "verified"
    assert by_id[19]["status"] == "mismatch_detected"


def test_second_start_does_nothing(demo_run):
    assert demo_run["second"]["seeded"] is False
    assert demo_run["second"]["demo_invoice_ids"] == []


def test_ground_truth_files_unchanged(demo_run):
    assert demo_run["before"] == demo_run["after"]
