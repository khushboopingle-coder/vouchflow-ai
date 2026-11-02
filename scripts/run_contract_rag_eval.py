"""Evaluation script for Phase 4: Contract Finder RAG.
Runs a 15-question benchmark once, evaluating:
1. Status accuracy (found, not_found, conflict)
2. Source accuracy (exact matching clause and contract file)
3. Content validity (correct answer / 'I don't know')
Saves full evaluation results to data/evaluation/contract_rag_results.csv.
"""
import sys
from pathlib import Path

# Add repository root to python path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import csv
from typing import List, Dict, Any

from backend.tools.contract_finder import ask_contract, get_vector_store

RESULTS_CSV = Path("data/evaluation/contract_rag_results.csv")

BENCHMARK_QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "Q01",
        "question": "What are the agreed payment terms for Sharma Traders Pvt Ltd?",
        "expected_status": "found",
        "expected_source": "contract_supplier_1.txt, Clause 4",
        "alt_sources": ["contract_supplier_1.txt, Header"],
        "expected_keywords": ["30 days"]
    },
    {
        "id": "Q02",
        "question": "What is the agreed unit price for Standing Desk 120cm from Patel Enterprises?",
        "expected_status": "found",
        "expected_source": "contract_supplier_2.txt, Clause 1",
        "alt_sources": [],
        "expected_keywords": ["12000", "12,000"]
    },
    {
        "id": "Q03",
        "question": "What is the mandatory delivery verification requirement before invoices are approved under Reddy Logistics agreement?",
        "expected_status": "found",
        "expected_source": "contract_supplier_3.txt, Clause 3",
        "alt_sources": [],
        "expected_keywords": ["grn", "goods received note"]
    },
    {
        "id": "Q04",
        "question": "What GST tax rate applies to invoices under Mehta Industrial Solutions contract?",
        "expected_status": "found",
        "expected_source": "contract_supplier_4.txt, Clause 2",
        "alt_sources": [],
        "expected_keywords": ["18%", "gst"]
    },
    {
        "id": "Q05",
        "question": "What is the warranty coverage period for Verma Tech Components hardware?",
        "expected_status": "found",
        "expected_source": "contract_supplier_6.txt, Clause 5",
        "alt_sources": [],
        "expected_keywords": ["24 months"]
    },
    {
        "id": "Q06",
        "question": "What penalty rate applies for delayed deliveries by Gupta Office Essentials?",
        "expected_status": "found",
        "expected_source": "contract_supplier_5.txt, Clause 6",
        "alt_sources": [],
        "expected_keywords": ["2%"]
    },
    {
        "id": "Q07",
        "question": "What early payment cash discount percentage does Singh & Sons Equipment provide?",
        "expected_status": "found",
        "expected_source": "contract_supplier_8.txt, Clause 7",
        "alt_sources": [],
        "expected_keywords": ["3%"]
    },
    {
        "id": "Q08",
        "question": "Where is the legal arbitration venue for disputes with Nair & Company?",
        "expected_status": "found",
        "expected_source": "contract_supplier_7.txt, Clause 8",
        "alt_sources": [],
        "expected_keywords": ["mumbai"]
    },
    {
        "id": "Q09",
        "question": "What is the company policy regarding annual performance bonuses and festival gifts?",
        "expected_status": "not_found",
        "expected_source": "None",
        "alt_sources": [],
        "expected_keywords": ["i don't know"]
    },
    {
        "id": "Q10",
        "question": "Can employees expense weekend personal rides and international hotel upgrades?",
        "expected_status": "not_found",
        "expected_source": "None",
        "alt_sources": [],
        "expected_keywords": ["i don't know"]
    },
    {
        "id": "Q11",
        "question": "What meals are served in the executive dining lounge on Fridays?",
        "expected_status": "not_found",
        "expected_source": "None",
        "alt_sources": [],
        "expected_keywords": ["i don't know"]
    },
    {
        "id": "Q12",
        "question": "What is the agreed unit price for High-Speed USB-C Dock for Sharma Traders?",
        "expected_status": "conflict",
        "expected_source": "contract_supplier_1.txt, Clause 1; contract_supplier_1.txt, Clause 8",
        "alt_sources": [],
        "expected_keywords": ["conflict", "3200", "3500"]
    },
    {
        "id": "Q13",
        "question": "What is the standard warranty duration across equipment supplier contracts?",
        "expected_status": "conflict",
        "expected_source": "Multiple conflicting contracts",
        "alt_sources": [],
        "expected_keywords": ["conflict"]
    },
    {
        "id": "Q14",
        "question": "What is the agreed unit rate for A4 Copier Paper (Box of 5 Reams) from Gupta Office Essentials?",
        "expected_status": "found",
        "expected_source": "contract_supplier_5.txt, Clause 1",
        "alt_sources": [],
        "expected_keywords": ["1100", "1,100"]
    },
    {
        "id": "Q15",
        "question": "How many days does the finance department have to release payment to Singh & Sons Equipment?",
        "expected_status": "found",
        "expected_source": "contract_supplier_8.txt, Clause 4",
        "alt_sources": ["contract_supplier_8.txt, Header"],
        "expected_keywords": ["60 days"]
    }
]


def run_eval():
    print("=" * 80)
    print("VouchFlow AI - Phase 4: Contract Finder RAG Evaluation")
    print("Evaluating 15 Benchmark Questions against 8 Supplier Contracts")
    print("=" * 80)
    
    vs = get_vector_store()
    
    results = []
    correct_count = 0
    wrong_cases = []
    
    for item in BENCHMARK_QUESTIONS:
        qid = item["id"]
        qtext = item["question"]
        exp_status = item["expected_status"]
        exp_source = item["expected_source"]
        alt_sources = item.get("alt_sources", [])
        exp_keywords = item["expected_keywords"]
        
        # Execute query
        res = ask_contract(qtext, vector_store=vs)
        
        actual_status = res["status"]
        actual_source = res["source"]
        actual_answer = res["answer"]
        distance = res.get("distance", 0.0)
        
        # Evaluation checks
        # 1. Status check
        status_match = (actual_status == exp_status)
        
        # 2. Source check
        if exp_status == "not_found":
            source_match = (actual_source is None)
        elif exp_status == "conflict":
            # For conflicts, actual_source is a list of sources or string
            actual_src_str = "; ".join(actual_source) if isinstance(actual_source, list) else str(actual_source)
            if exp_source == "Multiple conflicting contracts":
                source_match = len(res.get("sources", [])) >= 2
            else:
                # Check that both expected sources are present
                exp_parts = [p.strip() for p in exp_source.split(";")]
                source_match = all(any(p in s for s in res.get("sources", [])) for p in exp_parts)
        else:
            # Single source match
            actual_src_str = str(actual_source)
            source_match = (actual_src_str == exp_source or actual_src_str in alt_sources)
            
        # 3. Content keyword check
        ans_lower = actual_answer.lower()
        keyword_match = any(kw.lower() in ans_lower for kw in exp_keywords)
        
        is_correct = status_match and source_match and keyword_match
        if is_correct:
            correct_count += 1
        else:
            reasons = []
            if not status_match:
                reasons.append(f"Status mismatch (exp: {exp_status}, got: {actual_status})")
            if not source_match:
                reasons.append(f"Source mismatch (exp: {exp_source}, got: {actual_source})")
            if not keyword_match:
                reasons.append(f"Keyword missing ({exp_keywords} in answer)")
            wrong_cases.append({
                "id": qid,
                "question": qtext,
                "expected_status": exp_status,
                "actual_status": actual_status,
                "expected_source": exp_source,
                "actual_source": actual_source,
                "answer_snippet": actual_answer[:120],
                "reason": "; ".join(reasons)
            })
            
        res_row = {
            "question_id": qid,
            "question": qtext,
            "expected_status": exp_status,
            "actual_status": actual_status,
            "expected_source": exp_source,
            "actual_source": "; ".join(actual_source) if isinstance(actual_source, list) else str(actual_source),
            "status_match": status_match,
            "source_match": source_match,
            "keyword_match": keyword_match,
            "is_correct": is_correct,
            "distance": distance,
            "answer_preview": actual_answer.replace("\n", " ")[:150]
        }
        results.append(res_row)
        
        icon = "PASS" if is_correct else "FAIL"
        print(f"[{icon}] {qid}: {qtext[:60]}... -> Status: {actual_status} | Source: {actual_source}")

    # Write results CSV
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "question_id", "question", "expected_status", "actual_status",
            "expected_source", "actual_source", "status_match", "source_match",
            "keyword_match", "is_correct", "distance", "answer_preview"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
        
    accuracy = (correct_count / len(BENCHMARK_QUESTIONS)) * 100.0
    print("\n" + "=" * 80)
    print(f"EVALUATION SUMMARY: {correct_count}/{len(BENCHMARK_QUESTIONS)} Correct ({accuracy:.1f}%)")
    print(f"Detailed results saved to: {RESULTS_CSV}")
    print("=" * 80)
    
    if wrong_cases:
        print(f"\nWRONG CASES ({len(wrong_cases)}):")
        for wc in wrong_cases:
            print(f"- {wc['id']}: {wc['question']}")
            print(f"  Reason: {wc['reason']}")
            print(f"  Expected: {wc['expected_status']} | Source: {wc['expected_source']}")
            print(f"  Actual:   {wc['actual_status']} | Source: {wc['actual_source']}")
    else:
        print("\nAll 15 benchmark questions passed cleanly with exact sources and correct status!")

if __name__ == "__main__":
    run_eval()
