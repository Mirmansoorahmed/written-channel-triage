"""Text normalisation for the injection detector (V18).

v1 learned the hard way that an attacker can slip `I G N O R E all previous
instructions` past a regex that keys on contiguous phrasing, and that homoglyphs
(Cyrillic/Greek lookalikes) defeat a Latin-only pattern. So before the injection
detector matches, I canonicalise the text:

  1. Unicode NFKC, which folds compatibility forms.
  2. Strip zero-width and bidi control characters an attacker uses to hide spacing.
  3. Fold a small homoglyph table (Cyrillic/Greek -> Latin).
  4. Collapse runs of whitespace so `I G N O R E` becomes `ignore` only when the
     single-letter-spacing pattern is present (handled by a dedicated de-spacer).

This module is pure standard library: no dependency, safe to import anywhere.
"""

from __future__ import annotations

import re
import unicodedata

# A small, explicit homoglyph map. I keep it readable rather than exhaustive:
# these are the lookalikes that actually show up in spaced/obfuscated injection
# attempts. Key = confusable, value = Latin canonical.
_HOMOGLYPHS: dict[str, str] = {
    # Cyrillic
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c",
    "\u0443": "y", "\u0445": "x", "\u0456": "i", "\u0455": "s", "\u043a": "k",
    "\u0432": "b", "\u043d": "h", "\u043c": "m", "\u0442": "t",
    # Greek
    "\u03b1": "a", "\u03bf": "o", "\u03b5": "e", "\u03c1": "p", "\u03c5": "u",
    "\u03b9": "i", "\u03ba": "k", "\u03bd": "v", "\u03c7": "x", "\u03c4": "t",
    # Full-width latin letters fold under NFKC already; kept here for clarity.
}

# Zero-width and bidi/control characters used to hide or space out text.
_INVISIBLES = re.compile(
    "[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad\u202a-\u202e]"
)

# A run of single letters separated by whitespace, e.g. "i g n o r e".
# Require at least 4 single chars (3 "<char><space>" groups + a final char) so
# ordinary short sequences like "a b c" are left alone while spaced-out attack
# words (ignore, system, reveal, ...) are collapsed.
_SPACED_LETTERS = re.compile(r"(?:(?<=\s)|^)(?:[a-z0-9]\s+){3,}[a-z0-9](?=\s|$)")

# A run of letters separated by a single punctuation char, e.g. "i-g-n-o-r-e".
_PUNCT_SPACED = re.compile(r"\b(?:[a-z0-9][-_.]){2,}[a-z0-9]\b")


def fold_homoglyphs(text: str) -> str:
    return "".join(_HOMOGLYPHS.get(ch, ch) for ch in text)


def strip_invisibles(text: str) -> str:
    return _INVISIBLES.sub("", text)


def _despace_letters(text: str) -> str:
    """Join single-letter-spaced runs: 'i g n o r e' -> 'ignore'.

    Only collapses runs that look deliberately spaced out (>=3 single chars),
    so ordinary prose ('a b c' style lists are rare and short) is left intact.
    """
    def repl(m: re.Match) -> str:
        return re.sub(r"\s+", "", m.group(0))

    return _SPACED_LETTERS.sub(repl, text)


def _depunct_letters(text: str) -> str:
    """Join punctuation-spaced runs: 'i-g-n-o-r-e' -> 'ignore'."""
    def repl(m: re.Match) -> str:
        return re.sub(r"[-_.]", "", m.group(0))

    return _PUNCT_SPACED.sub(repl, text)


def normalize(text: str) -> str:
    """Canonicalise text for robust injection matching (V18).

    The result is lower-cased, NFKC-folded, homoglyph-folded, stripped of invisible
    characters, with single-letter spacing collapsed. The original text is never
    mutated in place; callers keep the raw string for display.
    """
    out = unicodedata.normalize("NFKC", text)
    out = strip_invisibles(out)
    out = fold_homoglyphs(out.lower())
    out = _despace_letters(out)
    out = _depunct_letters(out)
    # Collapse remaining whitespace runs to single spaces for stable matching.
    out = re.sub(r"\s+", " ", out).strip()
    return out
