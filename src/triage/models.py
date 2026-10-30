"""Shared data models for the triage pipeline.

Every verdict carries a human-readable reason so decisions are explainable (N2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Source(str, Enum):
    EML = "eml"
    FORM = "form"


class TrustLevel(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass
class Request:
    """One incoming written message."""

    source: Source
    raw_text: str
    subject: str = ""
    sender: str = ""
    # Raw Authentication-Results header value, if any.
    auth_results: str = ""


@dataclass
class TrustVerdict:
    """Sender-trust decision from the ingest step."""

    level: TrustLevel
    reason: str
    spf: str = "none"
    dkim: str = "none"
    dmarc: str = "none"


@dataclass
class PhishingVerdict:
    """Explainable phishing decision."""

    suspected: bool
    reason: str
    matched_rules: list[str] = field(default_factory=list)


@dataclass
class Classification:
    """Category plus extracted fields for a request."""

    category: str
    confidence: float
    fields: dict[str, str] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class InjectionVerdict:
    """Prompt-injection decision on the masked text."""

    detected: bool
    reason: str
    matched_rules: list[str] = field(default_factory=list)


@dataclass
class PendingApproval:
    """A risky action parked for a human. Never auto-executed."""

    action: str
    reason: str
    created_at: str


@dataclass
class PolicyDecision:
    """Outcome of the policy gate."""

    allowed: bool
    reason: str
    pending_approval: Optional[PendingApproval] = None


@dataclass
class OutputBundle:
    """What we hand to the human / return to the caller."""

    disclosure: str
    handoff_summary: str
    queued: bool = False
    eta: str = ""


@dataclass
class TriageResult:
    """End-to-end result for one request."""

    trust: TrustVerdict
    phishing: PhishingVerdict
    classification: Classification
    injection: InjectionVerdict
    policy: PolicyDecision
    output: OutputBundle
    audit_hash: str = ""
