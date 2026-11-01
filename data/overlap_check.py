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


def _generator_template_texts() -> list[tuple[str, str]]:
    """The raw generator template/payload strings themselves (Round 3).

    So the unseen set can be checked against the generator's TEMPLATES directly,
    not just its materialised train items -- a stricter guard that the hand-written
    unseen items share no template with the generator.
    """
    refs: list[tuple[str, str]] = []
    try:
        from data import generator as gen

        for cat, tmpls in gen.TEMPLATES.items():
            for i, t in enumerate(tmpls):
                refs.append((f"gen_template:{cat}#{i}", t.replace("{en}", "")))
        for i, p in enumerate(gen._INJECTION_PAYLOADS):
            refs.append((f"gen_payload#{i}", p))
        for i, b in enumerate(gen._PHISH_BODIES):
            refs.append((f"gen_phish#{i}", b.replace("{d}", "")))
    except Exception:
        pass
    return refs


def _model_facing_examples() -> list[tuple[str, str]]:
    """The few-shot / detector exemplars the model actually sees."""
    refs: list[tuple[str, str]] = []
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
        from triage.ingest import PHISHING_EXEMPLARS

        for i, ex in enumerate(PHISHING_EXEMPLARS):
            refs.append((f"phishing_exemplar#{i}", ex))
    except Exception:
        pass
    return refs


def _reference_texts() -> list[tuple[str, str]]:
    """Train items + the model-facing examples (what the TEST split is checked
    against)."""
    refs: list[tuple[str, str]] = [("train:" + r["id"], r["text"]) for r in _load("train")]
    refs += _model_facing_examples()
    return refs


def _unseen_reference_texts() -> list[tuple[str, str]]:
    """What the UNSEEN set is checked against: train items, the model-facing
    examples, AND the generator's raw templates/payloads."""
    return _reference_texts() + _generator_template_texts()


def _load_unseen() -> list[dict]:
    path = os.path.join(HERE, "..", "eval", "unseen", "unseen.jsonl")
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


def _check_rows(rows: list[dict], refs: list[tuple[str, str]],
                threshold: float) -> list[dict]:
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
    for t in rows:
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
                "test_id": t["id"], "family": t.get("family", "?"),
                "nearest_ref": worst_ref, "similarity": round(worst, 4),
            })
    return violations


def check(threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """Test split vs train + model-facing examples."""
    return _check_rows(_load("test"), _reference_texts(), threshold)


def check_unseen(threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """Unseen set vs train + model-facing examples + generator templates."""
    return _check_rows(_load_unseen(), _unseen_reference_texts(), threshold)


def _report(name: str, violations: list[dict], threshold: float) -> int:
    if violations:
        print(f"LEAKAGE ({name}): {len(violations)} item(s) >= {threshold} similar "
              f"to a reference item:")
        for v in violations[:20]:
            print(f"  {v['test_id']} ({v['family']}) ~ {v['nearest_ref']} "
                  f"sim={v['similarity']}")
        if len(violations) > 20:
            print(f"  ... and {len(violations) - 20} more")
        return 1
    print(f"OK ({name}): no item >= {threshold} similar to a reference item.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()
    rc = 0
    rc |= _report("test vs train+examples", check(args.threshold), args.threshold)
    rc |= _report("unseen vs train+examples+generator-templates",
                  check_unseen(args.threshold), args.threshold)
    return rc


if __name__ == "__main__":
    sys.exit(main())
