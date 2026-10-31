from triage.classify import classify, retrieve
from triage.llm import MockClient, OfflineClient


def test_retrieve_ranks_stoerung():
    cands = retrieve("Mein Internet ist seit gestern tot, kein Internet mehr.")
    assert cands[0][0] == "Störung"
    assert cands[0][1] > 0


def test_classify_offline_default_stoerung():
    c = classify("kein internet, der anschluss funktioniert nicht, alles offline")
    assert c.category == "Störung"
    assert c.confidence > 0


def test_classify_rechnung_extracts_and_marks_missing():
    text = "Frage zur rechnung, kundennummer [[CUSTOMER_1]]. Es geht um den Betrag im Mai."
    c = classify(text)
    assert c.category == "Rechnung"
    assert "kundennummer" in c.fields
    assert "rechnungsmonat" in c.fields
    assert c.missing_fields == []


def test_classify_unknown_falls_back_to_sonstiges():
    c = classify("xyz qwerty foobar")
    assert c.category == "Sonstiges"
    assert c.confidence == 0.0


def test_llm_is_pluggable_via_mock():
    c = classify("egal welcher text", client=MockClient("Kündigung", 0.9))
    assert c.category == "Kündigung"
    assert c.confidence == 0.9


def test_offline_client_is_deterministic():
    text = "tarifwechsel bitte, ich möchte einen anderen tarif"
    a = classify(text, client=OfflineClient())
    b = classify(text, client=OfflineClient())
    assert a == b
