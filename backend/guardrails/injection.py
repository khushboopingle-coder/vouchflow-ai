"""
Injection Detection Guardrail
==============================
Scans invoice content (item names, vendor names, notes, raw text) for
instruction-like patterns that an attacker could embed to hijack the agent.

If detected:
- The payload is ignored (the text is treated as inert DATA, not instructions).
- A warning is added to the report.
- The recommended_next_action is forced to 'needs_human_review'.
- The detection is written to audit_logs by the caller (graph.py).

Rule: invoice content is ALWAYS treated as UNTRUSTED DATA.
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any


# ---------------------------------------------------------------------------
# Injection Pattern Definitions
# ---------------------------------------------------------------------------
# Each tuple: (compiled_regex, human-readable description)
INJECTION_PATTERNS: List[tuple] = [
    # Classic ignore-override patterns
    (re.compile(r"ignore\s+(your\s+)?(previous\s+)?(instructions?|rules?|prompts?)", re.I),
     "Attempt to override instructions: 'ignore your rules / ignore previous instructions'"),

    (re.compile(r"disregard\s+(all\s+)?(previous\s+)?(instructions?|rules?)", re.I),
     "Attempt to disregard rules"),

    (re.compile(r"forget\s+(all\s+)?(previous\s+)?(instructions?|context)", re.I),
     "Attempt to erase context"),

    # Payment / approval manipulation
    (re.compile(r"approve\s+(this\s+)?(invoice|payment|order)", re.I),
     "Instruction to approve invoice or payment"),

    (re.compile(r"send\s+(the\s+)?(payment|money|funds?|transfer)", re.I),
     "Instruction to send payment"),

    (re.compile(r"release\s+(the\s+)?(payment|funds?|money)", re.I),
     "Instruction to release payment"),

    (re.compile(r"mark\s+(this\s+)?(invoice\s+)?as\s+(paid|approved|verified|processed)", re.I),
     "Instruction to mark as paid/approved"),

    (re.compile(r"pay\s+(this|the|immediately|now|directly)", re.I),
     "Instruction to pay immediately"),

    # Role / identity hijacking
    (re.compile(r"you\s+are\s+(now\s+)?(a\s+|an\s+)?(new\s+)?(assistant|agent|finance|bot|ai|system)", re.I),
     "Role hijacking: 'you are now ...'"),

    (re.compile(r"act\s+as\s+(a\s+|an\s+)?(finance|payment|approver|admin|system)", re.I),
     "Role hijacking: 'act as finance/approver/admin'"),

    (re.compile(r"pretend\s+(to\s+be|you\s+are)", re.I),
     "Identity override: 'pretend to be / pretend you are'"),

    # System / override commands
    (re.compile(r"override\s+(all\s+)?(rules?|instructions?|policies?|guardrails?)", re.I),
     "Attempt to override guardrails or policies"),

    (re.compile(r"bypass\s+(all\s+)?(security|guardrails?|checks?|rules?)", re.I),
     "Attempt to bypass security checks"),

    (re.compile(r"system\s*:\s*", re.I),
     "Embedded system-prompt-style prefix 'SYSTEM:'"),

    (re.compile(r"\[INST\]|\[SYS\]|<\|system\|>|<\|im_start\|>", re.I),
     "Embedded prompt-template token (INST/SYS)"),

    # Exfiltration / leak attempts
    (re.compile(r"(print|output|reveal|leak|show)\s+(all\s+)?(your\s+)?(instructions?|system\s+prompt|configuration)", re.I),
     "Attempt to extract system prompt or configuration"),
]


@dataclass
class InjectionResult:
    detected: bool
    matched_patterns: List[str] = field(default_factory=list)
    warning_message: str = ""
    scanned_fields: List[str] = field(default_factory=list)


def _extract_text_fields(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Pull every string-valued field out of a nested dict, up to 2 levels deep.
    Returns {field_path: text_value}.
    """
    results: Dict[str, str] = {}

    def _collect(obj: Any, prefix: str):
        if isinstance(obj, str) and obj.strip():
            results[prefix] = obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _collect(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _collect(item, f"{prefix}[{i}]")

    _collect(data, "")
    return results


def scan_for_injection(
    text: str = "",
    invoice_data: Dict[str, Any] = None,
    extraction_data: Dict[str, Any] = None,
) -> InjectionResult:
    """
    Scan text and/or invoice/extraction data dicts for injection patterns.

    Args:
        text:            A single string to scan (e.g. a notes field).
        invoice_data:    Full invoice dict from the DB.
        extraction_data: Full extraction dict from the DB.

    Returns:
        InjectionResult with detected=True if any pattern matches.
    """
    matched: List[str] = []
    scanned_fields: List[str] = []

    # Build corpus: combine single text with all string fields from dicts
    corpus: Dict[str, str] = {}

    if text and text.strip():
        corpus["text"] = text

    for label, data in [("invoice_data", invoice_data), ("extraction_data", extraction_data)]:
        if data and isinstance(data, dict):
            extracted = _extract_text_fields(data)
            for field_path, field_text in extracted.items():
                corpus[f"{label}.{field_path}"] = field_text

    for field_key, field_value in corpus.items():
        scanned_fields.append(field_key)
        for pattern, description in INJECTION_PATTERNS:
            if pattern.search(field_value):
                entry = f"[{field_key}] {description}"
                if entry not in matched:
                    matched.append(entry)

    detected = len(matched) > 0
    warning = ""
    if detected:
        warning = (
            "⚠️ INJECTION DETECTED: Instruction-like text was found embedded in invoice content. "
            "The content has been treated as inert data and ignored. "
            "This invoice requires manual human review before any action is taken. "
            f"Matched pattern(s): {'; '.join(matched[:5])}"
        )

    return InjectionResult(
        detected=detected,
        matched_patterns=matched,
        warning_message=warning,
        scanned_fields=scanned_fields,
    )

