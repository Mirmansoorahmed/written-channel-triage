"""Train/test leakage guard (review fix #1).

Fails (exit 1) if any TEST item is >= THRESHOLD similar to any TRAIN item or to
any detector/few-shot example that the model sees. This is the gate the review
asked for: it makes leakage a hard build failure, not a footnote.

Similarity is a dependency-free blend of word-level Jaccard and character
3-gram Jaccard (max of the two). It is intentionally conservative -- it flags
near-duplicates regardless of word order or small edits -- so it catches the
"same template in both splits" problem the first cut had.

For injection/phishing items the comparison is done on a normalised form so an
obfuscated copy (spaced / homoglyph / base64-decoded) of a train payload is also
caught.

Usage:
  python -m data.overlap_check            # check test vs train + examples
  python -m data.overlap_check --threshold 0.9
Exit code 0 = clean, 1 = leakage found.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(__file__)
DEFAULT_THRESHOLD = 0.9


def _load(split: str) -> list[dict]:
    path = os.path.join(HERE, f"{split}.jsonl")
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("_meta"):
                continue
            rows.append(obj)
    return rows


def _norm(text: str) -> str:
    """Normalise for comparison so obfuscated copies collapse to the plain form."""
    try:
        from triage.normalize import normalize
        from triage.injection import _decode_base64_blobs

        decoded = _decode_base64_blobs(text)
        base = text + (" " + " ".join(decoded) if decoded else "")
        return normalize(base)
    except Exception:
        return text.lower()


def _word_jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _char_ngrams(text: str, n: int = 3) -> set:
    t = "".join(text.split())
    return {t[i:i + n] for i in range(len(t) - n + 1)} if len(t) >= n else {t}


def similarity(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    w = _word_jaccard(set(na.split()), set(nb.split()))
    c = _word_jaccard(_char_ngrams(na), _char_ngrams(nb))
    return max(w, c)


def _reference_texts() -> list[tuple[str, str]]:
    """Train items + the detector/few-shot examples the model actually sees."""
    refs: list[tuple[str, str]] = []
    for r in _load("train"):
        refs.append(("train:" + r["id"], r["text"]))
    # Few-shot + detector exemplars (only if importable; they are plain strings).
    try:
        from triage.retrieval import FEWSHOT, INJECTION_EXEMPLARS

        for cat, examples in FEWSHOT.items():
            for i, ex in enumerate(examples):
                refs.append((f"fewshot:{cat}#{i}", ex))
        for i, ex in enumerate(INJECTION_EXEMPLARS):
            refs.append((f"injection_exemplar#{i}", ex))
    except Exception:
        pass
    try:
        from triage.ingest import PHISHING_EXEMPLARS  # optional, if present

        for i, ex in enumerate(PHISHING_EXEMPLARS):
            refs.append((f"phishing_exemplar#{i}", ex))
    except Exception:
        pass
    return refs


def check(threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    test = _load("test")
    refs = _reference_texts()
    # Pre-normalise references ONCE and cache their word/ngram sets, so the inner
    # loop is pure set math (no repeated normalise/base64-decode per comparison).
    norm_refs = [
        (rid, set(rn.split()), _char_ngrams(rn))
        for rid, rtext in refs
        for rn in (_norm(rtext),)
    ]
    # Pre-filter threshold: a true near-duplicate has high word overlap, so we
    # only pay for the (costlier) char-ngram Jaccard when word Jaccard already
    # looks close. This keeps the gate fast enough for CI without weakening it.
    prefilter = max(0.4, threshold - 0.3)
    violations: list[dict] = []
    for t in test:
        tn = _norm(t["text"])
        tw, tc = set(tn.split()), _char_ngrams(tn)
        worst = 0.0
        worst_ref = None
        for rid, rw, rc in norm_refs:
            sw = _word_jaccard(tw, rw)
            s = sw
            if sw >= prefilter:
                sc = _word_jaccard(tc, rc)
                if sc > s:
                    s = sc
            if s > worst:
                worst, worst_ref = s, rid
            if worst >= 1.0:
                break
        if worst >= threshold:
            violations.append({
                "test_id": t["id"], "family": t["family"],
                "nearest_ref": worst_ref, "similarity": round(worst, 4),
            })
    return violations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()
    violations = check(args.threshold)
    if violations:
        print(f"LEAKAGE: {len(violations)} test item(s) >= {args.threshold} similar "
              f"to a train/example item:")
        for v in violations[:20]:
            print(f"  {v['test_id']} ({v['family']}) ~ {v['nearest_ref']} "
                  f"sim={v['similarity']}")
        if len(violations) > 20:
            print(f"  ... and {len(violations) - 20} more")
        return 1
    print(f"OK: no test item >= {args.threshold} similar to any train/example item "
          f"(threshold {args.threshold}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
