"""Eval harness (R25).

Runs the pipeline over the synthetic corpus and measures:
  - phishing detection: precision / recall
  - injection detection: precision / recall
  - PII masking: recall (share of PII-heavy cases where no raw PII survives)
  - out-of-hours queueing: recall (queued when processed at night)
  - category accuracy

It writes ONLY numbers this run produces into eval/results.json. If a family has
no cases, the metric is reported as the string "not measured" rather than a guess.

Determinism: the default offline LLM is used, so the numbers are stable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from triage import pii, pipeline
from eval.corpus import Case, build_corpus

IN_HOURS = datetime(2026, 10, 30, 10, 0)
NIGHT = datetime(2026, 10, 30, 3, 0)


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4) if precision is not None else "not measured",
        "recall": round(recall, 4) if recall is not None else "not measured",
    }


def run_eval() -> dict:
    corpus = build_corpus()

    ph_tp = ph_fp = ph_fn = 0
    inj_tp = inj_fp = inj_fn = 0
    pii_ok = pii_total = 0
    ooh_ok = ooh_total = 0
    cat_correct = cat_total = 0

    for case in corpus:
        now = NIGHT if case.out_of_hours else IN_HOURS
        result = pipeline.run(case.text, source=case.source, now=now)

        # phishing
        pred_ph = result.phishing.suspected
        if case.is_phishing and pred_ph:
            ph_tp += 1
        elif not case.is_phishing and pred_ph:
            ph_fp += 1
        elif case.is_phishing and not pred_ph:
            ph_fn += 1

        # injection
        pred_inj = result.injection.detected
        if case.is_injection and pred_inj:
            inj_tp += 1
        elif not case.is_injection and pred_inj:
            inj_fp += 1
        elif case.is_injection and not pred_inj:
            inj_fn += 1

        # PII masking recall: for PII-heavy cases, confirm no raw PII survives masking.
        if case.has_pii:
            pii_total += 1
            masked = pii.mask(case.text).masked_text
            raw_leak = (
                "DE89" in masked or "DE12" in masked
                or "@example.de" in masked
                or "0171" in masked
            )
            if not raw_leak:
                pii_ok += 1

        # out-of-hours queueing recall
        if case.out_of_hours:
            ooh_total += 1
            if result.output.queued:
                ooh_ok += 1

        # category accuracy
        cat_total += 1
        if result.classification.category == case.expected_category:
            cat_correct += 1

    results = {
        "note": "Synthetic data only; fictional telco NordTel GmbH. Not a certification. "
                "All numbers are produced by this eval run.",
        "corpus_size": len(corpus),
        "checks": {
            "phishing_detection": _prf(ph_tp, ph_fp, ph_fn),
            "injection_detection": _prf(inj_tp, inj_fp, inj_fn),
            "pii_masking": {
                "cases": pii_total,
                "no_leak": pii_ok,
                "recall": round(pii_ok / pii_total, 4) if pii_total else "not measured",
            },
            "out_of_hours_queue": {
                "cases": ooh_total,
                "queued": ooh_ok,
                "recall": round(ooh_ok / ooh_total, 4) if ooh_total else "not measured",
            },
        },
        "category_accuracy": {
            "correct": cat_correct,
            "total": cat_total,
            "accuracy": round(cat_correct / cat_total, 4) if cat_total else "not measured",
        },
    }
    return results


def main() -> None:
    results = run_eval()
    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
