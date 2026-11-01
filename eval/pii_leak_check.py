"""Fuzzy ground-truth PII leak check (Round 3, #7).

Runs the masker over ALL test and unseen items and fuzzy-searches every
ground-truth PII value (both the pre-typo and post-typo forms the generator
records) in the masked text:
  * case/whitespace-normalised substring match, OR
  * partial ratio >= 0.85, OR
  * (for IBAN-like values) any surviving fragment of 8+ characters.

Prints and returns a summary {checked, items_with_leak, leaks, examples}. The
harness embeds the same summary in eval/results-v2.json. Target 0 leaks; the real
number is reported either way.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
TRAIN_PATH = os.path.join(ROOT, "data", "train.jsonl")
DEV_PATH = os.path.join(ROOT, "data", "dev.jsonl")
TEST_PATH = os.path.join(ROOT, "data", "test.jsonl")
UNSEEN_PATH = os.path.join(HERE, "unseen", "unseen.jsonl")


def _load(path: str) -> list[dict]:
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if not obj.get("_meta"):
                    rows.append(obj)
    return rows


def run_check() -> dict:
    from triage import pii

    rows = [("train", r) for r in _load(TRAIN_PATH)]
    rows += [("dev", r) for r in _load(DEV_PATH)]
    rows += [("test", r) for r in _load(TEST_PATH)]
    rows += [("unseen", r) for r in _load(UNSEEN_PATH)]

    checked = 0
    items_with_leak = 0
    total_leaks = 0
    examples: list[dict] = []
    for split, r in rows:
        # Round 4 #5: check EVERY item that has ground-truth PII, not only those
        # flagged has_pii (a non-PII item can still carry a signature name).
        truth = r.get("pii_truth") or []
        if not truth:
            continue
        checked += 1
        masked = pii.mask(r["text"]).masked_text
        leaks = pii.fuzzy_ground_truth_leaks(masked, truth)
        if leaks:
            items_with_leak += 1
            total_leaks += len(leaks)
            if len(examples) < 15:
                examples.append({
                    "split": split, "id": r["id"],
                    "leaked": leaks,
                    "masked_excerpt": masked[:160].replace("\n", " "),
                })
    return {
        "checked_items": checked,
        "items_with_leak": items_with_leak,
        "total_leaked_values": total_leaks,
        "examples": examples,
        "method": "fuzzy ground-truth: normalised substring OR partial_ratio>=0.85 "
                  "OR IBAN fragment>=8 chars, against pre- and post-typo values",
    }


def main() -> int:
    summary = run_check()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["items_with_leak"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
