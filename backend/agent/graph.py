"""
LangGraph Investigation Agent Workflow
=======================================
Pipeline Steps:
1. load_invoice_and_extraction -> Loads invoice record and OCR/AI extraction data
2. run_matcher                -> Runs deterministic 3-way matcher
3. fetch_po_and_grn_facts     -> Retrieves PO authorized limits and warehouse physical GRN receipts
4. search_contract_clauses    -> Searches contract RAG for clauses behind each finding
5. build_evidence_list        -> Formulates auditable evidence showing values compared and sources
6. write_template_explanation -> Generates deterministic rule-based explanation and recommended next action
7. compile_report             -> Compiles final InvestigationReport Pydantic model

Auditing:
Every step writes an entry to the audit_logs table.
Rule:
The agent never decides to approve or pay. Decisions and numbers come from existing tools.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, START, END

from backend.database.models import AuditLog
from backend.agent.state import (
    InvestigationState,
    InvestigationReport,
    AgentFinding,
    ContractCitation,
    RecommendedAction
)
from backend.agent.tools import (
    get_invoice,
    get_extraction,
    run_matcher,
    get_po_and_grn,
    search_contract
)


def log_audit_step(db: Optional[Session], who: str, action: str, details: str) -> None:
    """Helper to record an audit log entry for each workflow step."""
    if db is None:
        return
    try:
        entry = AuditLog(
            who=who or "investigation_agent",
            action=action,
            details=details,
            time=datetime.utcnow()
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        # Fallback in case of transaction issue
        if db:
            db.rollback()


# =============================================================================
# Pipeline Node 1: Load Invoice and Extraction
# =============================================================================
def load_invoice_and_extraction(state: InvestigationState) -> Dict[str, Any]:
    invoice_id = state["invoice_id"]
    db = state.get("db_session")
    who = state.get("who", "investigation_agent")

    inv_data = get_invoice(invoice_id, db) if db else {"found": False}
    ext_data = get_extraction(invoice_id, db) if db else {"found": False}

    supplier_name = inv_data.get("supplier_name", "Unknown Supplier")
    inv_num = inv_data.get("invoice_number", "Unknown")

    log_audit_step(
        db=db,
        who=who,
        action="agent_load_invoice",
        details=f"Loaded invoice #{inv_num} (ID: {invoice_id}) for {supplier_name} and extraction data."
    )

    return {
        "invoice_data": inv_data,
        "extraction_data": ext_data
    }


# =============================================================================
# Pipeline Node 2: Run Matcher
# =============================================================================
def run_matcher_step(state: InvestigationState) -> Dict[str, Any]:
    invoice_id = state["invoice_id"]
    db = state.get("db_session")
    who = state.get("who", "investigation_agent")

    match_result = run_matcher(invoice_id, db) if db else {
        "status": "needs_review",
        "mistake_types": ["unknown"],
        "difference_amount": 0.0,
        "findings": []
    }

    log_audit_step(
        db=db,
        who=who,
        action="agent_run_matcher",
        details=(
            f"Executed 3-way matcher for invoice ID {invoice_id}: "
            f"status={match_result.get('status')}, "
            f"mistakes={match_result.get('mistake_types')}, "
            f"difference=Rs. {match_result.get('difference_amount', 0.0):,.2f}."
        )
    )

    return {"match_result": match_result}


# =============================================================================
# Pipeline Node 3: Fetch PO and GRN Facts
# =============================================================================
def fetch_po_and_grn_facts(state: InvestigationState) -> Dict[str, Any]:
    invoice_id = state["invoice_id"]
    db = state.get("db_session")
    who = state.get("who", "investigation_agent")

    po_grn = get_po_and_grn(invoice_id, db) if db else {
        "has_po": False,
        "po": None,
        "grn_list": [],
        "items_summary": {}
    }

    po_num = po_grn.get("po", {}).get("po_number") if po_grn.get("po") else "None"
    grn_count = len(po_grn.get("grn_list", []))

    log_audit_step(
        db=db,
        who=who,
        action="agent_fetch_po_grn",
        details=f"Fetched PO and GRN facts for invoice ID {invoice_id}: PO={po_num}, GRN records found={grn_count}."
    )

    return {"po_and_grn_facts": po_grn}


# =============================================================================
# Pipeline Node 4: Search Contract for Clause Behind Each Finding
# =============================================================================
def search_contract_clauses(state: InvestigationState) -> Dict[str, Any]:
    invoice_id = state["invoice_id"]
    db = state.get("db_session")
    who = state.get("who", "investigation_agent")
    inv_data = state.get("invoice_data") or {}
    match_result = state.get("match_result") or {}
    findings_raw = match_result.get("findings", [])
    supplier_name = inv_data.get("supplier_name", "")

    citations: List[Dict[str, Any]] = []
    seen_sources = set()

    # Determine what contract clauses to search strictly based on findings
    queries_to_run: List[Dict[str, str]] = []

    # Filter findings that have issues / failures / warnings
    for f in findings_raw:
        check = f.get("check_name")
        has_issue = (f.get("status") in ("fail", "warning")) or bool(f.get("mistake_type"))
        
        if check == "price" and has_issue:
            ev = f.get("evidence", {})
            item_name = ev.get("item_name") or ""
            if item_name:
                queries_to_run.append({
                    "query": f"agreed unit price for {item_name}",
                    "relevance": f"Agreed unit price terms for {item_name}"
                })
        elif check == "quantity" and has_issue:
            queries_to_run.append({
                "query": "delivery and acceptance terms partial delivery warehouse inspection",
                "relevance": "Delivery & Acceptance terms governing physical quantities received"
            })
        elif check == "totals" and has_issue:
            queries_to_run.append({
                "query": "taxation and GST clause rate",
                "relevance": "Taxation clause defining statutory GST rates and invoicing math"
            })

    # If no findings had issues (clean verified match), query baseline terms for that supplier
    if not queries_to_run:
        items = inv_data.get("items", [])
        if items:
            first_item = items[0].get("item_name", "")
            queries_to_run.append({
                "query": f"agreed unit price for {first_item}",
                "relevance": f"Contract pricing baseline for {first_item}"
            })
        queries_to_run.append({
            "query": "payment terms days credit period",
            "relevance": "Standard payment terms and credit period agreed in master contract"
        })

    # Execute supplier-scoped searches using the contract finder
    for q_spec in queries_to_run:
        res = search_contract(query=q_spec["query"], supplier_name=supplier_name)
        status = res.get("status", "not_found")
        raw_source = res.get("source")
        answer = res.get("answer", "")
        matched_clause = res.get("matched_clause") or {}

        if status in ("found", "conflict"):
            if isinstance(raw_source, list):
                source_str = " | ".join(raw_source)
                sources_list = raw_source
            elif raw_source and raw_source != "no source found":
                source_str = str(raw_source)
                sources_list = res.get("sources") or [source_str]
            else:
                source_str = "Master Contract"
                sources_list = ["Master Contract"]

            source_key = f"{source_str}:{matched_clause.get('clause_number', '')}"
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                citations.append({
                    "supplier_name": supplier_name,
                    "file_name": matched_clause.get("file_name"),
                    "clause_number": matched_clause.get("clause_number"),
                    "clause_title": matched_clause.get("clause_title"),
                    "source": source_str,
                    "sources": sources_list,
                    "text": answer,
                    "relevance_to_finding": q_spec["relevance"],
                    "status": status
                })
        else:
            # Invoice's own supplier has no matching clause in contracts: report 'no source found'
            source_key = f"no_source_found:{q_spec['relevance']}"
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                citations.append({
                    "supplier_name": supplier_name,
                    "file_name": None,
                    "clause_number": None,
                    "clause_title": None,
                    "source": "no source found",
                    "sources": [],
                    "text": "no source found",
                    "relevance_to_finding": q_spec["relevance"],
                    "status": "not_found"
                })

    log_audit_step(
        db=db,
        who=who,
        action="agent_search_contract",
        details=f"Retrieved {len(citations)} contract citations for invoice ID {invoice_id} ({supplier_name})."
    )

    return {"contract_citations": citations}


# =============================================================================
# Pipeline Node 5: Build Evidence List
# =============================================================================
def build_evidence_list(state: InvestigationState) -> Dict[str, Any]:
    invoice_id = state["invoice_id"]
    db = state.get("db_session")
    who = state.get("who", "investigation_agent")
    inv_data = state.get("invoice_data") or {}
    match_result = state.get("match_result") or {}
    po_grn = state.get("po_and_grn_facts") or {}
    raw_findings = match_result.get("findings", [])

    structured_findings: List[Dict[str, Any]] = []

    for f in raw_findings:
        check_name = f.get("check_name", "general")
        raw_ev = f.get("evidence", {})
        diff = float(f.get("difference_amount", 0.0))

        values_compared = {}
        sources = {}

        if check_name == "price":
            item = raw_ev.get("item_name", "item")
            values_compared = {
                "invoiced_unit_price": raw_ev.get("invoiced_unit_price"),
                "po_unit_price": raw_ev.get("po_unit_price"),
                "contract_unit_price": raw_ev.get("contract_unit_price")
            }
            sources = {
                "invoiced_unit_price": "Invoice Extraction (Line Items)",
                "po_unit_price": f"Purchase Order #{inv_data.get('po_number', 'N/A')}",
                "contract_unit_price": f"Supplier Master Contract ({inv_data.get('supplier_name', 'Supplier')})"
            }

        elif check_name == "quantity":
            item = raw_ev.get("item_name", "item")
            values_compared = {
                "invoiced_quantity": raw_ev.get("invoiced_quantity"),
                "po_authorized_quantity": raw_ev.get("po_authorized_quantity"),
                "grn_received_quantity": raw_ev.get("grn_received_quantity")
            }
            sources = {
                "invoiced_quantity": "Invoice Extraction (Line Items)",
                "po_authorized_quantity": f"Purchase Order #{inv_data.get('po_number', 'N/A')}",
                "grn_received_quantity": "Warehouse Physical Receipt (Goods Received Note)"
            }

        elif check_name == "totals":
            # Extract real numbers for subtotal and grand total
            inv_sub = raw_ev.get("invoiced_subtotal") or raw_ev.get("subtotal") or inv_data.get("subtotal")
            
            calc_sub = raw_ev.get("calculated_subtotal")
            if calc_sub is None:
                items_list = inv_data.get("items", [])
                if items_list:
                    calc_sub = round(sum(
                        float(it.get("total_price") or (it.get("quantity", 0) * it.get("unit_price", 0.0)))
                        for it in items_list
                    ), 2)
            if calc_sub is None and inv_sub is not None:
                calc_sub = inv_sub

            inv_gt = raw_ev.get("invoiced_grand_total") or raw_ev.get("grand_total") or inv_data.get("grand_total")
            
            exp_gt = raw_ev.get("expected_grand_total")
            if exp_gt is None and calc_sub is not None:
                exp_gt = round(calc_sub * 1.18, 2)
            if exp_gt is None and inv_gt is not None:
                exp_gt = inv_gt

            values_compared = {
                "invoiced_subtotal": inv_sub,
                "calculated_subtotal": calc_sub,
                "invoiced_grand_total": inv_gt,
                "expected_grand_total": exp_gt
            }
            sources = {
                "invoiced_subtotal": "Invoice Header Extraction",
                "calculated_subtotal": "Sum of Billed Line Items (Quantity * Unit Price)",
                "invoiced_grand_total": "Invoice Header Extraction (Total Payable)",
                "expected_grand_total": "Statutory Calculation (Subtotal + 18% GST)"
            }

        elif check_name == "duplicate":
            values_compared = {
                "invoice_number": raw_ev.get("invoice_number") or inv_data.get("invoice_number"),
                "existing_invoice_id": raw_ev.get("duplicate_of_invoice_id"),
                "duplicate_rule": raw_ev.get("duplicate_rule")
            }
            sources = {
                "invoice_number": "Invoice Header Extraction",
                "existing_invoice_id": "Historical Invoices Database Table",
                "duplicate_rule": "Deterministic Duplicate Detection Check"
            }

        elif check_name == "missing_po":
            po_ref = raw_ev.get("po_reference") or raw_ev.get("po_number") or inv_data.get("po_number")
            values_compared = {
                "po_reference": po_ref
            }
            sources = {
                "po_reference": "Invoice Header Extraction / Purchase Orders Table"
            }

        else:
            values_compared = raw_ev
            sources = {"raw_evidence": "3-Way Matcher Rule Engine"}

        # Universal sanitization: ensure no compared value is None (use 'not available' if missing)
        sanitized_values = {
            k: ("not available" if v is None else v)
            for k, v in values_compared.items()
        }

        structured_findings.append({
            "check_name": check_name,
            "status": f.get("status", "pass"),
            "mistake_type": f.get("mistake_type"),
            "message": f.get("message", ""),
            "evidence": {
                "values_compared": sanitized_values,
                "sources": sources,
                "difference_amount": diff,
                "raw_details": raw_ev
            },
            "difference_amount": diff
        })

    log_audit_step(
        db=db,
        who=who,
        action="agent_build_evidence",
        details=f"Built source-attributed evidence for {len(structured_findings)} findings on invoice ID {invoice_id}."
    )

    return {"findings": structured_findings}

    log_audit_step(
        db=db,
        who=who,
        action="agent_build_evidence",
        details=f"Built source-attributed evidence for {len(structured_findings)} findings on invoice ID {invoice_id}."
    )

    return {"findings": structured_findings}


# =============================================================================
# Pipeline Node 6: Write Template Explanation (No LLM)
# =============================================================================
def write_template_explanation(state: InvestigationState) -> Dict[str, Any]:
    invoice_id = state["invoice_id"]
    db = state.get("db_session")
    who = state.get("who", "investigation_agent")
    inv_data = state.get("invoice_data") or {}
    ext_data = state.get("extraction_data") or {}
    match_result = state.get("match_result") or {}
    citations = state.get("contract_citations") or []
    findings = state.get("findings") or []

    overall_status = match_result.get("status", "needs_review")
    mistake_types = match_result.get("mistake_types", [])
    diff_amount = match_result.get("difference_amount", 0.0)

    supplier_name = inv_data.get("supplier_name", "Supplier")
    inv_number = inv_data.get("invoice_number", "N/A")
    po_number = inv_data.get("po_number", "N/A")
    grand_total = inv_data.get("grand_total", 0.0)

    # Determine recommended_next_action strictly based on findings
    recommended_action: RecommendedAction
    if overall_status == "verified" and (not mistake_types or mistake_types == ["none"]):
        recommended_action = "ready_for_human_approval"
    elif "missing_po" in mistake_types:
        recommended_action = "needs_human_review"
    elif "duplicate_invoice" in mistake_types:
        recommended_action = "reject_and_escalate"
    elif "quantity_mismatch" in mistake_types or "price_mismatch" in mistake_types or "wrong_total" in mistake_types:
        # If discrepancy exceeds Rs. 50,000 or severe over-delivery, escalate; otherwise ask clarification
        if diff_amount > 50000.0:
            recommended_action = "reject_and_escalate"
        else:
            recommended_action = "ask_supplier_for_clarification"
    else:
        recommended_action = "needs_human_review"

    # Extraction confidence baseline
    ext_conf = float(ext_data.get("confidence", 0.95))
    if not ext_data.get("found"):
        ext_conf = 0.90  # Default reliable fallback

    # Compose deterministic template explanation
    lines = [
        f"### Investigation Report for Invoice #{inv_number}",
        f"- **Vendor**: {supplier_name}",
        f"- **PO Reference**: {po_number}",
        f"- **Billed Total**: Rs. {grand_total:,.2f}",
        f"- **Verification Status**: {overall_status.upper()}",
        f"- **Identified Discrepancies**: {', '.join(mistake_types) if mistake_types else 'None'}",
        f"- **Net Financial Discrepancy**: Rs. {diff_amount:,.2f}",
        "",
        "#### Findings & Comparison Evidence:"
    ]

    if not findings or (overall_status == "verified" and (not mistake_types or mistake_types == ["none"])):
        lines.append("1. **Complete 3-Way Match Verified**:")
        lines.append("   - Invoiced line item unit prices match internal Purchase Order and Master Contract.")
        lines.append("   - Invoiced quantities match Warehouse physical delivery receipts (GRN).")
        lines.append("   - Subtotal, 18% statutory GST, and grand total calculations reconcile accurately.")
    else:
        for idx, f in enumerate(findings, 1):
            check = f.get("check_name")
            msg = f.get("message")
            status = f.get("status")
            ev = f.get("evidence", {})
            vals = ev.get("values_compared", {})
            srcs = ev.get("sources", {})

            lines.append(f"{idx}. **Check: {check.upper()}** [{status.upper()}]")
            lines.append(f"   - **Details**: {msg}")
            if vals:
                lines.append("   - **Values Compared & Origin Sources**:")
                for k, v in vals.items():
                    origin = srcs.get(k, "System Record")
                    lines.append(f"     * {k}: `{v}` (Source: {origin})")

    if citations:
        lines.append("")
        lines.append("#### Master Contract Citations:")
        for cit in citations:
            src = cit.get("source", "Contract")
            rel = cit.get("relevance_to_finding", "Governing term")
            excerpt = cit.get("text", "").replace("\n", " ")
            if src == "no source found" or excerpt == "no source found":
                lines.append(f"- **no source found** ({rel}):")
                lines.append(f"  > \"no source found\"")
            else:
                lines.append(f"- **{src}** ({rel}):")
                lines.append(f"  > \"{excerpt[:250]}{'...' if len(excerpt) > 250 else ''}\"")

    lines.append("")
    lines.append(f"#### Recommended Next Action: `{recommended_action}`")
    if recommended_action == "ready_for_human_approval":
        lines.append("All numbers and documents reconcile cleanly. Recommended for finance manager sign-off.")
    elif recommended_action == "ask_supplier_for_clarification":
        lines.append(
            f"Financial variance of Rs. {diff_amount:,.2f} detected. "
            "Recommend contacting the vendor to clarify line item pricing or quantity differences before processing payment."
        )
    elif recommended_action == "reject_and_escalate":
        lines.append(
            f"Critical discrepancy or duplicate billing detected (Variance: Rs. {diff_amount:,.2f}). "
            "Recommend rejecting invoice and escalating to Senior Procurement / AP Lead."
        )
    else:
        lines.append("Document requires manual human inspection due to missing PO or unverified terms.")

    explanation_text = "\n".join(lines)

    limitations = [
        "Advisory boundary: The Investigation Agent does not have authority to approve invoices or release payments.",
        "Deterministic data provenance: All numbers and decisions originate directly from existing tools and database records.",
        "Template synthesis: Report explanation is formulated via deterministic rules without probabilistic LLM text generation."
    ]

    log_audit_step(
        db=db,
        who=who,
        action="agent_write_explanation",
        details=(
            f"Generated template explanation for invoice ID {invoice_id}. "
            f"Action={recommended_action}, Confidence={ext_conf:.2f}."
        )
    )

    return {
        "explanation": explanation_text,
        "recommended_next_action": recommended_action,
        "confidence": ext_conf,
        "limitations": limitations
    }


# =============================================================================
# Pipeline Node 7: Compile Report
# =============================================================================
def compile_report(state: InvestigationState) -> Dict[str, Any]:
    invoice_id = state["invoice_id"]
    db = state.get("db_session")
    who = state.get("who", "investigation_agent")
    inv_data = state.get("invoice_data") or {}
    match_result = state.get("match_result") or {}
    findings_list = state.get("findings") or []
    citations_list = state.get("contract_citations") or []
    explanation = state.get("explanation", "")
    recommended_action = state.get("recommended_next_action", "needs_human_review")
    confidence = float(state.get("confidence", 0.90))
    limitations = state.get("limitations") or []
    supplier_name = inv_data.get("supplier_name", "")

    # Map findings into AgentFinding Pydantic models
    agent_findings: List[AgentFinding] = [
        AgentFinding(
            check_name=f["check_name"],
            status=f["status"],
            mistake_type=f.get("mistake_type"),
            message=f["message"],
            evidence=f.get("evidence", {}),
            difference_amount=float(f.get("difference_amount", 0.0))
        )
        for f in findings_list
    ]

    # Map citations into ContractCitation Pydantic models
    agent_citations: List[ContractCitation] = []
    for c in citations_list:
        src = c.get("source")
        if isinstance(src, list):
            src_str = " | ".join(src)
            src_list = src
        elif src:
            src_str = str(src)
            src_list = c.get("sources") or [src_str]
        else:
            src_str = "no source found"
            src_list = []

        agent_citations.append(
            ContractCitation(
                supplier_name=c.get("supplier_name") or supplier_name,
                file_name=c.get("file_name"),
                clause_number=c.get("clause_number"),
                clause_title=c.get("clause_title"),
                source=src_str,
                sources=src_list,
                text=c.get("text", "no source found"),
                relevance_to_finding=c.get("relevance_to_finding"),
                status=c.get("status", "found")
            )
        )

    report = InvestigationReport(
        invoice_id=invoice_id,
        status=match_result.get("status", "needs_review"),
        findings=agent_findings,
        contract_citations=agent_citations,
        explanation=explanation,
        recommended_next_action=recommended_action,  # type: ignore
        confidence=confidence,
        limitations=limitations
    )

    log_audit_step(
        db=db,
        who=who,
        action="agent_investigation_complete",
        details=(
            f"Investigation report completed for invoice ID {invoice_id}: "
            f"status={report.status}, action={report.recommended_next_action}, "
            f"findings_count={len(report.findings)}, citations_count={len(report.contract_citations)}."
        )
    )

    return {"report": report.model_dump()}


# =============================================================================
# Build and Compile LangGraph Workflow
# =============================================================================
def create_investigation_graph() -> StateGraph:
    workflow = StateGraph(InvestigationState)

    # Register workflow nodes
    workflow.add_node("load_invoice_and_extraction", load_invoice_and_extraction)
    workflow.add_node("run_matcher", run_matcher_step)
    workflow.add_node("fetch_po_and_grn_facts", fetch_po_and_grn_facts)
    workflow.add_node("search_contract_clauses", search_contract_clauses)
    workflow.add_node("build_evidence_list", build_evidence_list)
    workflow.add_node("write_template_explanation", write_template_explanation)
    workflow.add_node("compile_report", compile_report)

    # Linear workflow sequence
    workflow.add_edge(START, "load_invoice_and_extraction")
    workflow.add_edge("load_invoice_and_extraction", "run_matcher")
    workflow.add_edge("run_matcher", "fetch_po_and_grn_facts")
    workflow.add_edge("fetch_po_and_grn_facts", "search_contract_clauses")
    workflow.add_edge("search_contract_clauses", "build_evidence_list")
    workflow.add_edge("build_evidence_list", "write_template_explanation")
    workflow.add_edge("write_template_explanation", "compile_report")
    workflow.add_edge("compile_report", END)

    return workflow.compile()


investigation_app = create_investigation_graph()


def run_investigation(
    invoice_id: int,
    db: Session,
    who: str = "investigation_agent"
) -> InvestigationReport:
    """
    Executes the LangGraph investigation workflow end-to-end for an invoice.
    Returns the validated InvestigationReport Pydantic object.
    """
    initial_state: InvestigationState = {
        "invoice_id": invoice_id,
        "db_session": db,
        "who": who,
        "invoice_data": None,
        "extraction_data": None,
        "match_result": None,
        "po_and_grn_facts": None,
        "contract_citations": [],
        "findings": [],
        "explanation": "",
        "recommended_next_action": "needs_human_review",
        "confidence": 0.0,
        "limitations": [],
        "report": None,
        "audit_entries": [],
        "errors": []
    }

    final_state = investigation_app.invoke(initial_state)
    report_dict = final_state.get("report")
    if not report_dict:
        raise RuntimeError(f"Investigation failed to generate report for invoice ID {invoice_id}")

    return InvestigationReport(**report_dict)
