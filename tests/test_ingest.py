"""Ingest + generic phishing tests (Round 3).

The phishing detector no longer knows the generator's bad domains. It scores
generic signals: auth fail/missing, lookalikes of NordTel's OWN domains, link
text/href mismatch, and urgency+payment. These tests use NordTel's own domain
(nordtel.de) and hand-built lookalikes of it -- never a generator domain.
"""

from triage.ingest import OWN_DOMAINS, detect_phishing, parse_eml, parse_form, sender_trust
from triage.models import Source, TrustLevel


EML_PASS = """\
From: kundenservice@nordtel.de
Subject: Frage zur Rechnung
Authentication-Results: mx.nordtel.de; spf=pass; dkim=pass; dmarc=pass

Guten Tag, ich habe eine Frage zu meiner letzten Rechnung.
"""

# Lookalike of nordtel.de (edit distance 1: "norctel.de"), auth fail, urgency+pay.
EML_PHISH = """\
From: billing@norctel.de
Subject: Dringend
Authentication-Results: mx.nordtel.de; spf=fail; dkim=fail; dmarc=fail

Ihr Konto wird gesperrt. Bitte sofort Ihre Bankdaten verifizieren: http://norctel.de/verify
"""


def test_parse_eml_reads_headers_and_body():
    req = parse_eml(EML_PASS)
    assert req.source == Source.EML
    assert req.subject == "Frage zur Rechnung"
    assert "nordtel.de" in req.sender
    assert "Rechnung" in req.raw_text
    assert "dmarc=pass" in req.auth_results


def test_parse_form_no_headers():
    req = parse_form("Mein Internet ist seit gestern tot.")
    assert req.source == Source.FORM
    assert req.auth_results == ""


def test_trust_pass():
    v = sender_trust(parse_eml(EML_PASS))
    assert v.level == TrustLevel.PASS


def test_trust_unknown_without_headers():
    v = sender_trust(parse_form("Hallo, ich brauche Hilfe."))
    assert v.level == TrustLevel.UNKNOWN
    assert "no Authentication-Results" in v.reason


# --- generic phishing signals ---------------------------------------------


def test_phishing_lookalike_and_urgency_flagged():
    v = detect_phishing(parse_eml(EML_PHISH))
    assert v.suspected
    assert "lookalike_domain" in v.matched_rules


def test_benign_own_portal_with_pass_not_flagged():
    eml = (
        "From: service@nordtel.de\n"
        "Subject: Ihre Rechnung steht bereit\n"
        "Authentication-Results: mx.nordtel.de; spf=pass; dkim=pass; dmarc=pass\n\n"
        "Ihre aktuelle Rechnung finden Sie im Kundenportal: https://portal.nordtel.de/rechnungen\n"
    )
    v = detect_phishing(parse_eml(eml))
    assert not v.suspected


def test_benign_mahnung_not_flagged():
    # A dunning ("Mahnung") notice from the real domain under pass auth, no link
    # trickery -- must not flag just because it mentions payment.
    eml = (
        "From: abrechnung@nordtel.de\n"
        "Subject: Zahlungserinnerung\n"
        "Authentication-Results: mx.nordtel.de; spf=pass; dkim=pass; dmarc=pass\n\n"
        "Freundliche Erinnerung: Ihre Rechnung ist noch offen. Details im Portal.\n"
    )
    v = detect_phishing(parse_eml(eml))
    assert not v.suspected


def test_punycode_lookalike_flagged():
    # xn--nrdtel-n2a.de decodes to nördtel.de -> folds to nordtel.de -> lookalike.
    eml = (
        "From: billing@xn--nrdtel-n2a.de\n"
        "Subject: Konto\n"
        "Authentication-Results: mx.nordtel.de; spf=fail; dkim=fail; dmarc=fail\n\n"
        "Bitte sofort Ihre Zahlungsdaten bestätigen: http://xn--nrdtel-n2a.de/verify\n"
    )
    v = detect_phishing(parse_eml(eml))
    assert v.suspected
    assert "lookalike_domain" in v.matched_rules


def test_edit_distance_lookalike_flagged():
    # "nordtei.de" is edit distance 1 from nordtel.de and does not homoglyph-fold
    # to it, so it must be caught by the lookalike signal itself.
    eml = (
        "From: info@nordtei.de\n"
        "Subject: Info\n"
        "Authentication-Results: mx.nordtel.de; spf=pass; dkim=pass; dmarc=pass\n\n"
        "Bitte im Portal anmelden: http://nordtei.de/login\n"
    )
    v = detect_phishing(parse_eml(eml))
    assert v.suspected
    assert "lookalike_domain" in v.matched_rules


def test_link_text_href_mismatch_flagged():
    eml = (
        "From: service@nordtel.de\n"
        "Subject: Info\n"
        "Authentication-Results: mx.nordtel.de; spf=pass; dkim=pass; dmarc=pass\n\n"
        "Bitte hier bestätigen: [nordtel.de](http://evil-collect.example/login)\n"
    )
    v = detect_phishing(parse_eml(eml))
    assert v.suspected
    assert "link_text_href_mismatch" in v.matched_rules


def test_single_weak_signal_does_not_flag():
    # auth missing alone (one weak signal) must stay below threshold.
    req = parse_form("Nur eine allgemeine Frage zu meinem Tarif.")
    v = detect_phishing(req)
    assert not v.suspected


def test_own_domains_config_present():
    assert "nordtel.de" in OWN_DOMAINS
