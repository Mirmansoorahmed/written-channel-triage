"""Pipeline orchestration (Task 8): wire the steps end to end.

Order (and why): parse -> trust/phishing -> MASK -> classify on masked text ->
injection on masked text -> policy gate -> output + audit. Masking happens before
anything model-facing (R6, R14); the policy gate is the last word on whether an
action may run (R15, R17-R19).
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import audit, classify, ingest, injection, output, pii, policy as policy_mod
from .llm import LLMClient
from .models import Request, Source, TriageResult


def _to_request(raw_text: str, source: Source) -> Request:
    if source == Source.EML:
        return ingest.parse_eml(raw_text)
    return ingest.parse_form(raw_text)


def run(
    raw_text: str,
    source: Source = Source.FORM,
    now: datetime | None = None,
    client: LLMClient | None = None,
    audit_path: str | None = None,
) -> TriageResult:
    now = now or datetime.now(timezone.utc)

    request = _to_request(raw_text, source)

    # Step 1: sender trust + phishing (rule-based, on the raw message).
    trust = ingest.sender_trust(request)
    phishing = ingest.detect_phishing(request)

    # Step 2: mask PII before anything model-facing. Token map stays local.
    masked = pii.mask(request.raw_text)

    # Step 3: classify on the masked text.
    classification = classify.classify(masked.masked_text, client=client)

    # Step 4: injection detector on the masked text.
    inj = injection.detect_injection(masked.masked_text)

    # Step 5: policy gate. Injection => no tool use; account changes => pending.
    policy = policy_mod.gate(classification.category, inj, now=now)

    # Step 6: output + out-of-hours + audit.
    out = output.build_output(trust, phishing, classification, inj, policy, now)

    audit_hash = ""
    if audit_path:
        payload = {
            "ts": now.isoformat(),
            "source": request.source.value,
            "trust": trust.level.value,
            "phishing": phishing.matched_rules,
            "category": classification.category,
            "confidence": classification.confidence,
            "missing_fields": classification.missing_fields,
            "injection": inj.matched_rules,
            "policy_allowed": policy.allowed,
            "pending_action": policy.pending_approval.action if policy.pending_approval else None,
            "queued": out.queued,
        }
        audit_hash = audit.append_entry(audit_path, payload)

    return TriageResult(
        trust=trust,
        phishing=phishing,
        classification=classification,
        injection=inj,
        policy=policy,
        output=out,
        audit_hash=audit_hash,
    )
