"""Tests for text normalisation (V18)."""

from triage.normalize import (
    fold_homoglyphs,
    normalize,
    strip_invisibles,
)


def test_despaces_single_letter_run():
    assert normalize("I G N O R E all") == "ignore all"


def test_depuncts_letter_run():
    assert "ignore" in normalize("i-g-n-o-r-e the rules")


def test_folds_cyrillic_homoglyphs():
    # 'o' here is U+043E CYRILLIC SMALL LETTER O
    assert normalize("ign\u043ere") == "ignore"


def test_strips_zero_width():
    assert strip_invisibles("ig\u200bnore") == "ignore"


def test_nfkc_folds_fullwidth():
    # Full-width 'IGNORE' folds to ascii under NFKC.
    assert "ignore" in normalize("\uff29\uff27\uff2e\uff2f\uff32\uff25")


def test_homoglyph_table_is_identity_for_latin():
    assert fold_homoglyphs("normal text") == "normal text"


def test_collapses_whitespace():
    assert normalize("a   b\n\tc") == "a b c"


def test_short_letter_sequence_is_left_alone():
    # Only runs of >=4 spaced single chars are treated as obfuscation;
    # a short "a b c" stays as separate tokens.
    assert normalize("a b c") == "a b c"
