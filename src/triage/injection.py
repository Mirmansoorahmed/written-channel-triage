"""Step 4: prompt-injection detector (R14-R16, V18-V20).

Runs on the MASKED text, because that is exactly what the model would see (R14).
Rule-based and explainable: it records which pattern matched. On a hit, the
pipeline performs no tool use for that request (enforced by the policy gate).

v2 hardening (closes the two misses v1's larger eval exposed):
  * Normalise first (normalize.py): NFKC, strip invisibles, fold homoglyphs,
    collapse single-letter spacing. So `I G N O R E all previous instructions`
    and Cyrillic lookalikes no longer slip past contiguous-phrasing regexes.
  * Add a "repeat/verbatim/print your instructions" pattern for the v1 miss
    `repeat the above instructions ... then ignore them`.
  * Decode short base64 tokens and re-scan the decoded text, since an attacker can
    wrap the payload in base64 with a "decode and follow" carrier.
  * Optional embedding-similarity check (V20): when a retriever with injection
    exemplars is supplied, flag text that sits close to a known attack. No-op when
    no retriever is given, so the default offline path is unchanged.

Patterns cover both English jailbreak phrasing and German equivalents, since
written customer support receives both.
"""

from __future__ import annotations

import base64
import binascii
import re

from .models import InjectionVerdict
from .normalize import normalize

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_previous", re.compile(
        r"ignor\w*\s+(all\s+)?(previous|prior|above|die\s+(vorherigen|obigen))\s+"
        r"(instructions?|anweisungen|regeln)", re.IGNORECASE)),
    ("override_system", re.compile(
        r"(system\s*prompt|du bist jetzt|you are now|act as|handle als|vergiss)\b", re.IGNORECASE)),
    ("reveal_instructions", re.compile(
        r"(zeig|gib|print|reveal|repeat)\w*\s+(mir\s+)?(deine|your|the)\s+"
        r"(instructions?|anweisungen|system\s*prompt|regeln)", re.IGNORECASE)),
    # V19: "repeat/verbatim/print the above (instructions)" -- the v1 miss.
    ("repeat_verbatim", re.compile(
        r"(repeat|print|wiederhol\w*|gib\s+.{0,10}wieder)\b.{0,40}"
        r"(above|vorher\w*|obig\w*|verbatim|wort\s*wörtlich|word\s*for\s*word)",
        re.IGNORECASE)),
    ("role_escalation", re.compile(
        r"(entwickler|developer|admin|root)\s*modus|developer mode|dan mode", re.IGNORECASE)),
    ("exfil_or_tooling", re.compile(
        r"(fetch|curl|wget|execute|run)\s+\S+|führe\s+.{0,20}\s+aus|API[-\s]?key", re.IGNORECASE)),
    ("fake_delimiter", re.compile(
        r"(-{3,}\s*(end|ende|system|user)\s*-{3,})|<\s*/?\s*(system|instructions?)\s*>", re.IGNORECASE)),
]

# Candidate base64 tokens: long-ish, base64 alphabet, optional `=` padding.
# No trailing \b: `=` is not a word char, so a \b would exclude the padding and
# break the length-mod-4 check used below.
_B64_TOKEN = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _decode_base64_blobs(text: str) -> list[str]:
    """Return decoded strings for base64-looking tokens that decode to text."""
    decoded: list[str] = []
    for m in _B64_TOKEN.finditer(text):
        tok = m.group(0)
        if len(tok) % 4 != 0:
            continue
        try:
            raw = base64.b64decode(tok, validate=True)
            s = raw.decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        # Only keep decodes that look like readable text, not random bytes.
        printable = sum(c.isprintable() or c.isspace() for c in s)
        if s and printable / len(s) > 0.85:
            decoded.append(s)
    return decoded


def _match_patterns(text: str) -> list[str]:
    return [name for name, rx in _PATTERNS if rx.search(text)]


def detect_injection(
    masked_text: str,
    injection_model=None,
    threshold: float | None = None,
) -> InjectionVerdict:
    """Detect prompt-injection on the masked text (R14-R16, V18-V19; Round 3).

    Verdict = normalised rules OR (trained injection-LR probability >= threshold).

    Round 3 removes the fixed 0.80 embedding-similarity cut (which flagged 99/100
    normal items). Instead, when a trained `injection_model` is supplied, its
    calibrated probability is compared against `threshold` (chosen on dev and
    stored in models/manifest.json). With no model supplied the detector is the
    normalised rules alone -- the offline default.
    """
    norm = normalize(masked_text)
    matched = _match_patterns(norm)

    # V19: decode short base64 blobs (from the raw text, pre-normalisation) and
    # re-scan the decoded content normalised.
    for decoded in _decode_base64_blobs(masked_text):
        for name in _match_patterns(normalize(decoded)):
            tag = f"{name}:base64"
            if tag not in matched:
                matched.append(tag)

    rule_hit = bool(matched)

    # Trained-model signal (Round 3). Only used when a model + threshold are given.
    model_prob = None
    model_hit = False
    if injection_model is not None and threshold is not None:
        try:
            model_prob = float(injection_model.proba(norm))
        except Exception:  # noqa: BLE001 - a model failure must not crash triage
            model_prob = None
        if model_prob is not None and model_prob >= threshold:
            model_hit = True
            matched.append(f"injection_lr>={threshold}:{round(model_prob, 3)}")

    detected = rule_hit or model_hit
    if detected:
        reason = "matched injection signal(s): " + ", ".join(matched)
    else:
        reason = "no injection rule matched"
        if model_prob is not None:
            reason += f" (lr prob {round(model_prob, 3)} < {threshold})"
    return InjectionVerdict(detected=detected, reason=reason, matched_rules=matched)
