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


# --- phishing heuristics ----------------------------------------------------

# Obviously-legitimate-looking cues an attacker uses, in German + common patterns.
_URGENT_PAYMENT = re.compile(
    r"(sofort|umgehend|dringend|innerhalb von \d+ stunden).{0,40}"
    r"(zahlen|überweis|bezahlen|zahlung|konto gesperrt|sperrung)",
    re.IGNORECASE | re.DOTALL,
)
_FAKE_INVOICE = re.compile(
    r"(rechnung|mahnung|offene forderung).{0,60}(anbei|im anhang|klicken|link|pdf)",
    re.IGNORECASE | re.DOTALL,
)
_PAYMENT_LINK = re.compile(
    r"(https?://|www\.)\S*(zahlung|payment|pay|rechnung|invoice|verify|login|konto)\S*",
    re.IGNORECASE,
)

# A lookalike domain uses digits/odd TLDs or hyphenated brand-ish tokens.
_LOOKALIKE_DOMAIN = re.compile(
    r"(https?://|www\.|@)[a-z0-9.-]*"
    r"(n0rdtel|nordte1|nord-tel|norde?tel\.(ru|xyz|top|click|info|zip))",
    re.IGNORECASE,
)


def detect_phishing(request: Request) -> PhishingVerdict:
    """Rule-based phishing heuristics (R4, R5)."""
    text = f"{request.subject}\n{request.sender}\n{request.raw_text}"
    matched: list[str] = []

    if _FAKE_INVOICE.search(text):
        matched.append("fake_invoice")
    if _URGENT_PAYMENT.search(text):
        matched.append("urgent_payment")
    if _PAYMENT_LINK.search(text):
        matched.append("payment_link")
    if _LOOKALIKE_DOMAIN.search(text):
        matched.append("lookalike_domain")

    if matched:
        return PhishingVerdict(
            suspected=True,
            reason="matched phishing pattern(s): " + ", ".join(matched),
            matched_rules=matched,
        )
    return PhishingVerdict(suspected=False, reason="no phishing pattern matched")
