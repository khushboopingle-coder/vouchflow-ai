"""
Permissions Guardrail
=====================
Policy table that governs which actions the Investigation Agent is allowed
to perform automatically, which require human approval, and which are
restricted to authorised humans only.

Rules:
- The Investigation Agent may NEVER approve an invoice or release a payment.
- Decisions and numbers come from existing tools only.
- Any attempt to call a tool outside the allowed list is blocked and logged.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict
from enum import Enum


class PolicyLevel(str, Enum):
    AUTOMATIC = "automatic"               # Agent may call without any approval
    NEEDS_HUMAN_APPROVAL = "needs_human_approval"  # Must obtain finance-staff sign-off first
    AUTHORIZED_HUMAN_ONLY = "authorized_human_only"  # Restricted to named human roles; agent blocked


@dataclass
class PermissionResult:
    action: str
    allowed: bool
    policy_level: PolicyLevel
    reason: str
    blocked: bool = False
    logged_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# Policy Table
# ---------------------------------------------------------------------------
# Format: action_name -> (PolicyLevel, human-readable reason)
POLICY_TABLE: Dict[str, tuple] = {
    # ---------- read-only data tools (always automatic) ----------
    "read_invoice":       (PolicyLevel.AUTOMATIC,             "Reading invoice data is a safe, read-only operation."),
    "get_invoice":        (PolicyLevel.AUTOMATIC,             "Reading invoice data is a safe, read-only operation."),
    "get_extraction":     (PolicyLevel.AUTOMATIC,             "Reading extraction data is a safe, read-only operation."),
    "run_matcher":        (PolicyLevel.AUTOMATIC,             "Running the deterministic matcher is a safe, read-only operation."),
    "get_po_and_grn":     (PolicyLevel.AUTOMATIC,             "Fetching PO and GRN records is a safe, read-only operation."),
    "search_contract":    (PolicyLevel.AUTOMATIC,             "Searching contract clauses via RAG is a safe, read-only operation."),
    "fetch_po_and_grn":   (PolicyLevel.AUTOMATIC,             "Fetching PO and GRN records is a safe, read-only operation."),

    # ---------- write/report operations (automatic for agent) ----------
    "write_report":       (PolicyLevel.AUTOMATIC,             "Writing an investigation report is within the agent's mandate."),
    "draft_email":        (PolicyLevel.AUTOMATIC,             "Drafting an email for review is within the agent's mandate."),

    # ---------- actions requiring human approval ----------
    "send_email":         (PolicyLevel.NEEDS_HUMAN_APPROVAL,  "Sending an external email requires explicit finance-staff approval."),
    "approve_invoice":    (PolicyLevel.AUTHORIZED_HUMAN_ONLY, "Approving invoices is restricted to authorised finance personnel only."),
    "release_payment":    (PolicyLevel.AUTHORIZED_HUMAN_ONLY, "Releasing payments is restricted to authorised finance personnel only."),
    "mark_as_paid":       (PolicyLevel.AUTHORIZED_HUMAN_ONLY, "Marking invoices as paid is restricted to authorised finance personnel only."),
    "delete_invoice":     (PolicyLevel.AUTHORIZED_HUMAN_ONLY, "Deleting invoices is restricted to authorised personnel only."),
    "modify_invoice":     (PolicyLevel.AUTHORIZED_HUMAN_ONLY, "Modifying invoice data is restricted to authorised personnel only."),
}

# Tools the investigation_agent role is explicitly allowed to call
AGENT_ALLOWED_TOOLS: List[str] = [
    "read_invoice",
    "get_invoice",
    "get_extraction",
    "run_matcher",
    "get_po_and_grn",
    "fetch_po_and_grn",
    "search_contract",
    "write_report",
    "draft_email",
]


def check_permission(action: str, caller: str = "investigation_agent") -> PermissionResult:
    """
    Check whether a given action is permitted for the caller.

    Returns a PermissionResult with .allowed and .blocked set.
    Always call this before performing any action in the agent.
    The result should be written to audit_logs by the caller.
    """
    policy_entry = POLICY_TABLE.get(action)

    if policy_entry is None:
        # Unknown / unregistered action — deny by default (fail-safe)
        return PermissionResult(
            action=action,
            allowed=False,
            policy_level=PolicyLevel.AUTHORIZED_HUMAN_ONLY,
            reason=f"Action '{action}' is not registered in the policy table. Denied by default (fail-safe).",
            blocked=True,
        )

    level, reason = policy_entry

    if level == PolicyLevel.AUTOMATIC:
        return PermissionResult(
            action=action,
            allowed=True,
            policy_level=level,
            reason=reason,
            blocked=False,
        )

    elif level == PolicyLevel.NEEDS_HUMAN_APPROVAL:
        return PermissionResult(
            action=action,
            allowed=False,
            policy_level=level,
            reason=f"BLOCKED: {reason}",
            blocked=True,
        )

    else:  # AUTHORIZED_HUMAN_ONLY
        return PermissionResult(
            action=action,
            allowed=False,
            policy_level=level,
            reason=f"BLOCKED: {reason} The Investigation Agent is not authorised for this action.",
            blocked=True,
        )


def get_allowed_tools(role: str = "investigation_agent") -> List[str]:
    """Return the list of tool names the given role may call automatically."""
    # Currently only one agent role is defined
    return list(AGENT_ALLOWED_TOOLS)

