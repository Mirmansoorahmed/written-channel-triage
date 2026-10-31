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


def embedding_injection_score(text: str, retriever) -> float | None:
    """Optional similarity of `text` to known injection exemplars (V20).

    Returns a cosine-style score in [0, 1], or None when no retriever is given or
    the retriever has no injection exemplars. Pure delegation so this module keeps
    no model dependency.
    """
    if retriever is None:
        return None
    score_fn = getattr(retriever, "injection_similarity", None)
    if score_fn is None:
        return None
    return score_fn(text)


def detect_injection(masked_text: str, retriever=None, embed_threshold: float = 0.80) -> InjectionVerdict:
    """Detect prompt-injection attempts on the masked text (R14-R16, V18-V20).

    `retriever` is optional; when supplied and it exposes `injection_similarity`,
    an embedding check can flag novel phrasings the regexes miss.
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

    # V20: optional embedding-similarity check.
    embed_score = embedding_injection_score(norm, retriever)
    if embed_score is not None and embed_score >= embed_threshold:
        matched.append(f"embedding_similarity:{round(embed_score, 3)}")

    if matched:
        return InjectionVerdict(
            detected=True,
            reason="matched injection pattern(s): " + ", ".join(matched),
            matched_rules=matched,
        )
    return InjectionVerdict(detected=False, reason="no injection pattern matched")
