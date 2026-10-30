"""Step 4: prompt-injection detector (R14-R16).

Runs on the MASKED text, because that is exactly what the model would see (R14).
Rule-based and explainable: it records which pattern matched. On a hit, the
pipeline performs no tool use for that request (enforced by the policy gate).

Patterns cover both common English jailbreak phrasing and German equivalents,
since written customer support receives both.
"""

from __future__ import annotations

import re

from .models import InjectionVerdict

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_previous", re.compile(
        r"ignor\w*\s+(all\s+)?(previous|prior|above|die\s+(vorherigen|obigen))\s+"
        r"(instructions?|anweisungen|regeln)", re.IGNORECASE)),
    ("override_system", re.compile(
        r"(system\s*prompt|du bist jetzt|you are now|act as|handle als|vergiss)\b", re.IGNORECASE)),
    ("reveal_instructions", re.compile(
        r"(zeig|gib|print|reveal|repeat)\w*\s+(mir\s+)?(deine|your|the)\s+"
        r"(instructions?|anweisungen|system\s*prompt|regeln)", re.IGNORECASE)),
    ("role_escalation", re.compile(
        r"(entwickler|developer|admin|root)\s*modus|developer mode|dan mode", re.IGNORECASE)),
    ("exfil_or_tooling", re.compile(
        r"(fetch|curl|wget|execute|run)\s+\S+|führe\s+.{0,20}\s+aus|API[-\s]?key", re.IGNORECASE)),
    ("fake_delimiter", re.compile(
        r"(-{3,}\s*(end|ende|system|user)\s*-{3,})|<\s*/?\s*(system|instructions?)\s*>", re.IGNORECASE)),
]


def detect_injection(masked_text: str) -> InjectionVerdict:
    """Detect prompt-injection attempts on the masked text (R14-R16)."""
    matched = [name for name, rx in _PATTERNS if rx.search(masked_text)]
    if matched:
        return InjectionVerdict(
            detected=True,
            reason="matched injection pattern(s): " + ", ".join(matched),
            matched_rules=matched,
        )
    return InjectionVerdict(detected=False, reason="no injection pattern matched")
