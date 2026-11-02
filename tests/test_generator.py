"""
Generator & Ground Truth Automated Tests
========================================
Tests that:
1. scripts/generate_data.py creates 50 PDF files in data/invoices/
2. 8 supplier contracts are created in data/contracts/
3. data/evaluation/ground_truth.csv exists with 50 rows and required columns
4. Ground truth mistake distribution matches requirements (70% clean, 30% planted mistakes)
"""

import os
from pathlib import Path
import pandas as pd
import pytest

from scripts.generate_data import generate_contracts, generate_dataset


@pytest.fixture(scope="module", autouse=True)
def ensure_data_generated():
    """Ensures data generation has been run before testing files."""
    invoices_dir = Path("data/invoices")
    contracts_dir = Path("data/contracts")
    gt_path = Path("data/evaluation/ground_truth.csv")

    # If any file is missing, run generator
    pdf_count = len(list(invoices_dir.glob("*.pdf"))) if invoices_dir.exists() else 0
    if pdf_count < 50 or not gt_path.exists():
        generate_contracts()
        generate_dataset()


def test_generated_pdf_files_count_and_size():
    """Verifies that at least 50 invoice PDFs exist (including standard 50) and each has valid content size."""
    invoices_dir = Path("data/invoices")
    assert invoices_dir.exists(), "data/invoices directory does not exist."

    pdf_files = list(invoices_dir.glob("*.pdf"))
    assert len(pdf_files) >= 50, f"Expected at least 50 invoice PDFs, found {len(pdf_files)}."

    # Verify standard dataset 50 invoices all exist
    for i in range(1, 51):
        std_pdf = invoices_dir / f"INV_{i:03d}.pdf"
        assert std_pdf.exists(), f"Standard invoice {std_pdf.name} is missing."

    # Verify each PDF has a realistic file size (> 1000 bytes)
    for pdf in pdf_files:
        assert pdf.stat().st_size > 1000, f"PDF file {pdf.name} is too small or corrupted."


def test_generated_supplier_contracts():
    """Verifies that 8 contract text files exist in data/contracts/."""
    contracts_dir = Path("data/contracts")
    assert contracts_dir.exists(), "data/contracts directory does not exist."

    contract_files = list(contracts_dir.glob("*.txt"))
    assert len(contract_files) == 8, f"Expected 8 contract text files, found {len(contract_files)}."

    # Check content of the first contract
    sample_content = contract_files[0].read_text(encoding="utf-8")
    assert "MASTER VENDOR SUPPLY AGREEMENT" in sample_content
    assert "GST" in sample_content
    assert "Rs." in sample_content


def test_ground_truth_csv_structure_and_columns():
    """Verifies ground_truth.csv existence, row count, and required schema columns."""
    gt_path = Path("data/evaluation/ground_truth.csv")
    assert gt_path.exists(), "ground_truth.csv file does not exist."

    df = pd.read_csv(gt_path)
    assert len(df) == 50, f"Expected 50 rows in ground_truth.csv, got {len(df)}."

    # Required columns
    expected_columns = {
        "invoice_id",
        "file_name",
        "expected_status",
        "mistake_type",
        "supplier_name",
        "po_number",
        "correct_subtotal",
        "correct_grand_total"
    }
    missing_cols = expected_columns - set(df.columns)
    assert not missing_cols, f"Missing columns in ground_truth.csv: {missing_cols}"


def test_mistake_distribution():
    """
    Verifies that about 70% of invoices are clean (35 invoices)
    and exactly 30% have planted mistakes (15 invoices across the 5 categories).
    """
    gt_path = Path("data/evaluation/ground_truth.csv")
    df = pd.read_csv(gt_path)

    mistake_counts = df["mistake_type"].value_counts().to_dict()

    # Clean invoices (70%)
    assert mistake_counts.get("none", 0) == 35, (
        f"Expected 35 clean invoices, got {mistake_counts.get('none', 0)}."
    )

    # 5 planted mistake types
    required_mistakes = [
        "price_mismatch",
        "quantity_mismatch",
        "wrong_total",
        "duplicate_invoice",
        "missing_po"
    ]
    for mistake in required_mistakes:
        assert mistake in mistake_counts, f"Mistake type '{mistake}' not found in ground truth."
        assert mistake_counts[mistake] == 3, (
            f"Expected 3 occurrences of '{mistake}', got {mistake_counts[mistake]}."
        )

    # Allowed status values only
    allowed_statuses = {"verified", "needs_review", "mismatch_detected", "pending_approval"}
    unique_statuses = set(df["expected_status"].unique())
    assert unique_statuses.issubset(allowed_statuses), (
        f"Found unexpected statuses: {unique_statuses - allowed_statuses}"
    )
