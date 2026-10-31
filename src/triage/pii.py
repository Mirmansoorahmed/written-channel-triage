"""Step 2: PII masking (R6-R9).

Mask personal data before any LLM call. Masking is reversible via an in-memory
token map that lives only for the request lifetime. No raw PII ever reaches the
LLM, the human handoff, or the audit log.

Order matters: we mask the most specific / structured patterns first (IBAN,
email) before looser ones (phone, customer number) so we do not mis-split a value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MaskResult:
    masked_text: str
    # placeholder -> original value. In memory only (R7).
    token_map: dict[str, str] = field(default_factory=dict)


# German IBAN: DE + 2 check digits + 18 digits, tolerant of spaces.
_IBAN = re.compile(r"\bDE\d{2}(?:\s?\d{4}){4}\s?\d{2}\b", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# German phone: optional +49 / 0, then digits with spaces, slashes or dashes.
_PHONE = re.compile(r"(?<!\w)(?:\+49|0)[\d\s/\-]{6,}\d")
# Customer / Kundennummer: label followed by digits.
_CUSTOMER = re.compile(
    r"(?:Kundennummer|Kundennr\.?|Vertragsnummer|Kd\.?-?Nr\.?)\s*:?\s*([A-Z]?\d{5,})",
    re.IGNORECASE,
)
# Postal address: street + number, then optional "PLZ Ort" on same or next line.
_ADDRESS = re.compile(
    r"\b[A-ZÄÖÜ][a-zäöüß]+(?:straße|str\.?|weg|platz|allee|gasse|ring)\s+\d+[a-z]?"
    r"(?:,?\s*\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+)?",
)
# Name after a German greeting ("Mit freundlichen Grüßen\nVorname Nachname").
_NAME = re.compile(
    r"(?:Mit freundlichen Grüßen|Viele Grüße|Beste Grüße|Grüße)\s*[,]?\s*\n+\s*"
    r"([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+){1,2})",
)


def _mask_with(
    text: str,
    rx: re.Pattern,
    label: str,
    counter: dict[str, int],
    token_map: dict[str, str],
    group: int = 0,
) -> str:
    def repl(m: re.Match) -> str:
        original = m.group(group)
        # Reuse a placeholder if we already saw this exact value.
        for ph, val in token_map.items():
            if val == original and ph.startswith(f"[[{label}_"):
                return m.group(0).replace(original, ph)
        counter[label] = counter.get(label, 0) + 1
        placeholder = f"[[{label}_{counter[label]}]]"
        token_map[placeholder] = original
        return m.group(0).replace(original, placeholder)

    return rx.sub(repl, text)


def mask(text: str) -> MaskResult:
    """Mask all supported PII types, returning masked text + reverse map (R6-R8)."""
    counter: dict[str, int] = {}
    token_map: dict[str, str] = {}
    out = text
    # Specific/structured first.
    out = _mask_with(out, _IBAN, "IBAN", counter, token_map)
    out = _mask_with(out, _EMAIL, "EMAIL", counter, token_map)
    out = _mask_with(out, _CUSTOMER, "CUSTOMER", counter, token_map, group=1)
    out = _mask_with(out, _ADDRESS, "ADDRESS", counter, token_map)
    out = _mask_with(out, _NAME, "NAME", counter, token_map, group=1)
    out = _mask_with(out, _PHONE, "PHONE", counter, token_map)
    return MaskResult(masked_text=out, token_map=token_map)


def unmask(masked_text: str, token_map: dict[str, str]) -> str:
    """Restore original text from masked text + token map (R8)."""
    out = masked_text
    for placeholder, original in token_map.items():
        out = out.replace(placeholder, original)
    return out


def contains_pii_placeholder(text: str) -> bool:
    """True if the text still carries a masking placeholder."""
    return bool(re.search(r"\[\[[A-Z]+_\d+\]\]", text))


# Raw-PII detectors for the SLM-output re-check (V22). We ignore masking
# placeholders (they are safe) and look for unmasked structured values that must
# never leave the model boundary: IBAN, email, German phone, customer number.
_RAW_PII = (
    ("iban", _IBAN),
    ("email", _EMAIL),
    ("phone", _PHONE),
    ("customer", _CUSTOMER),
)


def contains_raw_pii(text: str) -> bool:
    """True if `text` still contains an unmasked PII value (V22).

    Used after the SLM returns to confirm the model did not echo a raw value back.
    Placeholders like [[IBAN_1]] are stripped first so they never count as a leak.
    """
    stripped = re.sub(r"\[\[[A-Z]+_\d+\]\]", "", text)
    return any(rx.search(stripped) for _name, rx in _RAW_PII)


def raw_pii_kinds(text: str) -> list[str]:
    """Which raw-PII kinds appear in `text` (for an explainable flag)."""
    stripped = re.sub(r"\[\[[A-Z]+_\d+\]\]", "", text)
    return [name for name, rx in _RAW_PII if rx.search(stripped)]
