"""Step 1: ingest and sender trust (R1-R5).

Parse an .eml file or raw form text, read SPF/DKIM/DMARC from the
Authentication-Results header, and apply rule-based phishing heuristics.
Everything here is rule-based and explainable -- no LLM touches the trust verdict.
"""

from __future__ import annotations

import re
from email import message_from_string
from email.message import Message

from .models import (
    PhishingVerdict,
    Request,
    Source,
    TrustLevel,
    TrustVerdict,
)

# Reference phishing phrasings used in docs/tests. IMPORTANT: these are written NOT
# to match the dataset generator's phishing bodies (`data/generator.py`); the
# phishing detector itself is rule-based (regex), so these are only reference
# examples and the overlap check uses them to confirm the detector's examples are
# not copied from the corpus. Synthetic, obviously fake, no real brand.
PHISHING_EXEMPLARS: list[str] = [
    "Wir konnten Ihre letzte Abbuchung nicht verarbeiten, bestaetigen Sie Ihre Daten unter dem Link.",
    "Sicherheitsabteilung: ungewoehnliche Anmeldung erkannt, verifizieren Sie Ihr Konto sofort.",
    "Ihr Anschluss wird in Kuerze deaktiviert; zur Reaktivierung hier die Zahlung freigeben.",
]

# --- parsing ---------------------------------------------------------------


def _body_from_message(msg: Message) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.is_multipart():
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    parts.append(payload.decode(charset, errors="replace"))
        return "\n".join(parts)
    payload = msg.get_payload(decode=True)
    if payload is not None:
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return msg.get_payload() or ""


def parse_eml(raw: str) -> Request:
    """Parse an .eml string into a Request (R1)."""
    msg = message_from_string(raw)
    subject = str(msg.get("Subject", "")).strip()
    sender = str(msg.get("From", "")).strip()
    auth = str(msg.get("Authentication-Results", "")).strip()
    body = _body_from_message(msg).strip()
    # If parsing produced no body and no headers, fall back to form text (R2 / error handling).
    if not body and not subject and not sender:
        return parse_form(raw)
    return Request(
        source=Source.EML,
        raw_text=body or raw,
        subject=subject,
        sender=sender,
        auth_results=auth,
    )


def parse_form(text: str) -> Request:
    """Accept raw form text without email headers (R2)."""
    return Request(source=Source.FORM, raw_text=text.strip())


# --- sender trust (SPF/DKIM/DMARC) -----------------------------------------

_MECH_RE = {
    "spf": re.compile(r"spf=(\w+)", re.IGNORECASE),
    "dkim": re.compile(r"dkim=(\w+)", re.IGNORECASE),
    "dmarc": re.compile(r"dmarc=(\w+)", re.IGNORECASE),
}


def _read_mechanisms(auth_results: str) -> dict[str, str]:
    out = {"spf": "none", "dkim": "none", "dmarc": "none"}
    for key, rx in _MECH_RE.items():
        m = rx.search(auth_results)
        if m:
            out[key] = m.group(1).lower()
    return out


def sender_trust(request: Request) -> TrustVerdict:
    """Produce an explainable sender-trust verdict (R2, R3)."""
    if not request.auth_results:
        return TrustVerdict(
            level=TrustLevel.UNKNOWN,
            reason="no Authentication-Results header; cannot verify sender",
        )

    mech = _read_mechanisms(request.auth_results)
    spf, dkim, dmarc = mech["spf"], mech["dkim"], mech["dmarc"]

    passed = [k for k, v in mech.items() if v == "pass"]
    failed = [k for k, v in mech.items() if v in ("fail", "softfail", "permerror")]

    if dmarc == "pass" and spf == "pass" and dkim == "pass":
        level = TrustLevel.PASS
        reason = "SPF, DKIM and DMARC all pass"
    elif "dmarc" in [k for k, v in mech.items() if v == "fail"] or len(failed) >= 2:
        level = TrustLevel.FAIL
        reason = f"authentication failed: {', '.join(failed) or 'dmarc'}"
    elif passed:
        level = TrustLevel.PARTIAL
        reason = f"partial authentication: pass={passed}, weak={failed or 'none'}"
    else:
        level = TrustLevel.FAIL
        reason = "no authentication mechanism passed"

    return TrustVerdict(level=level, reason=reason, spf=spf, dkim=dkim, dmarc=dmarc)


# --- phishing heuristics (Round 3: generic signals only) --------------------
#
# The v2 detector carried `_LOOKALIKE_DOMAIN`, a regex hard-coded with the dataset
# generator's own throwaway domains. That made the detector cheat: it scored
# against the exact domains the generator used, so a review rightly flagged it.
# Round 3 deletes that and uses only GENERIC signals that don't know the corpus:
#
#   1. Authentication-Results fail or missing (from sender_trust).
#   2. A link domain that is a LOOKALIKE of one of NordTel's OWN domains only
#      (OWN_DOMAINS below): punycode/IDN decode + homoglyph fold, then an exact
#      match (benign) or an edit distance <= 2 (lookalike). Brand-new unrelated
#      domains are NOT flagged on name alone.
#   3. Link TEXT vs href domain mismatch (classic display-URL trick).
#   4. Urgency AND a payment/credential request in the same message.
#
# Signals are weighted and scored against a documented threshold. A single weak
# signal, or an own-portal link under auth=pass, must not flag.

# NordTel's own domains. The ONLY brand knowledge the detector has -- so it can
# recognise impersonation of the company it protects, not the attacker's domains.
OWN_DOMAINS = ("nordtel.de", "portal.nordtel.de", "mx.nordtel.de")
# The registrable domains NordTel actually owns -- a combo-squat is only suspicious
# when the brand appears in a domain that is NOT one of these.
OWN_REGISTRABLE = ("nordtel.de",)
# The brand label(s) an attacker would combo-squat (e.g. nordtel-billing.co).
OWN_BRAND_LABELS = ("nordtel",)

_URGENCY = re.compile(
    r"\b(sofort|umgehend|dringend|sofortig|binnen|innerhalb von \d+\s*(stunden|minuten)|"
    r"letzte warnung|final warning|immediately|urgent|asap|within \d+\s*hours?)\b",
    re.IGNORECASE,
)
_PAYMENT_OR_CRED = re.compile(
    r"\b(zahlen|überweis\w*|bezahlen|zahlung|bankdaten|kontodaten|iban|kreditkarte|"
    r"passwort|anmeldedaten|verifizieren|verify|bestätigen sie ihre daten|"
    r"konto (?:gesperrt|wird gesperrt)|account (?:locked|suspended)|reactivate|"
    r"zahlungsdaten|payment details|confirm your (?:account|details))\b",
    re.IGNORECASE,
)

# Markdown/HTML link with visible text and an href, e.g. [NordTel](http://evil.ru)
# or <a href="http://evil.ru">nordtel.de</a>.
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_HTML_LINK = re.compile(r'<a\s+[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_URL = re.compile(r"https?://([a-z0-9.\-]+)", re.IGNORECASE)

_HOMO = {
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t",
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c",
    "\u0456": "i", "\u0445": "x", "\u03bf": "o",
}


def _fold(s: str) -> str:
    return "".join(_HOMO.get(ch, ch) for ch in s.lower())


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[len(b)]


def _decode_idn(host: str) -> str:
    """Decode a punycode/IDN host to unicode so a homoglyph domain is comparable."""
    try:
        return host.encode("ascii").decode("idna") if "xn--" in host else host
    except (UnicodeError, ValueError):
        return host


def _registrable(host: str) -> str:
    """Last two labels, a cheap stand-in for the registrable domain."""
    host = host.strip().lower().rstrip(".")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _domain_relation(host: str) -> str:
    """Classify a host against OWN_DOMAINS: 'own', 'lookalike', or 'unrelated'."""
    decoded = _decode_idn(host)
    folded = _fold(decoded)
    reg = _registrable(folded)
    own_regs = {_registrable(_fold(d)) for d in OWN_DOMAINS}
    full_own = {_fold(d) for d in OWN_DOMAINS}
    if folded in full_own or reg in own_regs:
        return "own"
    # Lookalike: close to an own registrable domain but not equal.
    for own in own_regs:
        if _edit_distance(reg, own) <= 2 and reg != own:
            return "lookalike"
    return "unrelated"


def _dehyphenate(s: str) -> str:
    """Strip hyphens, dots and spaces so 'n-o-r-d-t-e-l' and 'nordtel-billing'
    collapse: the attacker's separators no longer hide the brand."""
    return re.sub(r"[-.\s_]", "", s)


def _is_combo_squat(host: str) -> bool:
    """Combo-squat: an own BRAND label appears inside a FOREIGN registrable domain
    (Round 4 #6).

    De-hyphenate and homoglyph-fold the host, take its registrable domain, and if
    that domain is not one NordTel owns but still contains the brand label
    ('nordtel'), it is impersonation by combination/separation:
      nordtel-billing.co, nordtel-kundenservice.com, n-o-r-d-t-e-l.de (foreign TLD).
    An exact own domain (nordtel.de) is never a combo-squat.
    """
    decoded = _decode_idn(host)
    folded = _fold(decoded)
    reg = _registrable(folded)
    # "own" is an EXACT registrable match (hyphens are part of a domain, so
    # n-o-r-d-t-e-l.de is NOT nordtel.de -- it is a separate registration).
    if reg in OWN_REGISTRABLE:
        return False
    reg_squashed = _dehyphenate(reg)
    return any(_dehyphenate(lbl) in reg_squashed for lbl in OWN_BRAND_LABELS)


def _links(text: str) -> list[tuple[str, str]]:
    """Return (visible_text, href) pairs for markdown/HTML links."""
    pairs = [(vis, href) for vis, href in _MD_LINK.findall(text)]
    pairs += [(vis, href) for href, vis in _HTML_LINK.findall(text)]
    return pairs


# Signal weights and the decision threshold. Documented so the gate is auditable.
# A single weak signal (score 1) stays below THRESHOLD (2); it takes a strong
# signal (lookalike/mismatch, weight 2) or two weak ones to flag.
PHISH_WEIGHTS = {
    "auth_fail": 1,
    "auth_missing": 1,
    "lookalike_domain": 2,
    "combo_squat_domain": 2,
    "link_text_href_mismatch": 2,
    "urgency_and_payment": 1,
}
PHISH_THRESHOLD = 2


def detect_phishing(request: Request, trust: "TrustVerdict | None" = None) -> PhishingVerdict:
    """Generic, corpus-agnostic phishing scoring (R4, R5; Round 3).

    `trust` lets the caller pass the sender-trust verdict so auth is reused; if not
    given it is computed here.
    """
    trust = trust or sender_trust(request)
    text = f"{request.subject}\n{request.raw_text}"
    signals: dict[str, int] = {}

    # (1) Authentication.
    if trust.level == TrustLevel.FAIL:
        signals["auth_fail"] = PHISH_WEIGHTS["auth_fail"]
    elif trust.level == TrustLevel.UNKNOWN and request.source == Source.EML:
        signals["auth_missing"] = PHISH_WEIGHTS["auth_missing"]

    # (2) Lookalike of an OWN domain, across every URL and the sender host.
    hosts = list(_URL.findall(text))
    if "@" in request.sender:
        hosts.append(request.sender.rsplit("@", 1)[-1].strip(" >"))
    relations = {h: _domain_relation(h) for h in hosts}
    if any(rel == "lookalike" for rel in relations.values()):
        signals["lookalike_domain"] = PHISH_WEIGHTS["lookalike_domain"]

    # (2b) Combo-squat: the brand label inside a foreign registrable domain. This
    # fires independently of auth, which is the point -- an authenticated
    # lookalike (compromised sender under auth=pass) is still caught.
    if any(_is_combo_squat(h) for h in hosts):
        signals["combo_squat_domain"] = PHISH_WEIGHTS["combo_squat_domain"]

    # (3) Link text claims one domain, href points to another.
    for vis, href in _links(text):
        m = _URL.search(href)
        if not m:
            continue
        href_host = _registrable(_fold(m.group(1)))
        vis_m = _URL.search(vis) or re.search(r"([a-z0-9.\-]+\.[a-z]{2,})", vis, re.IGNORECASE)
        if vis_m:
            vis_host = _registrable(_fold(vis_m.group(1)))
            if vis_host and href_host and vis_host != href_host:
                signals["link_text_href_mismatch"] = PHISH_WEIGHTS["link_text_href_mismatch"]

    # (4) Urgency AND a payment/credential ask together.
    if _URGENCY.search(text) and _PAYMENT_OR_CRED.search(text):
        signals["urgency_and_payment"] = PHISH_WEIGHTS["urgency_and_payment"]

    # An own-portal link under passing auth is explicitly safe: if the only domains
    # are own and auth passed, do not flag regardless of other weak wording.
    only_own = hosts and all(rel == "own" for rel in relations.values())
    if only_own and trust.level == TrustLevel.PASS:
        return PhishingVerdict(
            suspected=False,
            reason="own-portal link(s) with passing authentication; not phishing",
            matched_rules=[],
        )

    score = sum(signals.values())
    matched = sorted(signals)
    if score >= PHISH_THRESHOLD:
        return PhishingVerdict(
            suspected=True,
            reason=(f"phishing score {score} >= {PHISH_THRESHOLD} from "
                    f"{matched}"),
            matched_rules=matched,
        )
    return PhishingVerdict(
        suspected=False,
        reason=f"phishing score {score} < {PHISH_THRESHOLD} ({matched or 'no signals'})",
        matched_rules=matched,
    )
