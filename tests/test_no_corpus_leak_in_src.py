"""Guard: no generator domain or payload may appear in src/ (Round 3, #2/#3).

The phishing and injection detectors must not be tuned to the exact domains and
payloads the dataset generator uses, otherwise they "cheat" on the eval. This test
reads the generator's own lists and fails if any of those strings is found in any
source module under src/triage/.
"""

from __future__ import annotations

import os

from data import generator as gen

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "triage")


def _src_blob() -> str:
    parts = []
    for root, _dirs, files in os.walk(os.path.normpath(SRC_DIR)):
        for fn in files:
            if fn.endswith(".py"):
                with open(os.path.join(root, fn), encoding="utf-8") as f:
                    parts.append(f.read())
    return "\n".join(parts).lower()


def test_no_generator_domain_in_src():
    blob = _src_blob()
    offenders = [d for d in gen._BAD_DOMAINS if d.lower() in blob]
    assert not offenders, f"generator domains leaked into src/: {offenders}"


def test_no_generator_payload_in_src():
    blob = _src_blob()
    offenders = [p for p in gen._INJECTION_PAYLOADS if p.lower() in blob]
    assert not offenders, f"generator payloads leaked into src/: {offenders}"


def test_no_generator_phish_body_in_src():
    blob = _src_blob()
    # Compare on a distinctive fragment of each phishing body (strip the {d} slot).
    offenders = []
    for body in gen._PHISH_BODIES:
        frag = body.split("{d}")[0].strip().lower()
        if len(frag) > 15 and frag in blob:
            offenders.append(frag)
    assert not offenders, f"generator phishing bodies leaked into src/: {offenders}"
