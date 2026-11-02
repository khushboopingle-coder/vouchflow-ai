"""
VouchFlow AI - Extraction Evaluation Script
===========================================
Evaluates AI extraction accuracy against the ground truth dataset.

Features:
1. Multi-model automatic fallback support with daily limit detection.
2. Caching & Resume: --resume reuses successful past extractions; --force re-evaluates all.
3. Strict, fair normalization:
   - Invoice numbers: case/whitespace/punctuation insensitive.
   - Dates: parsed to ISO YYYY-MM-DD.
   - Totals: parsed as floats with tolerance <= 0.01.
   - Item count: exact count match.
   - Empty/missing/failed extractions strictly count as WRONG for all fields (including vendor).
4. Tracks `model_name` and `error_message` for full visibility in extraction_results.csv.
5. Displays clear breakdown of Attempted, Failed, and Not Attempted invoices.
"""

import os
import sys
import json
import time
import re
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import pandas as pd

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import settings
from backend.tools.invoice_reader import InvoiceReader, reader
from backend.database.schemas import ExtractedInvoice, ExtractedItem


def normalize_str(s: Any) -> str:
    """Normalizes string for robust, fair comparison."""
    if s is None or pd.isna(s):
        return ""
    clean = str(s).lower().strip()
    # Strip common business legal suffixes
    for suffix in ["pvt ltd", "pvt. ltd.", "ltd", "enterprises", "traders", "supplies", "commercials", "solutions"]:
        clean = clean.replace(suffix, "")
    return "".join(c for c in clean if c.isalnum())


def normalize_inv_num(s: Any) -> str:
    """Normalizes invoice numbers by lowercasing and stripping punctuation and whitespace."""
    if s is None or pd.isna(s):
        return ""
    return "".join(c for c in str(s).lower() if c.isalnum())


def parse_date_to_iso(date_str: Any) -> Optional[str]:
    """Parses various date string formats into standard YYYY-MM-DD."""
    if date_str is None or pd.isna(date_str):
        return None
    s = str(date_str).strip()
    if not s:
        return None
    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d-%b-%Y",
        "%d %B %Y",
        "%B %d, %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Simple delimiter fallback
    parts = re.split(r'[-/.]', s)
    if len(parts) == 3:
        if len(parts[0]) == 4:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        elif len(parts[2]) == 4:
            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    return None


def compare_dates(d1: Any, d2: Any) -> bool:
    """Compares two dates in standardized ISO format."""
    iso1 = parse_date_to_iso(d1)
    iso2 = parse_date_to_iso(d2)
    if iso1 and iso2:
        return iso1 == iso2
    return False


def run_evaluation(count: int = 10, use_mock: bool = False, resume: bool = False, force: bool = False):
    """
    Evaluates extraction accuracy across invoices with multi-model fallback,
    resuming capability, and strict normalized scoring.
    """
    eval_dir = BASE_DIR / "data" / "evaluation"
    gt_csv_path = eval_dir / "ground_truth.csv"
    mock_json_path = eval_dir / "mock_data.json"
    results_csv_path = eval_dir / "extraction_results.csv"

    if not gt_csv_path.exists():
        print(f"Error: Ground truth CSV not found at {gt_csv_path}")
        print("Run 'python scripts/generate_data.py' first.")
        return

    # 1. Load ground truth dataset
    gt_df = pd.read_csv(gt_csv_path)
    print("=" * 80)
    print("VOUCHFLOW AI - INVOICE READER EVALUATION")
    print("=" * 80)
    print(f"Ground truth columns found ({len(gt_df.columns)}):")
    print(list(gt_df.columns))
    print("-" * 80)

    # 2. Load ground truth metadata (dates, item counts) from mock_data.json
    mock_dates = {}
    mock_item_counts = {}
    if mock_json_path.exists():
        with open(mock_json_path, "r", encoding="utf-8") as f:
            mock_data = json.load(f)
            for inv in mock_data.get("invoices", []):
                mock_dates[inv["id"]] = inv.get("invoice_date")
                mock_item_counts[inv["id"]] = len(inv.get("items", []))

    # 3. Handle caching & resume
    cached_results: Dict[int, Dict[str, Any]] = {}
    if resume and not force and results_csv_path.exists():
        try:
            prev_df = pd.read_csv(results_csv_path)
            for _, r in prev_df.iterrows():
                # Only cache successful extractions
                if bool(r.get("is_success")):
                    cached_results[int(r["invoice_id"])] = r.to_dict()
            print(f"[Resume] Found {len(cached_results)} existing successful extractions in cache.")
        except Exception as e:
            print(f"[Resume] Notice: could not load cache: {e}")

    eval_subset = gt_df.head(count).copy()
    print(f"Evaluating {len(eval_subset)} invoices (Active models: {', '.join(settings.gemini_models)})...\n")

    eval_rows = []
    stopped_early = False

    for idx, row in eval_subset.iterrows():
        inv_id = int(row["invoice_id"])
        file_name = row["file_name"]
        pdf_path = BASE_DIR / "data" / "invoices" / file_name

        print(f"[{idx + 1}/{len(eval_subset)}] Processing {file_name} (ID: {inv_id})...", end=" ")

        # Check cache
        if inv_id in cached_results and not force:
            cached = cached_results[inv_id]
            ext_vendor = str(cached.get("extracted_vendor", ""))
            ext_inv_num = str(cached.get("extracted_invoice_number", ""))
            ext_date = str(cached.get("extracted_invoice_date", ""))
            ext_total = float(cached.get("extracted_grand_total", 0.0))
            ext_items = int(cached.get("extracted_item_count", 0))
            confidence = float(cached.get("confidence", 1.0))
            is_success = bool(cached.get("is_success", True))
            model_used = str(cached.get("model_name", "cached"))
            error_msg = str(cached.get("error_message", ""))
            print(f"[CACHED - {model_used}]", end=" ")

        elif use_mock:
            # Mock mode for testing without hitting Gemini API
            ext_vendor = row["supplier_name"]
            ext_inv_num = row["invoice_number"]
            ext_date = mock_dates.get(inv_id, "2026-01-12")
            ext_total = float(row["invoiced_grand_total"])
            ext_items = mock_item_counts.get(inv_id, 1)
            confidence = 1.0
            is_success = True
            model_used = "mock"
            error_msg = ""

        else:
            if not pdf_path.exists():
                print(f"[File Not Found: {pdf_path}]")
                continue

            # Check if all models are exhausted before calling
            if reader.current_model is None:
                print("\n[STOP] All models reached their daily limit. Run again tomorrow with --resume")
                stopped_early = True
                break

            # Live extraction using InvoiceReader
            extracted = reader.read_invoice(str(pdf_path), rate_limit_delay=0.5)

            ext_vendor = extracted.vendor or ""
            ext_inv_num = extracted.invoice_number or ""
            ext_date = extracted.invoice_date or ""
            ext_total = float(extracted.grand_total or 0.0)
            ext_items = len(extracted.items)
            confidence = extracted.confidence
            is_success = extracted.is_success
            model_used = extracted.model_name or "unknown"
            error_msg = extracted.error_message or ""

            # Check if reading signaled exhaustion
            if not is_success and "All models reached" in error_msg:
                stopped_early = True

        # Expected Ground Truth values
        gt_vendor = str(row["supplier_name"])
        gt_inv_num = str(row["invoice_number"])
        gt_date = str(mock_dates.get(inv_id, ""))
        gt_total = float(row["invoiced_grand_total"])
        gt_items = int(mock_item_counts.get(inv_id, 1))

        # =====================================================================
        # STRICT & FAIR SCORING LOGIC
        # Rule: Any failed, empty or missing extraction MUST count as False (WRONG)
        # =====================================================================
        if not is_success:
            vendor_match = False
            inv_num_match = False
            date_match = False
            total_match = False
            item_count_match = False
        else:
            # 1. Vendor: non-empty check + normalized substring match
            norm_gt_v = normalize_str(gt_vendor)
            norm_ext_v = normalize_str(ext_vendor)
            if not norm_ext_v:
                vendor_match = False
            else:
                vendor_match = (norm_gt_v in norm_ext_v or norm_ext_v in norm_gt_v)

            # 2. Invoice Number: alphanumeric normalization
            norm_gt_num = normalize_inv_num(gt_inv_num)
            norm_ext_num = normalize_inv_num(ext_inv_num)
            if not norm_ext_num:
                inv_num_match = False
            else:
                inv_num_match = (norm_gt_num == norm_ext_num)

            # 3. Invoice Date: ISO comparison
            date_match = compare_dates(gt_date, ext_date)

            # 4. Grand Total: float tolerance comparison (within 0.01)
            try:
                total_match = abs(float(gt_total) - float(ext_total)) <= 0.01
            except (ValueError, TypeError):
                total_match = False

            # 5. Line Item Count
            item_count_match = (gt_items == ext_items) and (ext_items > 0 or gt_items == 0)

        all_match = all([vendor_match, inv_num_match, date_match, total_match, item_count_match])
        status_symbol = "[PASS]" if all_match else "[DIFF]"
        print(f"{status_symbol} (Confidence: {confidence:.2f}, Model: {model_used})")

        eval_rows.append({
            "invoice_id": inv_id,
            "file_name": file_name,
            "gt_vendor": gt_vendor,
            "extracted_vendor": ext_vendor if is_success else "",
            "vendor_match": vendor_match,
            "gt_invoice_number": gt_inv_num,
            "extracted_invoice_number": ext_inv_num if is_success else "",
            "invoice_number_match": inv_num_match,
            "gt_invoice_date": gt_date,
            "extracted_invoice_date": ext_date if is_success else "",
            "date_match": date_match,
            "gt_grand_total": gt_total,
            "extracted_grand_total": ext_total if is_success else 0.0,
            "total_match": total_match,
            "gt_item_count": gt_items,
            "extracted_item_count": ext_items if is_success else 0,
            "item_count_match": item_count_match,
            "all_fields_match": all_match,
            "confidence": confidence,
            "is_success": is_success,
            "model_name": model_used,
            "error_message": error_msg
        })

        if stopped_early:
            print("\nAll models reached their daily limit. Run again tomorrow with --resume")
            break

    # Save results to CSV (merging with existing cache if resuming)
    results_df = pd.DataFrame(eval_rows)
    if resume and results_csv_path.exists() and not force:
        try:
            existing_df = pd.read_csv(results_csv_path)
            # Combine existing and new rows, keeping the latest by invoice_id
            combined = pd.concat([existing_df, results_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["invoice_id"], keep="last")
            results_df = combined.sort_values(by="invoice_id")
        except Exception:
            pass

    results_df.to_csv(results_csv_path, index=False)

    # 4. Accuracy Report Output
    total_requested = len(eval_subset)
    attempted_count = len(eval_rows)
    not_attempted_count = total_requested - attempted_count
    failed_extractions = sum(1 for r in eval_rows if not r["is_success"])

    print("\n" + "=" * 80)
    print("                     EXTRACTION ACCURACY REPORT")
    print("=" * 80)
    print(f"Total Invoices Requested: {total_requested}")
    print(f"Attempted:                {attempted_count}/{total_requested}")
    print(f"Failed extractions:       {failed_extractions}/{attempted_count if attempted_count else 1}")
    print(f"Not attempted:            {not_attempted_count}/{total_requested}")
    print("-" * 80)

    if attempted_count == 0:
        print("No invoices were attempted.")
        return

    report_df = pd.DataFrame(eval_rows)
    vendor_acc = report_df["vendor_match"].mean() * 100
    inv_num_acc = report_df["invoice_number_match"].mean() * 100
    date_acc = report_df["date_match"].mean() * 100
    total_acc = report_df["total_match"].mean() * 100
    item_count_acc = report_df["item_count_match"].mean() * 100
    overall_field_acc = (vendor_acc + inv_num_acc + date_acc + total_acc + item_count_acc) / 5.0
    perfect_invoice_acc = report_df["all_fields_match"].mean() * 100

    print(f"{'Field':<30} {'Matched':<15} {'Accuracy':<15}")
    print("-" * 60)
    print(f"{'Vendor Name':<30} {report_df['vendor_match'].sum()}/{attempted_count:<12} {vendor_acc:>6.1f}%")
    print(f"{'Invoice Number':<30} {report_df['invoice_number_match'].sum()}/{attempted_count:<12} {inv_num_acc:>6.1f}%")
    print(f"{'Invoice Date':<30} {report_df['date_match'].sum()}/{attempted_count:<12} {date_acc:>6.1f}%")
    print(f"{'Grand Total (Rs.)':<30} {report_df['total_match'].sum()}/{attempted_count:<12} {total_acc:>6.1f}%")
    print(f"{'Line Item Count':<30} {report_df['item_count_match'].sum()}/{attempted_count:<12} {item_count_acc:>6.1f}%")
    print("-" * 60)
    print(f"{'Overall Field Accuracy':<30} {'--':<15} {overall_field_acc:>6.1f}%")
    print(f"{'Completely Perfect Invoices':<30} {report_df['all_fields_match'].sum()}/{attempted_count:<12} {perfect_invoice_acc:>6.1f}%")
    print("=" * 80)
    print(f"Detailed per-invoice results saved to:\n  {results_csv_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate VouchFlow AI Invoice Reader accuracy")
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of invoices to evaluate (default: 10)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode without hitting external Gemini API"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume evaluation by reusing successful cached extractions"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-evaluation of all invoices, ignoring cached results"
    )
    args = parser.parse_args()

    run_evaluation(count=args.count, use_mock=args.mock, resume=args.resume, force=args.force)
