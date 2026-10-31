"""Step 3: classify + extract (R10-R13).

A small, local retrieval step scores each category against the masked text using
my own category descriptions and keyword cues (this is the "RAG over my own
category descriptions" -- entirely local, no index service). The pluggable LLM
then picks from the scored candidates. Confidence comes from the retrieval score so
a low-confidence result can be routed to a human.

Field extraction reads which required fields are present (as masking placeholders
or plain cues) and marks the rest as missing.
"""

from __future__ import annotations

import re

from . import categories
from .llm import LLMClient, default_client
from .models import Classification


def _score(masked_text: str, cat: categories.Category) -> float:
    """Local retrieval score: keyword hits normalized, plus a description overlap."""
    text = masked_text.lower()
    if not cat.keywords:
        return 0.0
    hits = sum(1 for kw in cat.keywords if kw in text)
    kw_score = hits / len(cat.keywords)
    # Small bonus for description word overlap, so near-synonyms still rank.
    desc_words = {w for w in re.findall(r"[a-zäöüß]{4,}", cat.description.lower())}
    overlap = sum(1 for w in desc_words if w in text)
    desc_score = overlap / max(len(desc_words), 1)
    return round(0.8 * kw_score + 0.2 * desc_score, 4)


def retrieve(masked_text: str) -> list[tuple[str, float]]:
    """Return category candidates sorted by score, best first."""
    scored = [(c.name, _score(masked_text, c)) for c in categories.CATEGORIES if c.name != "Sonstiges"]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


# Map a required field name to the masking placeholder or cue that satisfies it.
_FIELD_CUES = {
    "kundennummer": re.compile(r"\[\[CUSTOMER_\d+\]\]"),
    "neue_adresse": re.compile(r"\[\[ADDRESS_\d+\]\]|neue adresse", re.IGNORECASE),
    "rechnungsmonat": re.compile(
        r"\b(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\b",
        re.IGNORECASE,
    ),
    "umzugsdatum": re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|zum \d"),
    "kündigungsdatum": re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|zum nächstmöglichen"),
    "fehlerbeschreibung": re.compile(r"\w{12,}"),
    "beschwerdegrund": re.compile(r"\w{12,}"),
    "zieltarif": re.compile(r"tarif\s+\w+|\b[a-z]+-?tarif\b", re.IGNORECASE),
    "anliegen_art": re.compile(r"auskunft|löschung|berichtigung", re.IGNORECASE),
    "gerät": re.compile(r"router|wlan|fritzbox|modem|repeater", re.IGNORECASE),
}


def _extract_fields(masked_text: str, cat: categories.Category) -> tuple[dict[str, str], list[str]]:
    found: dict[str, str] = {}
    missing: list[str] = []
    for fname in cat.required_fields:
        rx = _FIELD_CUES.get(fname)
        if rx:
            m = rx.search(masked_text)
            if m:
                found[fname] = m.group(0)
                continue
        missing.append(fname)
    return found, missing


def classify(masked_text: str, client: LLMClient | None = None) -> Classification:
    """Classify a masked request and extract required fields (R10-R13)."""
    client = client or default_client()
    candidates = retrieve(masked_text)
    name, confidence = client.classify(masked_text, candidates)

    cat = categories.get(name) if name in categories.BY_NAME else categories.get("Sonstiges")
    fields, missing = _extract_fields(masked_text, cat)

    if confidence <= 0.0:
        reason = "no category cue matched; routed as Sonstiges for a human"
    elif confidence < 0.25:
        reason = f"low confidence ({confidence}); suggest human review"
    else:
        reason = f"matched '{cat.name}' with confidence {confidence}"

    return Classification(
        category=cat.name,
        confidence=confidence,
        fields=fields,
        missing_fields=missing,
        reason=reason,
    )
