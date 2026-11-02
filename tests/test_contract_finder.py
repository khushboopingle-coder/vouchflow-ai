"""Unit tests for Contract Finder RAG (Phase 4).
Verifies:
(a) Correct answer with its source (file name and clause number)
(b) Unanswerable question returning "I don't know" and no source
(c) Two conflicting contracts / clauses detected and showing both sources
"""
import pytest
from backend.tools.contract_finder import ask_contract, get_vector_store


@pytest.fixture(scope="module")
def vector_store():
    """Initializes and reuses vector store for tests."""
    return get_vector_store()


def test_ask_contract_correct_answer_with_source(vector_store):
    """Test (a): Valid question returns the correct clause text and exact source."""
    # Query 1: Payment terms for Sharma Traders
    res1 = ask_contract("What are the payment terms for Sharma Traders?", vector_store=vector_store)
    assert res1["status"] == "found"
    assert res1["source"] == "contract_supplier_1.txt, Clause 4"
    assert "30 days" in res1["answer"].lower()
    assert res1["matched_clause"]["clause_number"] == "Clause 4"
    assert res1["matched_clause"]["file_name"] == "contract_supplier_1.txt"

    # Query 2: Warranty period for Verma Tech Components
    res2 = ask_contract("What is the warranty period for Verma Tech Components?", vector_store=vector_store)
    assert res2["status"] == "found"
    assert res2["source"] == "contract_supplier_6.txt, Clause 5"
    assert "24 months" in res2["answer"].lower()

    # Query 3: Early payment discount for Singh & Sons Equipment
    res3 = ask_contract("What early payment cash discount is offered by Singh & Sons Equipment?", vector_store=vector_store)
    assert res3["status"] == "found"
    assert res3["source"] == "contract_supplier_8.txt, Clause 7"
    assert "3%" in res3["answer"]


def test_ask_contract_unanswerable_returns_i_dont_know(vector_store):
    """Test (b): Out-of-domain / unanswerable questions must return 'I don't know' and source=None."""
    unanswerable_queries = [
        "What is the policy for annual employee festival bonuses?",
        "Can employees expense weekend personal flights to Tokyo?",
        "What is the CEO's favorite brand of coffee?"
    ]
    for q in unanswerable_queries:
        res = ask_contract(q, vector_store=vector_store)
        assert res["status"] == "not_found", f"Expected 'not_found' for query: {q}"
        assert res["answer"] == "I don't know", f"Expected 'I don't know', got: {res['answer']}"
        assert res["source"] is None, f"Expected source to be None, got: {res['source']}"
        assert res["sources"] == []


def test_ask_contract_conflicting_contracts(vector_store):
    """Test (c): When contracts disagree, return status='conflict' and show both sources."""
    # Conflict 1: Amendment conflict (Original Clause 1 vs Addendum Clause 8)
    res_amend = ask_contract("What is the agreed unit price for High-Speed USB-C Dock for Sharma Traders?", vector_store=vector_store)
    assert res_amend["status"] == "conflict"
    assert len(res_amend["sources"]) >= 2
    assert "contract_supplier_1.txt, Clause 1" in res_amend["sources"]
    assert "contract_supplier_1.txt, Clause 8" in res_amend["sources"]
    assert "conflict" in res_amend["answer"].lower()

    # Conflict 2: Cross-supplier conflict across vendors on general warranty
    res_cross = ask_contract("What is the standard warranty period across vendor equipment contracts?", vector_store=vector_store)
    assert res_cross["status"] == "conflict"
    assert len(res_cross["sources"]) >= 2
    # Ensure sources come from different contracts
    src_files = [s.split(",")[0].strip() for s in res_cross["sources"]]
    assert len(set(src_files)) >= 2, f"Expected conflicting sources from different files, got {src_files}"
