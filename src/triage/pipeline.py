"""Pipeline orchestration (Task 8): wire the steps end to end.

Order (and why): parse -> trust/phishing -> MASK -> classify on masked text ->
injection on masked text -> policy gate -> output + audit. Masking happens before
anything model-facing (R6, R14); the policy gate is the last word on whether an
action may run (R15, R17-R19).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from . import audit, classify, ingest, injection, observability as obs
from . import output, pii, policy as policy_mod
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
    retriever=None,
) -> TriageResult:
    now = now or datetime.now(timezone.utc)
    _t0 = time.perf_counter()

    request = _to_request(raw_text, source)

    # Step 1: sender trust + phishing (rule-based, on the raw message).
    trust = ingest.sender_trust(request)
    phishing = ingest.detect_phishing(request)

    # Step 2: mask PII before anything model-facing. Token map stays local.
    masked = pii.mask(request.raw_text)

    # Step 3: classify on the masked text. `retriever` (when supplied) swaps the
    # v1 regex retrieval for embeddings; `client` can be a real SLM (V4).
    classification = classify.classify(masked.masked_text, client=client, retriever=retriever)

    # Step 4: injection detector on the masked text (normalised first; optional
    # embedding-similarity check when a retriever is supplied) (V18-V20).
    inj = injection.detect_injection(masked.masked_text, retriever=retriever)

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

    # Observability (review fix #5): increment the metrics the architecture doc
    # names, and emit one structured log line. No raw PII is passed here.
    latency_ms = (time.perf_counter() - _t0) * 1000.0
    slm_fallback = getattr(client, "last_fallback", None) if client is not None else None
    pii_leak_blocked = "blocked raw PII" in (classification.reason or "")
    obs.inc("triage_requests_total", source=request.source.value,
            category=classification.category)
    if inj.detected:
        obs.inc("triage_injection_detected_total")
    if phishing.suspected:
        obs.inc("triage_phishing_suspected_total")
    if policy.pending_approval is not None:
        obs.inc("triage_policy_blocked_total")
    if slm_fallback:
        obs.inc("triage_slm_fallback_total")
    if pii_leak_blocked:
        obs.inc("triage_pii_leak_blocked_total")
    obs.observe("triage_request_latency_ms", latency_ms)
    obs.log_event(
        "triage",
        source=request.source.value,
        trust=trust.level.value,
        category=classification.category,
        confidence=classification.confidence,
        injection=inj.matched_rules,
        phishing=phishing.matched_rules,
        policy_allowed=policy.allowed,
        queued=out.queued,
        slm_fallback=slm_fallback,
        latency_ms=round(latency_ms, 3),
    )

    return TriageResult(
        trust=trust,
        phishing=phishing,
        classification=classification,
        injection=inj,
        policy=policy,
        output=out,
        audit_hash=audit_hash,
    )
