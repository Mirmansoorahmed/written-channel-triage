from datetime import datetime

from triage.models import (
    Classification,
    InjectionVerdict,
    PhishingVerdict,
    PolicyDecision,
    TrustLevel,
    TrustVerdict,
)
from triage.output import DISCLOSURE, build_output, is_out_of_hours, next_opening_eta

TRUST = TrustVerdict(level=TrustLevel.PASS, reason="all pass")
PHISH = PhishingVerdict(suspected=False, reason="clean")
CLS = Classification(category="Rechnung", confidence=0.5, fields={"kundennummer": "[[CUSTOMER_1]]"})
INJ = InjectionVerdict(detected=False, reason="clean")
POL = PolicyDecision(allowed=True, reason="read-only")


def test_in_hours_not_queued():
    now = datetime(2026, 10, 30, 10, 0)
    out = build_output(TRUST, PHISH, CLS, INJ, POL, now)
    assert not out.queued
    assert out.disclosure == DISCLOSURE


def test_out_of_hours_queued_with_eta():
    now = datetime(2026, 10, 30, 2, 0)
    assert is_out_of_hours(now)
    out = build_output(TRUST, PHISH, CLS, INJ, POL, now)
    assert out.queued
    assert out.eta.startswith("2026-10-30T07:00")


def test_eta_rolls_to_next_day_after_close():
    now = datetime(2026, 10, 30, 23, 30)
    eta = next_opening_eta(now)
    assert eta.startswith("2026-10-31T07:00")


def test_handoff_lists_flags():
    cls = Classification(category="Kündigung", confidence=0.4, missing_fields=["kündigungsdatum"])
    pol = PolicyDecision(allowed=False, reason="account change")
    out = build_output(TRUST, PHISH, cls, INJ, pol, datetime(2026, 10, 30, 12, 0))
    assert "missing:kündigungsdatum" in out.handoff_summary
