"""
Evidence view on the Investigation page: raw evidence JSON -> clean rows
(What we compared | Value | Source) and a Match / Mismatch pill.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

import ui_common as ui  # noqa: E402

PRICE_EVIDENCE = {
    "values_compared": {"invoiced_unit_price": 2000.0, "po_unit_price": 1500.0, "contract_unit_price": 1500.0},
    "sources": {
        "invoiced_unit_price": "Invoice Extraction (Line Items)",
        "po_unit_price": "Purchase Order #PO-2026-0019",
        "contract_unit_price": "Supplier Master Contract",
    },
    "difference_amount": 6490.0,
    "raw_details": {"item_name": "Wireless Keyboard & Mouse Combo"},
}


def test_rows_use_values_and_sources():
    rows = ui.evidence_rows(PRICE_EVIDENCE)
    assert rows[0] == {
        "What we compared": "Invoiced unit price",
        "Value": "₹2,000.00",
        "Source": "Invoice Extraction (Line Items)",
    }
    assert rows[1]["What we compared"] == "PO unit price"
    assert len(rows) == 3  # raw_details / difference are not rows


def test_rows_fallback_for_plain_evidence():
    rows = ui.evidence_rows({"duplicate_of": "INV-2026-0001", "same_amount": True})
    assert rows == [
        {"What we compared": "Duplicate of", "Value": "INV-2026-0001", "Source": "—"},
        {"What we compared": "Same amount", "Value": "Yes", "Source": "—"},
    ]
    assert ui.evidence_rows(None) == []


def test_quantities_are_not_money():
    rows = ui.evidence_rows({"values_compared": {"grn_received_quantity": 4}, "sources": {}})
    assert rows[0] == {"What we compared": "GRN received quantity", "Value": "4", "Source": "—"}


def test_result_pills():
    assert "vf-verified" in ui.result_pill("pass") and ">Match<" in ui.result_pill("pass")
    assert "vf-mismatch_detected" in ui.result_pill("fail") and ">Mismatch<" in ui.result_pill("fail")
    assert "vf-other" in ui.result_pill("unknown")


def test_material_icon_name():
    assert ui.material_name(":material/home:") == "home"
