from triage.pii import contains_pii_placeholder, mask, unmask

SAMPLE = """\
Guten Tag,
meine Kundennummer: 123456789 und meine IBAN lautet DE89 3704 0044 0532 0130 00.
Erreichbar bin ich unter 0171 2345678 oder max.mustermann@example.de.
Meine Adresse ist Beispielstraße 12, 10115 Berlin.

Mit freundlichen Grüßen
Max Mustermann
"""


def test_mask_covers_all_types():
    r = mask(SAMPLE)
    m = r.masked_text
    assert "DE89" not in m
    assert "max.mustermann@example.de" not in m
    assert "0171" not in m
    assert "123456789" not in m
    assert "Beispielstraße 12" not in m
    assert "Max Mustermann" not in m.split("Grüßen")[-1]
    # placeholders present
    assert "[[IBAN_1]]" in m
    assert "[[EMAIL_1]]" in m
    assert "[[CUSTOMER_1]]" in m


def test_mask_is_reversible():
    r = mask(SAMPLE)
    restored = unmask(r.masked_text, r.token_map)
    assert "DE89 3704 0044 0532 0130 00" in restored
    assert "max.mustermann@example.de" in restored
    assert restored == SAMPLE


def test_token_map_in_memory_only():
    # The mask() call returns the map; nothing is written to disk.
    r = mask(SAMPLE)
    assert isinstance(r.token_map, dict)
    assert all(k.startswith("[[") for k in r.token_map)


def test_repeated_value_reuses_placeholder():
    text = "Mail a@b.de und nochmal a@b.de bitte."
    r = mask(text)
    # same email twice -> one placeholder, used twice
    assert r.masked_text.count("[[EMAIL_1]]") == 2
    assert "[[EMAIL_2]]" not in r.masked_text


def test_clean_text_has_no_placeholder():
    r = mask("Mein Internet ist langsam.")
    assert not contains_pii_placeholder(r.masked_text)
    assert r.token_map == {}
