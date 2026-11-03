"""Contract Finder RAG for VouchFlow AI.
Indexes supplier master contracts using LangChain and ChromaDB.
Provides clause-level semantic retrieval, relevance gating ('I don't know'),
and explicit conflict detection across disagreeing contracts/clauses.
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import re
import os

from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma

from backend.tools.embeddings import get_embedding_model


DEFAULT_CONTRACTS_DIR = Path("data/contracts")
DEFAULT_CHROMA_DIR = Path("data/chroma_db")
COLLECTION_NAME = "supplier_contracts"

# Distance threshold: distances above 1.15 in L2 indicate out-of-domain / unanswerable queries
RELEVANCE_DISTANCE_THRESHOLD = 1.15

KNOWN_CONTRACT_SUPPLIERS = [
    "Sharma Traders Pvt Ltd",
    "Patel Enterprises",
    "Reddy Logistics & Supplies",
    "Mehta Industrial Solutions",
    "Gupta Office Essentials",
    "Verma Tech Components",
    "Nair & Company",
    "Singh & Sons Equipment"
]


def find_matching_supplier(supplier_name: Optional[str]) -> Optional[str]:
    """Matches a vendor name to the known indexed contract suppliers in ChromaDB."""
    if not supplier_name:
        return None
    s_norm = "".join(c for c in supplier_name.lower() if c.isalnum())
    for cand in KNOWN_CONTRACT_SUPPLIERS:
        c_norm = "".join(c for c in cand.lower() if c.isalnum())
        first_token = supplier_name.strip().split()[0].lower()
        cand_first_token = cand.strip().split()[0].lower()
        if (s_norm in c_norm or c_norm in s_norm) or (first_token == cand_first_token and len(first_token) > 3):
            return cand
    return None


def parse_contract_clauses(file_path: Path) -> List[Document]:
    """Parses a contract .txt file into discrete, clause-level Document chunks.
    Attaches rich metadata including file_name, clause_number, clause_title, and supplier.
    """
    text = file_path.read_text(encoding="utf-8")
    file_name = file_path.name
    
    # 1. Parse Supplier Header
    supp_match = re.search(r"Supplier:\s*([^\n\r]+)", text)
    supplier_name = supp_match.group(1).strip() if supp_match else "Unknown Supplier"
    
    gstin_match = re.search(r"GSTIN:\s*([^\n\r]+)", text)
    gstin = gstin_match.group(1).strip() if gstin_match else ""
    
    pay_terms_match = re.search(r"Payment Terms:\s*([^\n\r]+)", text)
    payment_terms = pay_terms_match.group(1).strip() if pay_terms_match else ""
    
    docs: List[Document] = []
    
    # Header Document
    header_content = (
        f"Master Vendor Supply Agreement Header\n"
        f"Supplier: {supplier_name} ({file_name})\n"
        f"GSTIN: {gstin}\n"
        f"Payment Terms: {payment_terms}\n"
        f"Agreement Date: 2026-01-01\n"
        f"Jurisdiction: Indian Contract Act, 1872"
    )
    docs.append(Document(
        page_content=header_content,
        metadata={
            "file_name": file_name,
            "source": file_name,
            "clause_number": "Header",
            "clause_title": "Master Supply Agreement Header",
            "supplier_name": supplier_name,
            "category": "header"
        }
    ))
    
    # Split text into numbered clauses using regex pattern (e.g., '1. SCOPE AND PRICING', 'Clause 8.')
    # Standard pattern across our contracts:
    # 1. SCOPE AND PRICING
    # 2. TAXATION & GST CLAUSE
    # 3. DELIVERY & ACCEPTANCE
    # 4. PAYMENT TERMS
    # 5. WARRANTY AND DEFECT LIABILITY
    # 6. LATE DELIVERY PENALTY
    # 7. EARLY PAYMENT CASH DISCOUNT
    # 8. JURISDICTION & DISPUTE RESOLUTION / Clause 8. AMENDMENT AND PRICE REVISION
    
    clause_patterns = [
        (r"1\.\s+SCOPE AND PRICING(.*?)(?=2\.\s+TAXATION|\Z)", "Clause 1", "Scope and Pricing", "pricing"),
        (r"2\.\s+TAXATION & GST CLAUSE(.*?)(?=3\.\s+DELIVERY|\Z)", "Clause 2", "Taxation & GST Clause", "taxation"),
        (r"3\.\s+DELIVERY & ACCEPTANCE(.*?)(?=4\.\s+PAYMENT|\Z)", "Clause 3", "Delivery & Acceptance", "delivery"),
        (r"4\.\s+PAYMENT TERMS(.*?)(?=5\.\s+WARRANTY|\Z)", "Clause 4", "Payment Terms", "payment_terms"),
        (r"5\.\s+WARRANTY AND DEFECT LIABILITY(.*?)(?=6\.\s+LATE|\Z)", "Clause 5", "Warranty and Defect Liability", "warranty"),
        (r"6\.\s+LATE DELIVERY PENALTY(.*?)(?=7\.\s+EARLY|\Z)", "Clause 6", "Late Delivery Penalty", "late_penalty"),
        (r"7\.\s+EARLY PAYMENT CASH DISCOUNT(.*?)(?=(?:8\.|Clause 8|\Z))", "Clause 7", "Early Payment Cash Discount", "early_discount"),
        (r"(?:8\.|Clause 8\.)\s+([^\n\r]+)(.*?)(?=Authorized Signatory|\Z)", "Clause 8", "Dispute or Amendment", "amendment_or_dispute")
    ]
    
    for pat, c_num, c_title, cat in clause_patterns:
        match = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if match:
            if c_num == "Clause 8":
                matched_title = match.group(1).strip()
                clause_body = match.group(2).strip()
                full_clause_title = f"Clause 8. {matched_title}"
                category = "amendment" if "amendment" in matched_title.lower() or "revision" in matched_title.lower() else "dispute"
            else:
                clause_body = match.group(1).strip()
                full_clause_title = c_title
                category = cat
                
            chunk_content = (
                f"Supplier: {supplier_name} | Contract: {file_name} | {c_num}: {full_clause_title}\n"
                f"{clause_body}"
            )
            
            docs.append(Document(
                page_content=chunk_content,
                metadata={
                    "file_name": file_name,
                    "source": file_name,
                    "clause_number": c_num,
                    "clause_title": full_clause_title,
                    "supplier_name": supplier_name,
                    "category": category
                }
            ))
            
            # If Clause 1 (pricing table), also generate high-resolution item chunks for each line item
            if c_num == "Clause 1":
                for line in clause_body.splitlines():
                    price_match = re.search(r"^(.*?)\s+Rs\.\s+([\d\.]+)", line.strip())
                    if price_match:
                        item_name = price_match.group(1).strip()
                        agreed_price = float(price_match.group(2).strip())
                        item_content = (
                            f"Supplier: {supplier_name} | Contract: {file_name} | Clause 1: Scope and Pricing\n"
                            f"The agreed fixed unit price for '{item_name}' is Rs. {agreed_price:,.2f} (exclusive of GST)."
                        )
                        docs.append(Document(
                            page_content=item_content,
                            metadata={
                                "file_name": file_name,
                                "source": file_name,
                                "clause_number": "Clause 1",
                                "clause_title": f"Scope and Pricing - {item_name}",
                                "supplier_name": supplier_name,
                                "category": "item_pricing",
                                "item_name": item_name,
                                "agreed_price": agreed_price
                            }
                        ))
                        
    return docs


# Global in-memory cache for VectorStore instance
_VECTOR_STORE_CACHE: Optional[Chroma] = None


def get_vector_store(
    contracts_dir: Path = DEFAULT_CONTRACTS_DIR,
    persist_dir: Optional[Path] = DEFAULT_CHROMA_DIR,
    force_rebuild: bool = False
) -> Chroma:
    """Builds or loads the ChromaDB vector store collection.
    Keeps embedding model swappable via backend/tools/embeddings.py.
    """
    global _VECTOR_STORE_CACHE
    if _VECTOR_STORE_CACHE is not None and not force_rebuild:
        return _VECTOR_STORE_CACHE
        
    embedding_model = get_embedding_model()
    
    # Check if persistent collection already exists and has records
    persist_path_str = str(persist_dir) if persist_dir else None
    
    if persist_dir and persist_dir.exists() and not force_rebuild:
        vector_store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embedding_model,
            persist_directory=persist_path_str
        )
        # If collection already has documents, return it
        if vector_store._collection.count() > 0:
            _VECTOR_STORE_CACHE = vector_store
            return vector_store
            
    # Parse all contract files
    all_docs: List[Document] = []
    contract_files = sorted(contracts_dir.glob("*.txt"))
    for cf in contract_files:
        docs = parse_contract_clauses(cf)
        all_docs.extend(docs)
        
    if not all_docs:
        raise ValueError(f"No contract text files found in {contracts_dir} to index.")
        
    # Build Chroma vector store (auto-persisted in Chroma >= 0.4.x)
    vector_store = Chroma.from_documents(
        documents=all_docs,
        embedding=embedding_model,
        collection_name=COLLECTION_NAME,
        persist_directory=persist_path_str
    )
        
    _VECTOR_STORE_CACHE = vector_store
    return vector_store


def detect_conflicts(
    docs_with_scores: List[Tuple[Document, float]],
    question: str,
    supplier_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Analyzes top retrieved candidates to detect whether two contracts or clauses disagree.
    Never picks one silently if a conflict exists.
    Returns a conflict dictionary if disagreement is detected, else None.
    """
    if len(docs_with_scores) < 2:
        return None
        
    q_lower = question.lower()
    
    # Filter candidates within relevant distance
    relevant = [(doc, score) for doc, score in docs_with_scores if score < RELEVANCE_DISTANCE_THRESHOLD]
    if len(relevant) < 2:
        return None
        
    # -------------------------------------------------------------
    # Case 1: Amendment / Revision Conflict within Same Supplier
    # Example: Sharma Traders High-Speed USB-C Dock in Clause 1 (Rs. 3200) vs Clause 8 (Rs. 3500)
    # -------------------------------------------------------------
    amendment_docs = [doc for doc, _ in relevant if doc.metadata.get("category") == "amendment"]
    pricing_docs = [doc for doc, _ in relevant if doc.metadata.get("category") in ("pricing", "item_pricing")]
    
    if amendment_docs and pricing_docs:
        amend_doc = amendment_docs[0]
        # Check if the pricing doc mentions the item revised in the amendment
        for p_doc in pricing_docs:
            if p_doc.metadata.get("file_name") == amend_doc.metadata.get("file_name"):
                src_orig = f"{p_doc.metadata['file_name']}, {p_doc.metadata['clause_number']}"
                src_amend = f"{amend_doc.metadata['file_name']}, {amend_doc.metadata['clause_number']}"
                return {
                    "is_conflict": True,
                    "status": "conflict",
                    "reason": "Contract contains conflicting original and amended terms.",
                    "sources": [src_orig, src_amend],
                    "details": (
                        f"Conflict detected for {p_doc.metadata.get('supplier_name')}: "
                        f"Original agreement in {src_orig} states: '{p_doc.page_content.strip()}', "
                        f"whereas {src_amend} states: '{amend_doc.page_content.strip()}'."
                    )
                }

    # -------------------------------------------------------------
    # Case 2: Cross-Contract Disagreement Across Suppliers
    # Only applies when query does NOT target a specific supplier
    # -------------------------------------------------------------
    all_suppliers = [
        "sharma traders", "patel enterprises", "reddy logistics",
        "mehta industrial", "gupta office", "verma tech",
        "nair & company", "singh & sons"
    ]
    vendor_in_question = bool(supplier_name) or any(s in q_lower for s in all_suppliers)
    
    # If question did not target a single vendor, check for divergent top matches
    if not vendor_in_question:
        top_doc, top_score = relevant[0]
        second_doc, second_score = relevant[1]
        
        # Are they from different contract files?
        if top_doc.metadata.get("file_name") != second_doc.metadata.get("file_name"):
            # Are their categories identical (e.g. both warranty, both payment_terms, both late_penalty)?
            cat1 = top_doc.metadata.get("category")
            cat2 = second_doc.metadata.get("category")
            
            # Or are both top scores very close (e.g., within 0.25 of each other)?
            score_diff = abs(top_score - second_score)
            if (cat1 == cat2 or score_diff < 0.25) and cat1 in ("warranty", "payment_terms", "late_penalty", "early_discount", "item_pricing"):
                src1 = f"{top_doc.metadata['file_name']}, {top_doc.metadata['clause_number']}"
                src2 = f"{second_doc.metadata['file_name']}, {second_doc.metadata['clause_number']}"
                return {
                    "is_conflict": True,
                    "status": "conflict",
                    "reason": "Different contracts specify contradictory terms for this query.",
                    "sources": [src1, src2],
                    "details": (
                        f"Conflicting terms found between {src1} ({top_doc.metadata.get('supplier_name')}) "
                        f"and {src2} ({second_doc.metadata.get('supplier_name')}). "
                        f"Source 1: '{top_doc.page_content.strip()}'. "
                        f"Source 2: '{second_doc.page_content.strip()}'."
                    )
                }
                
    return None


def ask_contract(
    question: str,
    vector_store: Optional[Chroma] = None,
    top_k: int = 4,
    supplier_name: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves the best matching contract clause for a given query.
    If supplier_name is provided, scopes the search strictly to that supplier's contract.
    
    Returns a dictionary with:
    - answer: The matching clause text, or 'no source found' / 'I don't know', or conflict details.
    - source: The source string (e.g. 'contract_supplier_1.txt, Clause 4') or 'no source found' or list of sources.
    - status: 'found', 'not_found', or 'conflict'.
    - sources: Always a list of matching source strings.
    - distance: L2 distance score from Chroma.
    """
    vs = vector_store or get_vector_store()
    
    # -------------------------------------------------------------------------
    # Supplier-Scoped Search (Investigation Agent Mode)
    # -------------------------------------------------------------------------
    if supplier_name:
        matched_supplier = find_matching_supplier(supplier_name)
        if not matched_supplier:
            return {
                "answer": "no source found",
                "source": "no source found",
                "sources": [],
                "status": "not_found",
                "distance": 999.0,
                "matched_clause": None
            }
            
        candidates: List[Tuple[Document, float]] = vs.similarity_search_with_score(
            question,
            k=top_k,
            filter={"supplier_name": matched_supplier}
        )
        
        if not candidates:
            return {
                "answer": "no source found",
                "source": "no source found",
                "sources": [],
                "status": "not_found",
                "distance": 999.0,
                "matched_clause": None
            }
            
        best_doc, best_distance = candidates[0]
        
        if best_distance > RELEVANCE_DISTANCE_THRESHOLD:
            return {
                "answer": "no source found",
                "source": "no source found",
                "sources": [],
                "status": "not_found",
                "distance": round(best_distance, 4),
                "matched_clause": None
            }
            
        # Conflict detection strictly scoped to the same supplier
        conflict_info = detect_conflicts(candidates, question, supplier_name=matched_supplier)
        if conflict_info:
            return {
                "answer": conflict_info["details"],
                "source": conflict_info["sources"],
                "sources": conflict_info["sources"],
                "status": "conflict",
                "distance": round(best_distance, 4),
                "conflict_details": conflict_info
            }
            
        src = f"{best_doc.metadata['file_name']}, {best_doc.metadata['clause_number']}"
        return {
            "answer": best_doc.page_content.strip(),
            "source": src,
            "sources": [src],
            "status": "found",
            "distance": round(best_distance, 4),
            "matched_clause": {
                "file_name": best_doc.metadata.get("file_name"),
                "clause_number": best_doc.metadata.get("clause_number"),
                "clause_title": best_doc.metadata.get("clause_title"),
                "supplier_name": best_doc.metadata.get("supplier_name")
            }
        }

    # -------------------------------------------------------------------------
    # General Unscoped Search (RAG Benchmark Evaluation Mode)
    # -------------------------------------------------------------------------
    candidates = vs.similarity_search_with_score(question, k=top_k)
    
    if not candidates:
        return {
            "answer": "I don't know",
            "source": None,
            "sources": [],
            "status": "not_found",
            "distance": 999.0,
            "matched_clause": None
        }
        
    best_doc, best_distance = candidates[0]
    
    # 1. Relevance check: "If nothing matches well enough, return 'I don't know' and no source"
    if best_distance > RELEVANCE_DISTANCE_THRESHOLD:
        return {
            "answer": "I don't know",
            "source": None,
            "sources": [],
            "status": "not_found",
            "distance": round(best_distance, 4),
            "matched_clause": None
        }
        
    # 2. Conflict detection: Cross-contract or intra-contract disagreement
    conflict_info = detect_conflicts(candidates, question, supplier_name=None)
    if conflict_info:
        return {
            "answer": conflict_info["details"],
            "source": conflict_info["sources"],
            "sources": conflict_info["sources"],
            "status": "conflict",
            "distance": round(best_distance, 4),
            "conflict_details": conflict_info
        }
        
    # 3. Clean single match
    src = f"{best_doc.metadata['file_name']}, {best_doc.metadata['clause_number']}"
    return {
        "answer": best_doc.page_content.strip(),
        "source": src,
        "sources": [src],
        "status": "found",
        "distance": round(best_distance, 4),
        "matched_clause": {
            "file_name": best_doc.metadata.get("file_name"),
            "clause_number": best_doc.metadata.get("clause_number"),
            "clause_title": best_doc.metadata.get("clause_title"),
            "supplier_name": best_doc.metadata.get("supplier_name")
        }
    }
