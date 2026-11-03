"""
Grounding Guardrail
====================
After the LLM writes an explanation, this module verifies that every
number and clause reference in it actually appears in the structured
evidence (findings + contract citations) the agent collected.

Any unsupported claim is replaced with the tag [unverified] in the cleaned
explanation, and the counts of checked and failed claims are returned for
the report.

Rule: decisions and numbers come from tools; the LLM only writes prose.
      If a number is not in the evidence, it must not appear in the report.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, List, Optional, Set, Tuple

# Statutory GST rates (18% total, 9% CGST / 9% SGST) are allowed even if the
# evidence does not repeat them. Remove this set to make the check stricter.
STATUTORY_CONSTANTS = {18.0, 9.0}


@dataclass
class GroundingResult:
    checked: int
    failed: int
    unverified_claims: List[str]
    cleaned_explanation: str


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# A number such as 1,234.56 or 1234.56 or 15 (never includes a leading dot)
_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# "Rs." / "Rs " / rupee sign right before a number
_PREFIX_RE = re.compile(r"(?:Rs\.?\s*|₹\s*)$", re.IGNORECASE)
# a percent sign right after a number
_PERCENT_RE = re.compile(r"^\s*%")
# Clause 3, Section 4.2 ...
_CLAUSE_RE = re.compile(r"\b(?:Clause|Section|Article|Term)\s+\d+(?:\.\d+)*\b", re.IGNORECASE)
# Identifiers such as INV-2026-0050, PO-HARD-0056, contract_supplier_8
_ID_RE = re.compile(r"\b[A-Za-z]+(?:[-_][A-Za-z0-9]+)+\b")
# ISO dates such as 2026-04-20
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

_EMPTY_VALUES = {"", "none", "not available", "no source found"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_numeric(s: str) -> str:
    """
    Return a clean numeric string (like '12000.00') from text such as
    'Rs. 12,000.00' or '18%'. Returns '' if it is not a valid number.
    """
    cleaned = re.sub(r"^(?:Rs\.?\s*|₹\s*)", "", str(s).strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"[,%\s]", "", cleaned)
    cleaned = cleaned.strip(".")
    if cleaned and re.match(r"^\d+(?:\.\d+)?$", cleaned):
        return cleaned
    return ""


def _to_float(token: str) -> Optional[float]:
    """Safely turn '1,234.50' into 1234.5. Returns None if it is not a number."""
    try:
        return float(token.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _walk(obj: Any, out: Set[str], depth: int = 0) -> None:
    """
    Collect every piece of text and every number found anywhere inside the
    evidence, whatever its shape (dicts, lists, Pydantic models, objects).
    """
    if obj is None or depth > 8:
        return
    if isinstance(obj, bool):
        return
    if isinstance(obj, (str, int, float, Decimal)):
        s = str(obj).strip()
        if s.lower() not in _EMPTY_VALUES:
            out.add(s.lower())
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out, depth + 1)
        return
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            _walk(v, out, depth + 1)
        return
    if hasattr(obj, "model_dump"):
        try:
            _walk(obj.model_dump(), out, depth + 1)
            return
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        _walk(vars(obj), out, depth + 1)


def _collect_evidence_values(findings: List[Any], citations: List[Any]) -> Set[str]:
    """All text found in the findings and the contract citations (lower-case)."""
    corpus: Set[str] = set()
    _walk(findings, corpus)
    _walk(citations, corpus)
    return corpus


def _evidence_numbers(corpus: Set[str]) -> Set[float]:
    """Every number found anywhere in the evidence, rounded to 2 decimals."""
    nums: Set[float] = set(STATUTORY_CONSTANTS)
    for text in corpus:
        for m in _NUM_RE.finditer(text):
            v = _to_float(m.group())
            if v is not None:
                nums.add(round(v, 2))
    return nums


def _ignored_spans(text: str) -> List[Tuple[int, int]]:
    """Parts of the text that are NOT money or quantity claims."""
    spans: List[Tuple[int, int]] = []
    for rx in (_ID_RE, _DATE_RE, _CLAUSE_RE):
        spans.extend(m.span() for m in rx.finditer(text))
    return spans


def _overlaps(start: int, end: int, spans: List[Tuple[int, int]]) -> bool:
    return any(start < e and end > s for s, e in spans)


def _find_numeric_claims(text: str) -> List[Tuple[int, int, str]]:
    """
    Find numeric claims as (start, end, claim_text).
    The claim includes a leading 'Rs.' and a trailing '%' when present.
    """
    ignored = _ignored_spans(text)
    claims: List[Tuple[int, int, str]] = []
    for m in _NUM_RE.finditer(text):
        s, e = m.span()
        if _overlaps(s, e, ignored):
            continue
        if s > 0 and text[s - 1].isalpha():  # e.g. "A4"
            continue
        pre = _PREFIX_RE.search(text[:s])
        start = pre.start() if pre else s
        pct = _PERCENT_RE.match(text[e:])
        end = e + pct.end() if pct else e
        claims.append((start, end, text[start:end]))
    return claims


def _extract_numeric_claims(text: str) -> List[str]:
    return [c for _, _, c in _find_numeric_claims(text)]


def _extract_clause_refs(text: str) -> List[str]:
    return [m.group() for m in _CLAUSE_RE.finditer(text)]


def _is_supported(claim: str, corpus: Set[str], nums: Optional[Set[float]] = None) -> bool:
    """True if the claim (a number or a clause reference) appears in the evidence."""
    if _CLAUSE_RE.fullmatch(claim.strip()):
        norm = " ".join(claim.lower().split())
        blob = " ".join(" ".join(s.split()) for s in corpus)
        return norm in blob

    m = _NUM_RE.search(claim)
    value = _to_float(m.group()) if m else None
    if value is None:
        return False
    if nums is None:
        nums = _evidence_numbers(corpus)
    return round(value, 2) in nums


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ground_check_explanation(
    explanation: str,
    findings: List[Any],
    citations: List[Any],
) -> GroundingResult:
    """
    Verify that every number and clause reference in the explanation is
    supported by the evidence.

    Returns a GroundingResult with:
      checked              number of different claims checked
      failed               number of claims NOT found in the evidence
      unverified_claims    the unsupported claims
      cleaned_explanation  the text with unsupported claims replaced by [unverified]
    """
    corpus = _collect_evidence_values(findings, citations)
    nums = _evidence_numbers(corpus)

    claims: List[Tuple[int, int, str, str]] = []
    for s, e, c in _find_numeric_claims(explanation):
        claims.append((s, e, c, "number"))
    for m in _CLAUSE_RE.finditer(explanation):
        claims.append((m.start(), m.end(), m.group(), "clause"))

    seen = {}
    unverified: List[str] = []
    checked = 0
    failed = 0
    to_replace: List[Tuple[int, int]] = []

    for s, e, claim, kind in claims:
        if kind == "clause":
            key = ("clause", " ".join(claim.lower().split()))
        else:
            m = _NUM_RE.search(claim)
            value = _to_float(m.group()) if m else None
            if value is None:
                continue
            has_percent = "%" in claim
            has_decimal = "." in m.group()
            # tiny whole numbers (1, 2, 3 ...) are too generic to check
            if value < 10 and not has_percent and not has_decimal:
                continue
            key = ("number", round(value, 2), has_percent)

        if key not in seen:
            seen[key] = _is_supported(claim, corpus, nums)
            checked += 1
            if not seen[key]:
                failed += 1
                unverified.append(claim.strip())
        if not seen[key]:
            to_replace.append((s, e))

    cleaned = explanation
    for s, e in sorted(to_replace, reverse=True):
        cleaned = cleaned[:s] + "[unverified]" + cleaned[e:]

    return GroundingResult(
        checked=checked,
        failed=failed,
        unverified_claims=unverified,
        cleaned_explanation=cleaned,
    )