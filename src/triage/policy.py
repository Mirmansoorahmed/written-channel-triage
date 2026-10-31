"""Step 5: policy gate (R17-R19).

Account-changing actions -- tariff change, cancellation, address change, SEPA
mandate change -- are never executed. They create a pending approval for a human.
Read-only answers (status, information) may proceed.

If the injection detector fired, no action is allowed at all (R15): the request
goes to a human regardless of category.

Input is the chosen category plus the injection verdict, so the gate does not need
the raw text and stays simple and testable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import categories
from .models import InjectionVerdict, PendingApproval, PolicyDecision

# Categories whose fulfilment would change the account.
ACCOUNT_CHANGING = {c.name for c in categories.CATEGORIES if c.account_changing}
# SEPA change is handled as part of these flows; named here for clarity.
ACCOUNT_CHANGING_ACTIONS = {
    "Tarifwechsel": "tariff_change",
    "Kündigung": "cancellation",
    "Umzug": "address_change",
}


def gate(category: str, injection: InjectionVerdict, now: datetime | None = None) -> PolicyDecision:
    """Decide whether an action may proceed (R17-R19, R15)."""
    now = now or datetime.now(timezone.utc)
    ts = now.isoformat()

    if injection.detected:
        return PolicyDecision(
            allowed=False,
            reason="prompt injection detected; no tool use permitted",
            pending_approval=PendingApproval(
                action="blocked_injection",
                reason=injection.reason,
                created_at=ts,
            ),
        )

    if category in ACCOUNT_CHANGING:
        action = ACCOUNT_CHANGING_ACTIONS.get(category, "account_change")
        return PolicyDecision(
            allowed=False,
            reason=f"account-changing request ({category}); created pending approval for a human",
            pending_approval=PendingApproval(
                action=action,
                reason=f"{category} requires human approval; never auto-executed",
                created_at=ts,
            ),
        )

    return PolicyDecision(
        allowed=True,
        reason=f"read-only / informational request ({category}); may proceed",
    )
