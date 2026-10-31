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


# --- v2: SLM-output raw-PII re-check (V22) ---

from triage.pii import contains_raw_pii, raw_pii_kinds


def test_contains_raw_pii_detects_iban():
    assert contains_raw_pii("Kunde IBAN DE89 3704 0044 0532 0130 00 bitte")


def test_contains_raw_pii_detects_email():
    assert contains_raw_pii("melde dich an max.mustermann@example.de")


def test_placeholders_are_not_raw_pii():
    assert not contains_raw_pii("Kunde [[IBAN_1]] und [[EMAIL_1]] fragt zur Rechnung")


def test_clean_text_has_no_raw_pii():
    assert not contains_raw_pii("Frage zur Rechnung im Mai, Kategorie Rechnung")


def test_raw_pii_kinds_lists_matches():
    kinds = raw_pii_kinds("IBAN DE89 3704 0044 0532 0130 00 und a@b.de")
    assert "iban" in kinds
    assert "email" in kinds


# --- v2 review fix #2: typo-tolerant masking + ground-truth leak check ---

from triage.pii import ground_truth_leaks


def test_masks_customer_number_under_typo_label():
    # "KKundeennumer" is a typo of Kundennummer; the number must still be masked.
    r = mask("KKundeennumer: 123456789 Frage zur Rechnung.")
    assert "123456789" not in r.masked_text
    assert "[[CUSTOMER_1]]" in r.masked_text


def test_masks_label_variants():
    for label in ["Kundennr.", "Kd.-Nr.", "Vertragsnummer", "Kundennumer"]:
        r = mask(f"{label}: 998877665 bitte prüfen")
        assert "998877665" not in r.masked_text, label


def test_masks_bare_long_number_as_customer():
    r = mask("Meine Nummer 100200300 für die Rückfrage.")
    assert "100200300" not in r.masked_text


def test_masks_signature_after_garbled_signoff():
    text = "Frage zur Rechnung.\n\nrGüße\nClara Schmidt"
    r = mask(text)
    assert "Clara Schmidt" not in r.masked_text
    assert "[[NAME_1]]" in r.masked_text


def test_masks_titled_hyphenated_name():
    text = "Rechnungsfrage.\n\nMit freundlichen Grüßen\nDr. Katharina Vollmer-Schmidt"
    r = mask(text)
    assert "Katharina" not in r.masked_text
    assert "Vollmer-Schmidt" not in r.masked_text


def test_ground_truth_leaks_detects_survivor():
    # A value in pii_truth that is NOT masked should be reported as leaked.
    masked = "Kunde [[CUSTOMER_1]] mit IBAN DE89 3704 0044 0532 0130 00"
    leaks = ground_truth_leaks(masked, ["DE89 3704 0044 0532 0130 00", "123456789"])
    assert "DE89 3704 0044 0532 0130 00" in leaks
    assert "123456789" not in leaks  # 123456789 is not present -> not leaked


def test_ground_truth_leaks_whitespace_insensitive():
    masked = "IBAN de8937040044053201 3000 blieb stehen"
    leaks = ground_truth_leaks(masked, ["DE89 3704 0044 0532 0130 00"])
    assert leaks  # whitespace/case differences still count as the same value


def test_ground_truth_leaks_clean_when_all_masked():
    masked = "Kunde [[CUSTOMER_1]], [[IBAN_1]], [[NAME_1]]"
    assert ground_truth_leaks(masked, ["123456789", "DE89 3704 0044 0532 0130 00", "Max Mustermann"]) == []


def test_masks_name_after_label():
    # "Signatur: Dr. Katharina Vollmer-Schmidt" (name not on the last line).
    r = mask("Rechnungsfrage. Kundennummer 123123123. Signatur: Dr. Katharina Vollmer-Schmidt.")
    assert "Katharina" not in r.masked_text
    assert "Vollmer-Schmidt" not in r.masked_text


def test_masks_multiword_street_name():
    # "Am Alten Markt 3, 04109 Leipzig" -- multi-word street, standalone suffix.
    r = mask("Umzug: neue Anschrift Am Alten Markt 3, 04109 Leipzig.")
    assert "Am Alten Markt 3" not in r.masked_text
    assert "[[ADDRESS_1]]" in r.masked_text
