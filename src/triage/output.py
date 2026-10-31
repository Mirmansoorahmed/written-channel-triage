"""Step 6 (output): AI disclosure, handoff summary, out-of-hours queue (R20-R22).

- AI disclosure: a short line stating the message was handled by an automated
  system, covering EU AI Act Article 50 transparency (R20).
- Handoff summary: what the human agent needs -- category, fields, trust, flags (R21).
- Hours: outside 07:00-23:00 local the request is queued with an ETA for the next
  opening; it is never silently closed (R22).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .models import (
    Classification,
    InjectionVerdict,
    OutputBundle,
    PhishingVerdict,
    PolicyDecision,
    TrustVerdict,
)

OPEN_HOUR = 7
CLOSE_HOUR = 23

DISCLOSURE = (
    "Hinweis: Diese Nachricht wurde zunächst von einem automatisierten "
    "Triage-System bearbeitet (EU AI Act Art. 50). Eine Person prüft bei Bedarf."
)


def is_out_of_hours(now: datetime) -> bool:
    return not (time(OPEN_HOUR, 0) <= now.time() < time(CLOSE_HOUR, 0))


def next_opening_eta(now: datetime) -> str:
    """ETA string for the next time the desk opens (R22)."""
    if now.time() < time(OPEN_HOUR, 0):
        opening = now.replace(hour=OPEN_HOUR, minute=0, second=0, microsecond=0)
    else:
        nxt = now + timedelta(days=1)
        opening = nxt.replace(hour=OPEN_HOUR, minute=0, second=0, microsecond=0)
    return opening.isoformat()


def build_handoff(
    trust: TrustVerdict,
    phishing: PhishingVerdict,
    classification: Classification,
    injection: InjectionVerdict,
    policy: PolicyDecision,
) -> str:
    """Compact, explainable summary for the human agent (R21)."""
    flags = []
    if phishing.suspected:
        flags.append(f"phishing({','.join(phishing.matched_rules)})")
    if injection.detected:
        flags.append(f"injection({','.join(injection.matched_rules)})")
    if classification.missing_fields:
        flags.append("missing:" + ",".join(classification.missing_fields))
    if policy.pending_approval:
        flags.append(f"pending:{policy.pending_approval.action}")

    lines = [
        f"Kategorie: {classification.category} (Konfidenz {classification.confidence})",
        f"Sender-Trust: {trust.level.value} -- {trust.reason}",
        f"Felder: {classification.fields or '-'}",
        f"Policy: {'erlaubt' if policy.allowed else 'nicht erlaubt'} -- {policy.reason}",
        f"Flags: {', '.join(flags) if flags else '-'}",
    ]
    return "\n".join(lines)


def build_output(
    trust: TrustVerdict,
    phishing: PhishingVerdict,
    classification: Classification,
    injection: InjectionVerdict,
    policy: PolicyDecision,
    now: datetime,
) -> OutputBundle:
    handoff = build_handoff(trust, phishing, classification, injection, policy)
    if is_out_of_hours(now):
        return OutputBundle(
            disclosure=DISCLOSURE,
            handoff_summary=handoff,
            queued=True,
            eta=next_opening_eta(now),
        )
    return OutputBundle(disclosure=DISCLOSURE, handoff_summary=handoff, queued=False)
