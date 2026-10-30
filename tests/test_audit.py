import json

import pytest

from triage.audit import append_entry, verify_chain


def test_chain_builds_and_verifies(tmp_path):
    p = str(tmp_path / "audit.jsonl")
    append_entry(p, {"event": "triage", "category": "Rechnung"})
    append_entry(p, {"event": "triage", "category": "Störung"})
    append_entry(p, {"event": "triage", "category": "Umzug"})
    assert verify_chain(p)


def test_tamper_breaks_chain(tmp_path):
    p = str(tmp_path / "audit.jsonl")
    append_entry(p, {"event": "a"})
    append_entry(p, {"event": "b"})
    lines = open(p, encoding="utf-8").read().splitlines()
    rec = json.loads(lines[0])
    rec["payload"]["event"] = "tampered"
    lines[0] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    assert not verify_chain(p)


def test_refuses_raw_iban(tmp_path):
    p = str(tmp_path / "audit.jsonl")
    with pytest.raises(ValueError):
        append_entry(p, {"note": "IBAN DE89370400440532013000"})


def test_refuses_raw_email(tmp_path):
    p = str(tmp_path / "audit.jsonl")
    with pytest.raises(ValueError):
        append_entry(p, {"note": "contact max@example.de"})


def test_allows_placeholders(tmp_path):
    p = str(tmp_path / "audit.jsonl")
    h = append_entry(p, {"fields": {"iban": "[[IBAN_1]]", "mail": "[[EMAIL_1]]"}})
    assert len(h) == 64
    assert verify_chain(p)
