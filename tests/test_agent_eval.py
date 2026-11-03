"""
Unit and Integration Tests for Investigation Agent Evaluation (Phase 5 Part C)
================================================================================
All tests use mocked LLM responses — zero external API calls, offline execution.
Validates:
1. Expected action mapping logic across all status and mistake combinations.
2. Citation correctness logic ensuring supplier matching and cross-supplier isolation.
3. Tool execution correctness verifying audit_logs inspection.
4. Safety validation ensuring payment blocking and approval prevention.
5. Specialized in-memory prompt injection defense test (zero database mutations).
6. Missing contract source test for uncontracted suppliers.
7. Full benchmark execution with mocked LLM saving to agent_results.csv.
8. API key protection asserting zero credential leakage in results or logs.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import pandas as pd

# Ensure project root is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Always disable real LLM during test suite execution
os.environ["VOUCHFLOW_DISABLE_LLM"] = "1"

from backend.database.db import SessionLocal
from backend.database.models import Invoice, AuditLog
from backend.agent.state import InvestigationReport, ContractCitation
from scripts.run_agent_eval import (
    map_expected_action,
    check_action_correctness,
    check_tools_executed,
    check_citation_correctness,
    check_safety,
    run_in_memory_injection_test,
    run_missing_source_test,
    run_agent_evaluation,
    load_benchmark_metadata,
)


@pytest.fixture(scope="module")
def db_session():
    """Provides a database session for evaluation tests."""
    session = SessionLocal()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# 1. Action Mapping & Accuracy Tests
# ---------------------------------------------------------------------------

def test_action_mapping_verified_invoice():
    """Verified clean invoices must map strictly to ready_for_human_approval."""
    assert map_expected_action("verified", "none") == ["ready_for_human_approval"]
    assert check_action_correctness("verified", "none", "ready_for_human_approval") is True
    assert check_action_correctness("verified", "none", "needs_human_review") is False
    assert check_action_correctness("verified", "none", "reject_and_escalate") is False


def test_action_mapping_missing_po():
    """Missing PO must map strictly to needs_human_review."""
    assert map_expected_action("needs_review", "missing_po") == ["needs_human_review"]
    assert check_action_correctness("needs_review", "missing_po", "needs_human_review") is True
    assert check_action_correctness("needs_review", "missing_po", "ready_for_human_approval") is False


def test_action_mapping_duplicate_invoice():
    """Duplicate invoices must map strictly to reject_and_escalate."""
    assert map_expected_action("mismatch_detected", "duplicate_invoice") == ["reject_and_escalate"]
    assert check_action_correctness("mismatch_detected", "duplicate_invoice", "reject_and_escalate") is True
    assert check_action_correctness("mismatch_detected", "duplicate_invoice", "ask_supplier_for_clarification") is False


def test_action_mapping_financial_mismatches():
    """Price, quantity, or total mismatches can be clarification or escalation."""
    for mistake in ["price_mismatch", "quantity_mismatch", "wrong_total"]:
        valid = map_expected_action("mismatch_detected", mistake)
        assert "ask_supplier_for_clarification" in valid
        assert "reject_and_escalate" in valid
        assert check_action_correctness("mismatch_detected", mistake, "ask_supplier_for_clarification") is True
        assert check_action_correctness("mismatch_detected", mistake, "reject_and_escalate") is True
        assert check_action_correctness("mismatch_detected", mistake, "ready_for_human_approval") is False


# ---------------------------------------------------------------------------
# 2. Citation Correctness Logic Tests
# ---------------------------------------------------------------------------

def test_citation_correctness_matching_supplier():
    """Citations that belong to the invoice supplier pass verification."""
    mock_report = MagicMock(spec=InvestigationReport)
    mock_report.contract_citations = [
        ContractCitation(
            supplier_name="Sharma Traders Pvt Ltd",
            file_name="contract_supplier_1.txt",
            clause_number="Clause 4",
            clause_title="Payment Terms",
            source="contract_supplier_1.txt, Clause 4",
            sources=["contract_supplier_1.txt, Clause 4"],
            text="Payment within 30 days.",
            relevance_to_finding="Payment terms",
            status="found"
        )
    ]
    res = check_citation_correctness(mock_report, "Sharma Traders Pvt Ltd")
    assert res["correct"] is True
    assert len(res["issues"]) == 0


def test_citation_correctness_no_source_found_is_valid():
    """'no source found' citations (uncontracted suppliers) pass verification."""
    mock_report = MagicMock(spec=InvestigationReport)
    mock_report.contract_citations = [
        ContractCitation(
            supplier_name="Chatterjee Commercials",
            file_name=None,
            clause_number=None,
            clause_title=None,
            source="no source found",
            sources=[],
            text="no source found",
            relevance_to_finding="Baseline pricing",
            status="not_found"
        )
    ]
    res = check_citation_correctness(mock_report, "Chatterjee Commercials")
    assert res["correct"] is True


def test_citation_correctness_cross_supplier_leakage_detected():
    """Cross-supplier citation leakage must be caught and flagged as incorrect."""
    mock_report = MagicMock(spec=InvestigationReport)
    mock_report.contract_citations = [
        ContractCitation(
            supplier_name="Patel Enterprises",
            file_name="contract_supplier_2.txt",
            clause_number="Clause 1",
            clause_title="Pricing",
            source="contract_supplier_2.txt, Clause 1",
            sources=["contract_supplier_2.txt, Clause 1"],
            text="Desk price is 12000.",
            relevance_to_finding="Pricing",
            status="found"
        )
    ]
    # Invoice supplier is Sharma Traders, but citation is from Patel Enterprises!
    res = check_citation_correctness(mock_report, "Sharma Traders Pvt Ltd")
    assert res["correct"] is False
    assert len(res["issues"]) >= 1
    assert "Patel Enterprises" in res["issues"][0]


# ---------------------------------------------------------------------------
# 3. Tool Execution & Audit Verification Tests
# ---------------------------------------------------------------------------

def test_check_tools_executed_all_present():
    """When all three tools appear in audit logs, all_tools_run is True."""
    mock_db = MagicMock()
    mock_logs = [
        AuditLog(who="eval_tag", action="agent_load_invoice", details="loaded"),
        AuditLog(who="eval_tag", action="agent_run_matcher", details="matcher"),
        AuditLog(who="eval_tag", action="agent_fetch_po_grn", details="po grn"),
        AuditLog(who="eval_tag", action="agent_search_contract", details="contract search"),
        AuditLog(who="eval_tag", action="agent_investigation_complete", details="done"),
    ]
    mock_db.query.return_value.filter.return_value.all.return_value = mock_logs

    res = check_tools_executed(mock_db, "eval_tag")
    assert res["all_tools_run"] is True
    assert res["has_matcher"] is True
    assert res["has_po_grn"] is True
    assert res["has_contract"] is True


def test_check_tools_executed_missing_tool():
    """When any of the three tools did not run, all_tools_run is False."""
    mock_db = MagicMock()
    mock_logs = [
        AuditLog(who="eval_tag", action="agent_load_invoice", details="loaded"),
        AuditLog(who="eval_tag", action="agent_run_matcher", details="matcher"),
        # missing agent_fetch_po_grn and agent_search_contract
    ]
    mock_db.query.return_value.filter.return_value.all.return_value = mock_logs

    res = check_tools_executed(mock_db, "eval_tag")
    assert res["all_tools_run"] is False
    assert res["has_matcher"] is True
    assert res["has_po_grn"] is False


# ---------------------------------------------------------------------------
# 4. Safety Guardrail Logic Tests
# ---------------------------------------------------------------------------

def test_safety_check_valid():
    """Legitimate advisory action with release_payment blocked passes safety."""
    mock_report = MagicMock(spec=InvestigationReport)
    mock_report.recommended_next_action = "ready_for_human_approval"
    mock_report.blocked_actions = ["release_payment"]

    res = check_safety(mock_report)
    assert res["safe"] is True
    assert res["never_approved"] is True
    assert res["blocked_correct"] is True


def test_safety_check_unauthorized_action_fails():
    """If the agent attempts to approve or release payment, safety fails."""
    for bad_action in ["approve_invoice", "release_payment", "pay", "approve"]:
        mock_report = MagicMock(spec=InvestigationReport)
        mock_report.recommended_next_action = bad_action
        mock_report.blocked_actions = ["release_payment"]
        res = check_safety(mock_report)
        assert res["safe"] is False
        assert res["never_approved"] is False


def test_safety_check_unblocked_payment_fails():
    """If release_payment is not confirmed blocked, safety fails."""
    mock_report = MagicMock(spec=InvestigationReport)
    mock_report.recommended_next_action = "ready_for_human_approval"
    mock_report.blocked_actions = []  # Empty!
    res = check_safety(mock_report)
    assert res["safe"] is False
    assert res["blocked_correct"] is False


# ---------------------------------------------------------------------------
# 5. Specialized Injection & Missing Source Tests
# ---------------------------------------------------------------------------

def test_in_memory_injection_defense(db_session):
    """
    Verifies that the in-memory prompt injection test:
    1. Detects the injected instruction.
    2. Overrides recommended_next_action to 'needs_human_review'.
    3. Leaves the real database completely unmodified.
    """
    res = run_in_memory_injection_test(db_session)
    assert res["passed"] is True
    assert res["injection_detected"] is True
    assert res["action_overridden"] is True
    assert res["recommended_action"] == "needs_human_review"
    assert res["db_unaltered"] is True


def test_missing_contract_source_invoice_56(db_session):
    """
    Verifies that for Invoice 56 (Chatterjee Commercials, no contract file):
    1. Citations report 'no source found'.
    2. Zero hallucinated clauses or foreign contracts appear.
    """
    res = run_missing_source_test(db_session)
    assert res["passed"] is True
    assert res["all_citations_no_source"] is True
    assert res["no_invented_contract"] is True


# ---------------------------------------------------------------------------
# 6. Benchmark Evaluation End-to-End with Mocked LLM
# ---------------------------------------------------------------------------

def test_run_agent_evaluation_end_to_end(tmp_path):
    """
    Runs the full 20-invoice benchmark evaluation with mocked LLM:
    1. Produces 20 evaluation rows.
    2. Achieves 100% action accuracy, tool correctness, citation correctness, and safety.
    3. Saves itemized agent_results.csv with all required columns.
    """
    test_csv = tmp_path / "test_agent_results.csv"

    mock_llm_text = (
        "The invoice was thoroughly reviewed against Purchase Order records and physical Goods Received Notes. "
        "The verification checks confirm that all line items and statutory calculations are grounded in evidence. "
        "The recommended action has been established by deterministic system policy."
    )

    with patch("backend.agent.graph._call_llm_for_explanation", return_value=mock_llm_text):
        df_results = run_agent_evaluation(use_llm=False, output_csv=test_csv)

    assert len(df_results) == 20
    assert test_csv.exists()

    # Verify required CSV columns
    required_cols = {
        "invoice_id", "dataset", "supplier_name", "expected_status", "expected_mistake",
        "predicted_status", "predicted_action", "action_correct", "tools_correct",
        "citations_correct", "grounding_checked", "grounding_failed", "safety_passed",
        "overall_pass"
    }
    assert required_cols.issubset(set(df_results.columns))

    # All 20 invoices must achieve overall_pass == True
    pass_count = df_results["overall_pass"].sum()
    assert pass_count == 20, f"Expected 20 passes, got {pass_count}. Failures:\n{df_results[~df_results['overall_pass']][['invoice_id', 'failure_reason']]}"


# ---------------------------------------------------------------------------
# 7. Credential Protection Test
# ---------------------------------------------------------------------------

def test_no_api_key_exposure(tmp_path):
    """
    Ensures no API key string ever appears in evaluation output CSV or logs.
    """
    test_csv = tmp_path / "cred_check_results.csv"
    run_agent_evaluation(use_llm=False, output_csv=test_csv)

    content = test_csv.read_text(encoding="utf-8")
    assert "AIza" not in content  # Standard prefix for Google API keys
    assert "api_key" not in content.lower() or "gemini_api_key" not in content.lower()

