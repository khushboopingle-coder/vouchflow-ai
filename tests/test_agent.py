"""
Unit Tests for Investigation Agent (Phase 5, Part A)
=====================================================
Tests:
1. Read-only tools (get_invoice, get_extraction, run_matcher, get_po_and_grn, search_contract)
   - Ensure tools return correct structures
   - Verify tools do NOT alter database records or invoice status
2. LangGraph investigation workflow
   - Test verified invoice (Invoice 1): status='verified', action='ready_for_human_approval'
   - Test mismatch invoice (Invoice 6): status='mismatch_detected'
   - Validate report schema: invoice_id, status, findings (with evidence), contract_citations,
     explanation, recommended_next_action, confidence, limitations
   - Verify audit log entry generated for each workflow step
3. API service functions (investigate_invoice, get_invoice_investigation)
   - Storing into invoice_investigations table
   - Retrieval and 404 error handling
"""

import json
import pytest
from datetime import datetime
from fastapi import HTTPException

from backend.database.db import SessionLocal
from backend.database.models import (
    Invoice,
    AuditLog,
    InvoiceInvestigation,
    InvoiceCheck
)
from backend.agent.state import InvestigationReport, AgentFinding, ContractCitation
from backend.agent.tools import (
    get_invoice,
    get_extraction,
    run_matcher,
    get_po_and_grn,
    search_contract
)
from backend.agent.graph import run_investigation
from backend.services.invoice_service import (
    investigate_invoice as service_investigate_invoice,
    get_invoice_investigation as service_get_invoice_investigation
)


@pytest.fixture(scope="module")
def db_session():
    """Provides a database session for test execution."""
    session = SessionLocal()
    yield session
    session.close()


# =============================================================================
# 1. Tests for Read-Only Tools
# =============================================================================
def test_tool_get_invoice_read_only(db_session):
    """Verifies get_invoice returns structured invoice data without modifying status."""
    inv_before = db_session.query(Invoice).filter(Invoice.id == 1).first()
    status_before = inv_before.status

    data = get_invoice(1, db_session)
    assert data["found"] is True
    assert data["id"] == 1
    assert data["invoice_number"] == "INV-2026-0001"
    assert "items" in data
    assert len(data["items"]) > 0
    assert data["supplier_name"] != ""

    # Verify no database mutation
    db_session.expire_all()
    inv_after = db_session.query(Invoice).filter(Invoice.id == 1).first()
    assert inv_after.status == status_before


def test_tool_get_extraction(db_session):
    """Verifies get_extraction returns stored extraction details or graceful fallback."""
    data = get_extraction(1, db_session)
    assert "found" in data
    if data["found"]:
        assert data["invoice_id"] == 1
        assert "confidence" in data
        assert "extracted" in data


def test_tool_run_matcher_read_only(db_session):
    """Verifies run_matcher executes in-memory without saving to invoice_checks table."""
    check_count_before = db_session.query(InvoiceCheck).count()

    res = run_matcher(1, db_session)
    assert "status" in res
    assert "mistake_types" in res
    assert "findings" in res
    assert "difference_amount" in res
    assert res["status"] in ("verified", "mismatch_detected", "needs_review")

    # Verify no invoice_checks row was inserted
    check_count_after = db_session.query(InvoiceCheck).count()
    assert check_count_after == check_count_before


def test_tool_get_po_and_grn(db_session):
    """Verifies get_po_and_grn returns purchase order limits and physical GRN receipts."""
    po_grn = get_po_and_grn(1, db_session)
    assert po_grn["has_po"] is True
    assert po_grn["po"] is not None
    assert "po_number" in po_grn["po"]
    assert "items" in po_grn["po"]
    assert isinstance(po_grn["grn_list"], list)


def test_tool_search_contract():
    """Verifies search_contract retrieves relevant contract clauses via RAG."""
    res = search_contract(query="agreed unit price for Cat6 Ethernet Cable", supplier_name="Sharma Traders")
    assert "answer" in res
    assert "status" in res
    assert res["status"] in ("found", "not_found", "conflict")
    if res["status"] == "found":
        assert res["source"] is not None


# =============================================================================
# 2. Tests for LangGraph Workflow
# =============================================================================
def test_investigation_graph_verified_invoice(db_session):
    """
    Verifies that running the workflow on a clean invoice produces:
    - status: 'verified'
    - recommended_next_action: 'ready_for_human_approval'
    - contract citations
    - evidence with values_compared and sources for each finding
    - deterministic template explanation
    - limitations list
    """
    report = run_investigation(1, db_session, who="test_runner")
    assert isinstance(report, InvestigationReport)
    assert report.invoice_id == 1
    assert report.status == "verified"
    assert report.recommended_next_action == "ready_for_human_approval"
    assert report.confidence >= 0.7
    assert len(report.limitations) >= 2
    assert len(report.contract_citations) > 0
    assert "Investigation Report for Invoice" in report.explanation

    # Check evidence structure on findings
    for finding in report.findings:
        assert isinstance(finding, AgentFinding)
        assert finding.check_name != ""
        assert "values_compared" in finding.evidence
        assert "sources" in finding.evidence


def test_investigation_graph_mismatch_invoice(db_session):
    """
    Verifies that running the workflow on an invoice with discrepancies (Invoice 6)
    correctly flags status mismatch_detected and advises clarification or escalation.
    """
    report = run_investigation(6, db_session, who="test_runner")
    assert isinstance(report, InvestigationReport)
    assert report.invoice_id == 6
    assert report.status == "mismatch_detected"
    assert report.recommended_next_action in ("ask_supplier_for_clarification", "reject_and_escalate")
    assert len(report.findings) > 0


def test_investigation_audit_logs_per_step(db_session):
    """
    Verifies that every single step of the LangGraph workflow writes an audit log.
    Expected actions:
    - agent_load_invoice
    - agent_run_matcher
    - agent_fetch_po_grn
    - agent_search_contract
    - agent_build_evidence
    - agent_write_explanation
    - agent_investigation_complete
    """
    who_tag = f"audit_test_{int(datetime.utcnow().timestamp())}"
    run_investigation(1, db_session, who=who_tag)

    logs = db_session.query(AuditLog).filter(AuditLog.who == who_tag).all()
    actions = {log.action for log in logs}

    expected_actions = {
        "agent_load_invoice",
        "agent_run_matcher",
        "agent_fetch_po_grn",
        "agent_search_contract",
        "agent_build_evidence",
        "agent_write_explanation",
        "agent_investigation_complete"
    }

    for action in expected_actions:
        assert action in actions, f"Missing audit log action: {action}"

    # Clean up test audit logs
    for l in logs:
        db_session.delete(l)
    db_session.commit()


# =============================================================================
# 3. Tests for API Service Endpoints
# =============================================================================
def test_service_investigate_and_get(db_session):
    """
    Verifies service functions:
    1. investigate_invoice persists to invoice_investigations table
    2. get_invoice_investigation retrieves the saved report
    3. Non-existent invoice raises 404
    """
    # 1. Investigate invoice 1
    report = service_investigate_invoice(db_session, invoice_id=1, who="api_tester")
    assert report.invoice_id == 1
    assert report.status == "verified"

    # 2. Retrieve saved report
    retrieved = service_get_invoice_investigation(db_session, invoice_id=1)
    assert retrieved.invoice_id == 1
    assert retrieved.status == report.status
    assert retrieved.recommended_next_action == report.recommended_next_action
    assert len(retrieved.findings) == len(report.findings)

    # 3. Non-existent invoice ID raises HTTPException 404
    with pytest.raises(HTTPException) as exc_info:
        service_get_invoice_investigation(db_session, invoice_id=999999)
    assert exc_info.value.status_code == 404


# =============================================================================
# 4. Tests for Scope & Evidence Sanitization (Invoice 56 Fixes)
# =============================================================================
def test_invoice_56_citations_belong_to_chatterjee_commercials(db_session):
    """
    Verifies that for invoice 56 (Chatterjee Commercials):
    1. Every contract citation belongs to Chatterjee Commercials
    2. No foreign supplier contracts are cited
    3. Shows 'no source found' when no contract is on file
    """
    report = run_investigation(56, db_session, who="test_runner")
    assert report.invoice_id == 56
    assert len(report.contract_citations) > 0
    for cit in report.contract_citations:
        assert cit.supplier_name == "Chatterjee Commercials"
        assert cit.source == "no source found"
        assert cit.text == "no source found"
        assert cit.status == "not_found"
        # Ensure zero leakage from other supplier contract files
        assert "Singh & Sons" not in cit.text
        assert "Reddy Logistics" not in cit.text
        assert "Verma Tech" not in cit.text
        assert "contract_supplier" not in str(cit.source)


def test_supplier_with_no_matching_clause_gives_no_source_found():
    """
    Verifies that querying a supplier with no matching contract
    returns 'no source found' rather than cross-supplier leakage.
    """
    res = search_contract(query="agreed unit price for A4 Copier Paper", supplier_name="Chatterjee Commercials")
    assert res["status"] == "not_found"
    assert res["source"] == "no source found"
    assert res["answer"] == "no source found"


def test_no_evidence_value_is_none(db_session):
    """
    Verifies that in evidence lists, no compared value is None.
    Specifically checks that the TOTALS check shows real numbers for
    invoiced_subtotal, calculated_subtotal, invoiced_grand_total, and expected_grand_total.
    """
    for inv_id in (1, 56):
        report = run_investigation(inv_id, db_session, who="test_runner")
        for finding in report.findings:
            vals = finding.evidence.get("values_compared", {})
            for k, v in vals.items():
                assert v is not None, f"Found None for key '{k}' in check '{finding.check_name}' on invoice {inv_id}"

            if finding.check_name == "totals":
                assert isinstance(vals.get("invoiced_subtotal"), (int, float))
                assert isinstance(vals.get("calculated_subtotal"), (int, float))
                assert isinstance(vals.get("invoiced_grand_total"), (int, float))
                assert isinstance(vals.get("expected_grand_total"), (int, float))


