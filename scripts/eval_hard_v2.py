"""
VouchFlow AI - Hard Test Cases v2 Evaluation Script
===================================================
Evaluates the 3-Way Matching Engine against the 30 new hard test cases
in data/evaluation/hard_ground_truth_v2.csv.

Computes:
1. Overall Status Accuracy
2. Strict Mistake Accuracy (Primary Match)
3. Multi-Label Accuracy (Detected in List)
4. Per-mistake precision, recall, and F1 for both modes
5. Status confusion matrix
6. Itemized breakdown of any misclassified invoices with root causes.

Saves results to data/evaluation/hard_v2_matching_results.csv.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.database.db import SessionLocal
from backend.tools.matcher import perform_three_way_match
from scripts.run_matching_eval import (
    compute_classification_metrics,
    compute_multilabel_classification_metrics
)


def run_hard_v2_evaluation():
    eval_dir = BASE_DIR / "data" / "evaluation"
    gt_csv_path = eval_dir / "hard_ground_truth_v2.csv"
    out_csv_path = eval_dir / "hard_v2_matching_results.csv"

    if not gt_csv_path.exists():
        print(f"Error: Ground truth file not found at {gt_csv_path}")
        print("Run 'python scripts/generate_hard_cases_v2.py' first.")
        return

    gt_df = pd.read_csv(gt_csv_path)
    db = SessionLocal()

    results_rows = []
    expected_statuses = []
    predicted_statuses = []
    expected_mistakes = []
    predicted_primary_mistakes = []
    predicted_all_mistakes = []
    errors = []

    print("\n" + "=" * 80)
    print("VOUCHFLOW AI - 3-WAY MATCHING HARD TEST SET v2 (30 NEW INVOICES)")
    print("=" * 80)

    for idx, row in gt_df.iterrows():
        inv_id = int(row["invoice_id"])
        file_name = row.get("invoice_file") or f"INV_{inv_id:03d}.pdf"
        exp_status = row["expected_status"]
        exp_mistake = row["expected_mistake"]
        notes = row.get("description") or ""

        # Run 3-way match
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
            badge = "[PASS]"
        elif status_correct and multilabel_mistake_correct:
            badge = "[MULTI]"
        else:
            badge = "[DIFF]"

        print(f"[{len(results_rows) + 1:2d}/{len(gt_df):2d}] {file_name:<14} (ID: {inv_id:3d}) -> {badge} "
              f"Status: {pred_status:<17} (Exp: {exp_status:<17}) | Mistake: {primary_pred_mistake:<18} (Exp: {exp_mistake})")

        if not (status_correct and strict_mistake_correct):
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

    results_df = pd.DataFrame(results_rows)
    results_df.to_csv(out_csv_path, index=False)

    total_eval = len(results_df)
    status_acc = (results_df["status_match"].sum() / total_eval) * 100 if total_eval > 0 else 0.0
    strict_acc = (results_df["strict_mistake_match"].sum() / total_eval) * 100 if total_eval > 0 else 0.0
    multilabel_acc = (results_df["multilabel_mistake_match"].sum() / total_eval) * 100 if total_eval > 0 else 0.0

    print("\n" + "=" * 80)
    print("                     3-WAY MATCHING ACCURACY REPORT (v2)")
    print("=" * 80)
    print(f"Total Invoices Evaluated:                 {total_eval}")
    print(f"Overall Status Accuracy:                  {results_df['status_match'].sum()}/{total_eval} ({status_acc:.1f}%)")
    print(f"Strict Mistake Accuracy (Primary Match):  {results_df['strict_mistake_match'].sum()}/{total_eval} ({strict_acc:.1f}%)")
    print(f"Multi-Label Accuracy (Detected in List):  {results_df['multilabel_mistake_match'].sum()}/{total_eval} ({multilabel_acc:.1f}%)")
    print("-" * 80)

    all_mistake_labels = ["none", "price_mismatch", "quantity_mismatch", "wrong_total", "duplicate_invoice", "missing_po"]

    # Strict performance
    strict_metrics = compute_classification_metrics(expected_mistakes, predicted_primary_mistakes, all_mistake_labels)
    print("\n[1] STRICT PERFORMANCE (Primary Detected Mistake == Expected):")
    print("-" * 80)
    print(f"{'Mistake Type':<22} {'TP':<5} {'FP':<5} {'FN':<5} {'Precision':<12} {'Recall':<12} {'F1':<10}")
    print("-" * 80)
    for _, r in strict_metrics.iterrows():
        print(f"{r['Mistake Type']:<22} {r['TP']:<5} {r['FP']:<5} {r['FN']:<5} {r['Precision']:<12} {r['Recall']:<12} {r['F1']:<10}")
    print("-" * 80)

    # Multi-label performance
    multi_metrics = compute_multilabel_classification_metrics(expected_mistakes, predicted_all_mistakes, all_mistake_labels)
    print("\n[2] MULTI-LABEL PERFORMANCE (Expected Mistake in All Detected Mistakes):")
    print("-" * 80)
    print(f"{'Mistake Type':<22} {'TP':<5} {'FP':<5} {'FN':<5} {'Precision':<12} {'Recall':<12} {'F1':<10}")
    print("-" * 80)
    for _, r in multi_metrics.iterrows():
        print(f"{r['Mistake Type']:<22} {r['TP']:<5} {r['FP']:<5} {r['FN']:<5} {r['Precision']:<12} {r['Recall']:<12} {r['F1']:<10}")
    print("-" * 80)

    # Status Confusion Matrix
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

    if errors:
        print(f"\n[ATTENTION] {len(errors)} MISCLASSIFIED INVOICES DETECTED:")
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
    run_hard_v2_evaluation()
