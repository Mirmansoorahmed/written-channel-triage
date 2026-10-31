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


# IBAN. Round 3: the old pattern required a correct "DE" country code, so a typo
# like "ED44 ..." or "D44 ..." leaked. We now match a German IBAN tolerantly: an
# optional/garbled 2-letter country code (or a single letter) followed by the 2
# check digits and the 18-digit body in 4-digit groups. The country code is
# matched loosely (any two letters, or one), so ED44/D44 are caught; validity is
# not the point -- masking is.
_IBAN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:[A-Za-z]{1,2})?\s?\d{2}(?:[ \-]?\d{4}){4}[ \-]?\d{2}"
    r"(?![0-9])",
)
# A bare IBAN body fragment: 4-digit groups that look like part of an IBAN even if
# the country code is missing entirely. Masked after the labelled form.
_IBAN_FRAGMENT = re.compile(r"(?<![A-Za-z0-9])\d{4}(?:[ \-]?\d{4}){3,}(?![0-9])")
# Email, tolerant of a truncated TLD (e.g. "example.d" or "example.").
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{0,}")
# German phone: optional +49 / 0, then digits with spaces, slashes or dashes.
_PHONE = re.compile(r"(?<!\w)(?:\+49|0)[\d\s/\-]{6,}\d")

# Customer / contract id: a FUZZY label (handled in code via Levenshtein on label
# tokens) followed by an id of >=5 digits. We also keep a regex for the common
# spellings as a fast path, plus a bare long-digit fallback.
_CUSTOMER_LABELLED = re.compile(
    r"(?:kund\w*|kd\.?-?\s*nr\.?|vertrags?\w*)\s*[:.]?\s*([A-Za-z]?\d{5,})",
    re.IGNORECASE,
)
_CUSTOMER_BARE = re.compile(r"(?<!\d)([A-Za-z]?\d{8,})(?!\d)")
# Any "<label>: <id>" where the label is close (edit distance <= 2) to a known PII
# label. Catches "Kundennummr: 12345", "Vretragsnummer 998", etc.
_LABELLED_ID = re.compile(
    r"([A-Za-zÄÖÜäöüß.\-]{3,15})\s*[:.]?\s*([A-Za-z]?\d{4,}(?:[ \-]?\d+)*)",
)
_PII_LABELS = ("kundennummer", "kundennr", "kd.-nr", "kdnr", "vertragsnummer",
               "vertragsnr", "nummer", "nr")

# Postal address: a street line ending in a house number, optionally followed by
# "PLZ Ort". The street may be multi-word ("Am Alten Markt 3") or a single
# compound ("Beispielstraße 12"), so we allow an optional capitalised prefix run
# before the final street token + number. Tolerate a typo'd suffix via the roots
# and an optional single inserted letter in "straße" (Beisspieltsraße).
_ADDRESS = re.compile(
    r"\b(?:[A-ZÄÖÜ][a-zäöüß]+\s+){0,3}"
    r"(?:"
    # compound ending in a (possibly typo'd) street suffix
    r"[A-ZÄÖÜ][a-zäöüß]*(?:stra[sß]?[sß]?e?|str\.?|t?sra[sß]e|weg|platz|allee|gasse|ring|markt|damm|ufer)"
    r"|"
    r"(?:Markt|Damm|Ufer|Platz|Ring|Allee|Weg)"
    r")"
    r"\s*\d+[a-z]?"
    r"(?:,?\s*\d{4,5}\s+[A-ZÄÖÜ][a-zäöüß]+)?",
    re.IGNORECASE,
)
# A standalone "PLZ Ort" (5-digit postcode + capitalised city) so a city survives
# even if the street match stops early.
_PLZ_ORT = re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+(?:[- ][A-ZÄÖÜ][a-zäöüß]+)?")


def _levenshtein(a: str, b: str) -> int:
    """Edit distance (stdlib, small strings only)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > 2:  # we only ever care about <= 2
        return 3
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[lb]


def _is_pii_label(token: str) -> bool:
    """True if `token` is within edit distance 2 of a known PII label."""
    t = token.lower().strip(".:- ")
    return any(_levenshtein(t, lab) <= 2 for lab in _PII_LABELS)
# An explicit name label ("Signatur:", "Name:", "Unterschrift:", "Absender:")
# followed by a capitalised personal name (optionally titled / hyphenated).
_NAME_LABELLED = re.compile(
    r"(?:signatur|name|unterschrift|absender|von)\s*[:]\s*"
    r"((?:Dr\.?\s+|Prof\.?\s+)?[A-ZÄÖÜ][a-zäöüß]+(?:[-\s]+[A-ZÄÖÜ][a-zäöüß]+){1,3})",
    re.IGNORECASE,
)
# Signature name after a sign-off. Round 3: tolerate ANY greeting (typo'd or not)
# by matching a short greeting-ish line followed by a capitalised full name on the
# next line, plus the explicit roots. A name may contain a typo in any token (we
# only require the capitalisation shape), so "Finn uMsterfrau" still matches.
_NAME = re.compile(
    r"(?:mit\s+freundlichen\s+gr\w+|viele\s+gr\w+|beste\s+gr\w+|gr\w*\u00df\w*|"
    r"gruess\w*|best\s+regards|regards|mfg|lg|danke(?:\s+und\s+gr\w+)?)\s*[,]?\s*\n+\s*"
    r"((?:Dr\.?\s+|Prof\.?\s+)?[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]+(?:[-\s]+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]+){1,3})",
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
# Tolerate a typo inside the name ("uMsterfrau") by allowing mixed case in the
# tail, while still requiring a capitalised first letter per token.
_SIG_NAME_LINE = re.compile(
    r"^\s*((?:Dr\.?\s+|Prof\.?\s+)?[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]+(?:[-\s]+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]+){1,3})\s*$"
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


def _mask_fuzzy_labelled_ids(
    text: str, counter: dict[str, int], token_map: dict[str, str]
) -> str:
    """Mask `<label>: <id>` where the label is within edit distance 2 of a known
    PII label but the fast-path regex did not already catch it (typo'd labels)."""
    def repl(m: re.Match) -> str:
        label, ident = m.group(1), m.group(2)
        if "[[" in ident or not _is_pii_label(label):
            return m.group(0)
        counter["CUSTOMER"] = counter.get("CUSTOMER", 0) + 1
        placeholder = f"[[CUSTOMER_{counter['CUSTOMER']}]]"
        token_map[placeholder] = ident
        return m.group(0).replace(ident, placeholder)

    return _LABELLED_ID.sub(repl, text)


def mask(text: str) -> MaskResult:
    """Mask all supported PII types, returning masked text + reverse map (R6-R8).

    Order matters: IBAN (full and typo'd country code) and IBAN fragments are
    masked BEFORE phone, so a grouped IBAN body is not eaten by the phone pattern.
    Then email, labelled/fuzzy-labelled customer ids, the bare long-digit fallback,
    address + postcode/city, and finally the signature name (explicit label, then
    sign-off regex, then a trailing-line fallback for garbled sign-offs).
    """
    counter: dict[str, int] = {}
    token_map: dict[str, str] = {}
    out = text
    out = _mask_with(out, _IBAN, "IBAN", counter, token_map)
    out = _mask_with(out, _IBAN_FRAGMENT, "IBAN", counter, token_map)
    out = _mask_with(out, _EMAIL, "EMAIL", counter, token_map)
    out = _mask_with(out, _PHONE, "PHONE", counter, token_map)
    out = _mask_with(out, _CUSTOMER_LABELLED, "CUSTOMER", counter, token_map, group=1)
    out = _mask_fuzzy_labelled_ids(out, counter, token_map)
    out = _mask_with(out, _CUSTOMER_BARE, "CUSTOMER", counter, token_map, group=1)
    out = _mask_with(out, _ADDRESS, "ADDRESS", counter, token_map)
    out = _mask_with(out, _PLZ_ORT, "ADDRESS", counter, token_map)
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


def _partial_ratio(needle: str, haystack: str) -> float:
    """Best overlap of `needle` against any equal-length window of `haystack`.

    A lightweight stand-in for a fuzzy partial ratio (no rapidfuzz dependency):
    slides `needle` over `haystack` and returns the highest fraction of matching
    characters at aligned positions. Good enough to catch a near-duplicate that a
    typo or a dropped character would otherwise hide.
    """
    n, h = len(needle), len(haystack)
    if n == 0:
        return 1.0
    if n > h:
        needle, haystack, n, h = haystack, needle, h, n
    if n == 0:
        return 1.0
    best = 0.0
    for start in range(h - n + 1):
        window = haystack[start:start + n]
        same = sum(1 for a, b in zip(needle, window) if a == b)
        best = max(best, same / n)
        if best == 1.0:
            break
    return best


_IBAN_FRAG = re.compile(r"[A-Za-z]{0,2}\d(?:[ \-]?\d)+")


def fuzzy_ground_truth_leaks(
    masked_text: str, pii_values: list[str], partial_threshold: float = 0.85
) -> list[dict]:
    """Fuzzy ground-truth leak check (Round 3, eval/pii_leak_check.py).

    For each ground-truth value, normalise case/whitespace and:
      * count it leaked if its loose form is a substring of the masked text, OR
      * the best partial-ratio against the masked text is >= `partial_threshold`, OR
      * (for IBAN-like values) any contiguous fragment of 8+ characters survives.
    Returns a list of {"value", "reason", "score"} for the values that leaked.
    """
    loose_blob = _loose(masked_text)
    leaks: list[dict] = []
    for value in pii_values:
        v = _loose(value)
        if not v:
            continue
        if v in loose_blob:
            leaks.append({"value": value, "reason": "exact", "score": 1.0})
            continue
        # IBAN-fragment rule: any 8+ char digit fragment of the value that survives.
        if _IBAN_FRAG.fullmatch(value.strip()) or _looks_ibanish(value):
            frag = re.sub(r"[^0-9a-z]", "", value.lower())
            hit = _longest_common_fragment(frag, loose_blob)
            if hit >= 8:
                leaks.append({"value": value, "reason": f"iban_fragment>={hit}", "score": 1.0})
                continue
        pr = _partial_ratio(v, loose_blob)
        if pr >= partial_threshold:
            leaks.append({"value": value, "reason": "partial_ratio", "score": round(pr, 3)})
    return leaks


def _looks_ibanish(value: str) -> bool:
    digits = sum(c.isdigit() for c in value)
    return digits >= 10


def _longest_common_fragment(needle: str, haystack: str) -> int:
    """Length of the longest contiguous substring of `needle` found in `haystack`."""
    best = 0
    n = len(needle)
    for i in range(n):
        for j in range(i + best + 1, n + 1):
            if needle[i:j] in haystack:
                best = max(best, j - i)
            else:
                break
    return best
