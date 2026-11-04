"""
Phase 3 tests: contract search (RAG) is per workspace.

- a contract uploaded by user A is found for A and NEVER for user B
- a workspace with the sample data can search the sample contracts
- a workspace without any contracts finds nothing
- the shared sample workspace keeps using the original index (evals unchanged)
"""

import pytest

from backend.database.db import SessionLocal
from backend.services import upload_service
from backend.tools.contract_finder import ask_contract
from tests.helpers import temp_user

SECRET_CLAUSE = (
    "ZEPHYR MASTER AGREEMENT\n\n"
    "Late delivery penalty: Zephyr pays a penalty of 7 percent per week of late delivery.\n\n"
    "Payment terms: invoices are payable within 21 days of receipt."
)


@pytest.fixture(scope="module")
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def users(db):
    with temp_user(load_sample=False) as a, temp_user(load_sample=False) as b:
        upload_service.save_contract_document(db, a.workspace_id, "zephyr.txt", SECRET_CLAUSE.encode(),
                                              "Zephyr Office Supplies")
        yield a, b


def test_own_contract_is_found(users):
    a, _ = users
    result = ask_contract("late delivery penalty per week", supplier_name="Zephyr Office Supplies",
                          workspace_id=a.workspace_id)
    assert result["status"] == "found"
    assert "7 percent" in result["answer"]
    assert "zephyr.txt" in result["source"]


def test_other_workspace_cannot_find_it(users):
    _, b = users
    for supplier in ("Zephyr Office Supplies", None):
        result = ask_contract("late delivery penalty per week Zephyr", supplier_name=supplier,
                              workspace_id=b.workspace_id)
        assert result["status"] == "not_found"
        assert "7 percent" not in str(result)


def test_sample_contracts_searchable_with_sample_data():
    with temp_user(load_sample=True) as user:
        result = ask_contract("payment terms days", supplier_name="Sharma Traders Pvt Ltd",
                              workspace_id=user.workspace_id)
        assert result["status"] == "found"
        assert "contract_supplier_1.txt" in result["source"]


def test_sample_workspace_uses_shared_index(sample_ws_id):
    result = ask_contract("payment terms days", supplier_name="Sharma Traders Pvt Ltd", workspace_id=sample_ws_id)
    assert result["status"] == "found" and "contract_supplier_1.txt" in result["source"]


def test_new_upload_is_searchable_straight_away(db, users):
    a, _ = users
    upload_service.save_contract_document(
        db, a.workspace_id, "zephyr_addendum.txt",
        b"Warranty: Zephyr replaces any broken chair free of charge for 3 years.", "Zephyr Office Supplies")
    result = ask_contract("warranty broken chair replacement", supplier_name="Zephyr Office Supplies",
                          workspace_id=a.workspace_id)
    assert result["status"] == "found" and "3 years" in result["answer"]
