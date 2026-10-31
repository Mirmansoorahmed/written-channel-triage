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

# Customer / contract number. v2 note: typos in the data (e.g. "Kundennumer")
# broke the old fixed-label regex and leaked the raw number. We now match in two
# tolerant ways:
#   1. A FUZZY label: a token that starts "kund"/"kd"/"vertrag" (covering
#      Kundennummer, Kundennr., Kd.-Nr., Kundennumer, Vertragsnummer, ...),
#      followed within a few characters by an id of >=5 digits (optionally with a
#      leading letter, e.g. B12345678).
#   2. A fallback for a bare long digit run (>=8 digits) that IBAN/phone did not
#      already claim -- in this domain a lone long number is an identifier.
_CUSTOMER_LABELLED = re.compile(
    r"(?:kund\w*|kd\.?-?\s*nr\.?|vertrags?\w*)\s*[:.]?\s*([A-Za-z]?\d{5,})",
    re.IGNORECASE,
)
_CUSTOMER_BARE = re.compile(r"(?<!\d)([A-Za-z]?\d{8,})(?!\d)")

# Postal address: a street line ending in a house number, optionally followed by
# "PLZ Ort". The street may be multi-word ("Am Alten Markt 3") or a single
# compound ("Beispielstraße 12"), so we allow an optional capitalised prefix run
# before the final street token + number. Tolerate a typo'd suffix via the roots.
_ADDRESS = re.compile(
    r"\b(?:[A-ZÄÖÜ][a-zäöüß]+\s+){0,3}"
    r"(?:"
    # compound ending in a lowercase suffix: "Beispielstraße", "Lindenweg"
    r"[A-ZÄÖÜ][a-zäöüß]*(?:straße|strasse|str\.?|weg|platz|allee|gasse|ring|markt|damm|ufer)"
    r"|"
    # or a standalone capitalised suffix word: "Markt", "Damm", "Ufer", "Platz"
    r"(?:Markt|Damm|Ufer|Platz|Ring|Allee|Weg)"
    r")"
    r"\s+\d+[a-z]?"
    r"(?:,?\s*\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+)?",
)
# An explicit name label ("Signatur:", "Name:", "Unterschrift:", "Absender:")
# followed by a capitalised personal name (optionally titled / hyphenated).
_NAME_LABELLED = re.compile(
    r"(?:signatur|name|unterschrift|absender|von)\s*[:]\s*"
    r"((?:Dr\.?\s+|Prof\.?\s+)?[A-ZÄÖÜ][a-zäöüß]+(?:[-\s]+[A-ZÄÖÜ][a-zäöüß]+){1,3})",
    re.IGNORECASE,
)
# Signature name after a sign-off. v2: tolerate typos in the sign-off phrase
# (match on the stable roots "grüß"/"gruess"/"grüss"/"regards"/"MfG") and allow a
# title ("Dr.") and hyphenated surnames.
_NAME = re.compile(
    r"(?:mit\s+freundlichen\s+gr\w+|viele\s+gr\w+|beste\s+gr\w+|gr\w*\u00df\w*|"
    r"gruess\w*|best\s+regards|regards|mfg|lg|danke(?:\s+und\s+gr\w+)?)\s*[,]?\s*\n+\s*"
    r"((?:Dr\.?\s+|Prof\.?\s+)?[A-ZÄÖÜ][a-zäöüß]+(?:[-\s]+[A-ZÄÖÜ][a-zäöüß]+){1,3})",
    re.IGNORECASE,
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


# Fallback: a capitalised 2-4 word personal name standing alone on a line. Used
# only for the trailing signature line, where the preceding sign-off may be typo'd
# beyond recognition ("Dnake", "rGüße", "GL"), so matching on the sign-off text is
# unreliable. A lone capitalised full name on the final line is a signature.
_SIG_NAME_LINE = re.compile(
    r"^\s*((?:Dr\.?\s+|Prof\.?\s+)?[A-ZÄÖÜ][a-zäöüß]+(?:[-\s]+[A-ZÄÖÜ][a-zäöüß]+){1,3})\s*$"
)


def _mask_trailing_signature(
    text: str, counter: dict[str, int], token_map: dict[str, str]
) -> str:
    """Mask a personal name sitting alone on the last non-empty line (signature)."""
    lines = text.split("\n")
    # Find the last non-empty line.
    idx = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
    if idx is None:
        return text
    m = _SIG_NAME_LINE.match(lines[idx])
    if not m:
        return text
    name = m.group(1)
    # Don't mask if it already contains a placeholder.
    if "[[" in name:
        return text
    counter["NAME"] = counter.get("NAME", 0) + 1
    placeholder = f"[[NAME_{counter['NAME']}]]"
    token_map[placeholder] = name
    lines[idx] = lines[idx].replace(name, placeholder)
    return "\n".join(lines)


def mask(text: str) -> MaskResult:
    """Mask all supported PII types, returning masked text + reverse map (R6-R8).

    Order matters: mask the structured values that contain long digit runs (IBAN,
    email, phone) BEFORE the customer-number fallback, so the bare-digit fallback
    only claims an identifier that nothing else took. Labelled customer numbers are
    matched first (even under a typo'd label); then the bare long-digit fallback;
    then address; then the signature name (sign-off regex, then a trailing-line
    fallback for garbled sign-offs).
    """
    counter: dict[str, int] = {}
    token_map: dict[str, str] = {}
    out = text
    out = _mask_with(out, _IBAN, "IBAN", counter, token_map)
    out = _mask_with(out, _EMAIL, "EMAIL", counter, token_map)
    out = _mask_with(out, _PHONE, "PHONE", counter, token_map)
    out = _mask_with(out, _CUSTOMER_LABELLED, "CUSTOMER", counter, token_map, group=1)
    out = _mask_with(out, _CUSTOMER_BARE, "CUSTOMER", counter, token_map, group=1)
    out = _mask_with(out, _ADDRESS, "ADDRESS", counter, token_map)
    out = _mask_with(out, _NAME_LABELLED, "NAME", counter, token_map, group=1)
    out = _mask_with(out, _NAME, "NAME", counter, token_map, group=1)
    out = _mask_trailing_signature(out, counter, token_map)
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
    ("customer", _CUSTOMER_LABELLED),
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


def _loose(value: str) -> str:
    """Collapse whitespace/casing so 'DE89 3704' and 'de893704' compare equal."""
    return re.sub(r"\s+", "", value).lower()


def ground_truth_leaks(masked_text: str, pii_truth: list[str]) -> list[str]:
    """Return the ground-truth PII values that SURVIVED masking (review fix #2).

    This is the honest leak check: it compares the masked text against the TRUE
    values the generator placed (`pii_truth`), not against the masker's own regex
    (which would be circular -- the masker can't catch a value its regex missed,
    and then its regex would also say "no leak"). A value counts as leaked if its
    whitespace/case-insensitive form still appears in the masked output.
    """
    blob = _loose(masked_text)
    leaked: list[str] = []
    for value in pii_truth:
        v = _loose(value)
        if not v:
            continue
        if v in blob:
            leaked.append(value)
    return leaked
