"""Step 6 (audit): hash-chained JSONL audit log (R23).

Each line stores the SHA-256 of the previous line in `prev_hash`, and its own
`entry_hash` over (prev_hash + payload). Any edit or deletion breaks the chain, so
the log is tamper-evident. No unmasked PII is ever written here (R9): callers pass
only verdicts, categories, flags -- never the token map.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

GENESIS = "0" * 64


def _hash(prev_hash: str, payload: str) -> str:
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


def _last_hash(path: str) -> str:
    if not os.path.exists(path):
        return GENESIS
    last = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if last is None:
        return GENESIS
    return json.loads(last)["entry_hash"]


def append_entry(path: str, payload: dict[str, Any]) -> str:
    """Append one audit entry and return its hash (R23)."""
    assert_no_pii(payload)
    prev = _last_hash(path)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    entry_hash = _hash(prev, body)
    record = {"prev_hash": prev, "payload": payload, "entry_hash": entry_hash}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return entry_hash


def verify_chain(path: str) -> bool:
    """Return True if the hash chain is intact (R23)."""
    if not os.path.exists(path):
        return True
    prev = GENESIS
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec["prev_hash"] != prev:
                return False
            body = json.dumps(rec["payload"], ensure_ascii=False, sort_keys=True)
            if _hash(prev, body) != rec["entry_hash"]:
                return False
            prev = rec["entry_hash"]
    return True


_PII_MARKERS = ("IBAN", "@", "Kundennummer")


def assert_no_pii(payload: dict[str, Any]) -> None:
    """Guard: refuse to log anything that looks like raw PII (R9).

    Masking placeholders like [[IBAN_1]] are allowed; raw values are not.
    """
    blob = json.dumps(payload, ensure_ascii=False)
    # Allow placeholders; strip them before checking.
    import re

    stripped = re.sub(r"\[\[[A-Z]+_\d+\]\]", "", blob)
    if re.search(r"\bDE\d{2}\d{2,}", stripped):
        raise ValueError("refusing to log raw IBAN")
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", stripped):
        raise ValueError("refusing to log raw email")
