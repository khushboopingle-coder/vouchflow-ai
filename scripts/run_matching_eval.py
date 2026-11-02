"""
VouchFlow AI - 3-Way Matching Evaluation Script
================================================
Evaluates the 3-Way Matching checker against ground_truth.csv or hard_ground_truth.csv.

Features:
1. Evaluates all invoices with successful extractions (or all 50 with --all, or 40 hard with --hard).
2. Computes Overall Status Accuracy.
3. Computes BOTH Overall Mistake Type Accuracies:
   - "Strict" Accuracy: Primary predicted mistake must equal expected mistake.
   - "Multi-Label" Accuracy: Expected mistake must be present among all detected mistakes.
4. Computes Precision, Recall, and F1 score per mistake type for BOTH strict and multi-label modes.
5. Generates an ASCII Confusion Matrix of Expected vs. Predicted Status.
6. Saves itemized per-invoice results to data/evaluation/matching_results.csv (or hard_matching_results.csv).
7. Clearly diagnoses and reports any misclassified invoices with root causes.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.database.db import SessionLocal
from backend.database.models import Invoice, InvoiceExtraction
from backend.tools.matcher import perform_three_way_match


def compute_classification_metrics(expected_list: List[str], predicted_list: List[str], labels: List[str]) -> pd.DataFrame:
    """Computes TP, FP, FN, Precision, Recall, and F1 for a given set of labels (Strict Single-Label)."""
    metrics_data = []

    for label in labels:
        tp = sum(1 for e, p in zip(expected_list, predicted_list) if e == label and p == label)
        fp = sum(1 for e, p in zip(expected_list, predicted_list) if e != label and p == label)
        fn = sum(1 for e, p in zip(expected_list, predicted_list) if e == label and p != label)

        precision = (tp / (tp + fp)) * 100 if (tp + fp) > 0 else 0.0
        recall = (tp / (tp + fn)) * 100 if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        metrics_data.append({
            "Mistake Type": label,
            "TP": tp,
            "FP": fp,
            "FN": fn,
            "Precision": f"{precision:5.1f}%",
            "Recall": f"{recall:5.1f}%",
            "F1": f"{f1:5.1f}%"
        })

    return pd.DataFrame(metrics_data)


def compute_multilabel_classification_metrics(expected_list: List[str], predicted_sets: List[List[str]], labels: List[str]) -> pd.DataFrame:
    """Computes TP, FP, FN, Precision, Recall, and F1 where expected label is checked against all detected labels."""
    metrics_data = []

    for label in labels:
        tp = 0
        fp = 0
        fn = 0

        for exp, pred_set in zip(expected_list, predicted_sets):
            if label == "none":
                # For clean invoices, TP means no mistakes detected at all
                if exp == "none" and ("none" in pred_set or not pred_set):
                    tp += 1
                elif exp != "none" and ("none" in pred_set or not pred_set):
                    fp += 1
                elif exp == "none" and ("none" not in pred_set and len(pred_set) > 0):
                    fn += 1
            else:
                in_pred = label in pred_set
                is_exp = (exp == label)

                if is_exp and in_pred:
                    tp += 1
                elif not is_exp and in_pred:
                    fp += 1
                elif is_exp and not in_pred:
                    fn += 1

        precision = (tp / (tp + fp)) * 100 if (tp + fp) > 0 else 0.0
        recall = (tp / (tp + fn)) * 100 if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        metrics_data.append({
            "Mistake Type": label,
            "TP": tp,
            "FP": fp,
            "FN": fn,
            "Precision": f"{precision:5.1f}%",
            "Recall": f"{recall:5.1f}%",
            "F1": f"{f1:5.1f}%"
        })

    return pd.DataFrame(metrics_data)


def run_matching_evaluation(eval_all: bool = False, count: int = None, is_hard: bool = False):
    """
    Runs the 3-way matching checker across invoices and evaluates
    against ground_truth.csv or hard_ground_truth.csv.
    Reports BOTH strict and multi-label accuracy metrics.
    """
    eval_dir = BASE_DIR / "data" / "evaluation"

    if is_hard:
        gt_csv_path = eval_dir / "hard_ground_truth.csv"
        out_csv_path = eval_dir / "hard_matching_results.csv"
        eval_title = "VOUCHFLOW AI - 3-WAY MATCHING HARD STRESS-TEST EVALUATION"
    else:
        gt_csv_path = eval_dir / "ground_truth.csv"
        out_csv_path = eval_dir / "matching_results.csv"
        eval_title = "VOUCHFLOW AI - 3-WAY MATCHING STANDARD EVALUATION"

    ext_csv_path = eval_dir / "extraction_results.csv"

    if not gt_csv_path.exists():
        print(f"Error: Ground truth CSV not found at {gt_csv_path}")
        if is_hard:
            print("Run 'python scripts/generate_hard_cases.py' first.")
        else:
            print("Run 'python scripts/generate_data.py' first.")
        return

    gt_df = pd.read_csv(gt_csv_path)
    db = SessionLocal()

    if is_hard:
        target_df = gt_df.copy()
        print(f"Evaluating all {len(target_df)} hard stress-test invoices from {gt_csv_path.name}...")
    else:
        # Identify which invoices have extractions available in database or extraction_results.csv
        extracted_invoice_ids = set()

        # Check database invoice_extractions table
        db_extracted_ids = [r[0] for r in db.query(InvoiceExtraction.invoice_id).distinct().all()]
        extracted_invoice_ids.update(db_extracted_ids)

        # Check extraction_results.csv
        if ext_csv_path.exists():
            try:
                ext_df = pd.read_csv(ext_csv_path)
                for _, r in ext_df.iterrows():
                    if bool(r.get("is_success")):
                        extracted_invoice_ids.add(int(r["invoice_id"]))
            except Exception:
                pass

        # Determine target invoices
        if eval_all or not extracted_invoice_ids:
            target_df = gt_df.copy()
            if eval_all:
                print(f"Evaluating ALL {len(target_df)} invoices in ground truth dataset...")
            else:
                print(f"No previous extraction records found. Evaluating all {len(target_df)} invoices...")
        else:
            target_df = gt_df[gt_df["invoice_id"].isin(extracted_invoice_ids)].copy()
            print(f"Evaluating {len(target_df)} invoices with successful extractions (use --all to evaluate all 50)...")

    if count and count < len(target_df):
        target_df = target_df.head(count).copy()

    results_rows = []
    expected_statuses = []
    predicted_statuses = []
    expected_mistakes = []
    predicted_primary_mistakes = []
    predicted_all_mistakes = []
    errors = []

    print("\n" + "=" * 80)
    print(eval_title)
    print("=" * 80)

    for idx, row in target_df.iterrows():
        inv_id = int(row["invoice_id"])
        file_name = row.get("file_name") or row.get("invoice_file") or f"INV_{inv_id:03d}.pdf"
        exp_status = row["expected_status"]
        exp_mistake = row.get("mistake_type") or row.get("expected_mistake")
        notes = row.get("notes") or row.get("description") or ""

        # Run 3-way matching engine (loads extracted data from database)
        check_res = perform_three_way_match(invoice_id=inv_id, db=db)

        pred_status = check_res.status
        pred_mistake_list = check_res.mistake_types if check_res.mistake_types else ["none"]
        primary_pred_mistake = pred_mistake_list[0]

        status_correct = (pred_status == exp_status)
        strict_mistake_correct = (primary_pred_mistake == exp_mistake)

        if exp_mistake == "none":
            multilabel_mistake_correct = (primary_pred_mistake == "none")
        else:
            multilabel_mistake_correct = (exp_mistake in pred_mistake_list)

        expected_statuses.append(exp_status)
        predicted_statuses.append(pred_status)
        expected_mistakes.append(exp_mistake)
        predicted_primary_mistakes.append(primary_pred_mistake)
        predicted_all_mistakes.append(pred_mistake_list)

        if status_correct and strict_mistake_correct:
            status_badge = "[PASS]"
        elif status_correct and multilabel_mistake_correct:
            status_badge = "[MULTI]"
        else:
            status_badge = "[DIFF]"

        print(f"[{len(results_rows) + 1:2d}/{len(target_df):2d}] {file_name:<14} (ID: {inv_id:2d}) -> {status_badge} "
              f"Status: {pred_status:<17} (Exp: {exp_status:<17}) | Mistake: {primary_pred_mistake:<18} (Exp: {exp_mistake})")

        if not (status_correct and strict_mistake_correct):
            # Diagnose root cause
            reason_parts = []
            if not status_correct:
                reason_parts.append(f"Status mismatch (Expected '{exp_status}' vs Checker '{pred_status}')")
            if not strict_mistake_correct:
                if multilabel_mistake_correct:
                    reason_parts.append(f"Primary label prioritized '{primary_pred_mistake}', but expected '{exp_mistake}' was detected in {pred_mistake_list}")
                else:
                    reason_parts.append(f"Mistake mismatch (Expected '{exp_mistake}' not found in detected {pred_mistake_list})")

            errors.append({
                "invoice_id": inv_id,
                "file_name": file_name,
                "expected": f"({exp_status}, {exp_mistake})",
                "predicted": f"({pred_status}, {primary_pred_mistake})",
                "all_detected": pred_mistake_list,
                "difference_amount": check_res.difference_amount,
                "notes": notes,
                "reason": " | ".join(reason_parts)
            })

        findings_summary = "; ".join(f"{f.check_name}:{f.status}" for f in check_res.findings)

        results_rows.append({
            "invoice_id": inv_id,
            "file_name": file_name,
            "expected_status": exp_status,
            "predicted_status": pred_status,
            "status_match": status_correct,
            "expected_mistake_type": exp_mistake,
            "primary_predicted_mistake": primary_pred_mistake,
            "strict_mistake_match": strict_mistake_correct,
            "multilabel_mistake_match": multilabel_mistake_correct,
            "all_detected_mistakes": json.dumps(pred_mistake_list),
            "difference_amount": check_res.difference_amount,
            "ground_truth_notes": notes,
            "findings_summary": findings_summary
        })

    db.close()

    # Save matching results CSV
    results_df = pd.DataFrame(results_rows)
    results_df.to_csv(out_csv_path, index=False)

    # Compute overall accuracies
    total_eval = len(results_df)
    status_acc = (results_df["status_match"].sum() / total_eval) * 100 if total_eval > 0 else 0.0
    strict_mistake_acc = (results_df["strict_mistake_match"].sum() / total_eval) * 100 if total_eval > 0 else 0.0
    multilabel_mistake_acc = (results_df["multilabel_mistake_match"].sum() / total_eval) * 100 if total_eval > 0 else 0.0

    print("\n" + "=" * 80)
    print("                     3-WAY MATCHING ACCURACY REPORT")
    print("=" * 80)
    print(f"Total Invoices Evaluated:                 {total_eval}")
    print(f"Overall Status Accuracy:                  {results_df['status_match'].sum()}/{total_eval} ({status_acc:.1f}%)")
    print(f"Strict Mistake Accuracy (Primary Match):  {results_df['strict_mistake_match'].sum()}/{total_eval} ({strict_mistake_acc:.1f}%)")
    print(f"Multi-Label Accuracy (Detected in List):  {results_df['multilabel_mistake_match'].sum()}/{total_eval} ({multilabel_mistake_acc:.1f}%)")
    print("-" * 80)

    all_mistake_labels = ["none", "price_mismatch", "quantity_mismatch", "wrong_total", "duplicate_invoice", "missing_po"]

    # 1. STRICT Performance Table
    strict_metrics_table = compute_classification_metrics(expected_mistakes, predicted_primary_mistakes, all_mistake_labels)
    print("\n[1] STRICT PERFORMANCE (Primary Detected Mistake == Expected):")
    print("-" * 80)
    print(f"{'Mistake Type':<22} {'TP':<5} {'FP':<5} {'FN':<5} {'Precision':<12} {'Recall':<12} {'F1':<10}")
    print("-" * 80)
    for _, r in strict_metrics_table.iterrows():
        print(f"{r['Mistake Type']:<22} {r['TP']:<5} {r['FP']:<5} {r['FN']:<5} {r['Precision']:<12} {r['Recall']:<12} {r['F1']:<10}")
    print("-" * 80)

    # 2. MULTI-LABEL Performance Table
    multilabel_metrics_table = compute_multilabel_classification_metrics(expected_mistakes, predicted_all_mistakes, all_mistake_labels)
    print("\n[2] MULTI-LABEL PERFORMANCE (Expected Mistake in All Detected Mistakes):")
    print("-" * 80)
    print(f"{'Mistake Type':<22} {'TP':<5} {'FP':<5} {'FN':<5} {'Precision':<12} {'Recall':<12} {'F1':<10}")
    print("-" * 80)
    for _, r in multilabel_metrics_table.iterrows():
        print(f"{r['Mistake Type']:<22} {r['TP']:<5} {r['FP']:<5} {r['FN']:<5} {r['Precision']:<12} {r['Recall']:<12} {r['F1']:<10}")
    print("-" * 80)

    # Confusion Matrix (Status)
    status_labels = ["verified", "mismatch_detected", "needs_review"]
    print("\nCONFUSION MATRIX (STATUS):")
    print("-" * 80)
    cm_header = f"{'Expected \\ Predicted':<25} " + " ".join(f"{lbl:<18}" for lbl in status_labels)
    print(cm_header)
    print("-" * 80)
    for exp_lbl in status_labels:
        row_counts = []
        for pred_lbl in status_labels:
            cnt = sum(1 for e, p in zip(expected_statuses, predicted_statuses) if e == exp_lbl and p == pred_lbl)
            row_counts.append(f"{cnt:<18}")
        print(f"{exp_lbl:<25} " + " ".join(row_counts))
    print("=" * 80)

    # Discrepancies / Errors
    if errors:
        print(f"\n[ATTENTION] {len(errors)} MISCLASSIFIED INVOICES DETECTED (STRICT CRITERIA):")
        print("=" * 80)
        for err in errors:
            print(f"\nInvoice ID {err['invoice_id']} ({err['file_name']}):")
            print(f"  - Expected:    {err['expected']}")
            print(f"  - Checker:     {err['predicted']} (All detected: {err['all_detected']})")
            print(f"  - Diff Amount: Rs. {err['difference_amount']:,.2f}")
            print(f"  - Description: {err['notes']}")
            print(f"  - Root Cause:  {err['reason']}")
    else:
        print("\nAll evaluated invoices matched ground truth perfectly! Zero misclassifications.")

    print(f"\nDetailed per-invoice results saved to:\n  {out_csv_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate VouchFlow AI 3-Way Matching Engine")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate all 50 regular ground-truth invoices"
    )
    parser.add_argument(
        "--hard",
        action="store_true",
        help="Evaluate 40 hard stress-test cases against hard_ground_truth.csv"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Optional limit on number of invoices to evaluate"
    )
    args = parser.parse_args()

    run_matching_evaluation(eval_all=args.all, count=args.count, is_hard=args.hard)
