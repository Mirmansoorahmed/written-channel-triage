from triage.models import InjectionVerdict
from triage.policy import gate

CLEAN = InjectionVerdict(detected=False, reason="clean")
HIT = InjectionVerdict(detected=True, reason="matched", matched_rules=["ignore_previous"])


def test_readonly_allowed():
    d = gate("Rechnung", CLEAN)
    assert d.allowed
    assert d.pending_approval is None


def test_cancellation_creates_pending_approval():
    d = gate("Kündigung", CLEAN)
    assert not d.allowed
    assert d.pending_approval is not None
    assert d.pending_approval.action == "cancellation"


def test_tariff_change_never_executed():
    d = gate("Tarifwechsel", CLEAN)
    assert not d.allowed
    assert d.pending_approval.action == "tariff_change"


def test_address_change_pending():
    d = gate("Umzug", CLEAN)
    assert not d.allowed
    assert d.pending_approval.action == "address_change"


def test_injection_blocks_even_readonly():
    d = gate("Rechnung", HIT)
    assert not d.allowed
    assert d.pending_approval.action == "blocked_injection"
