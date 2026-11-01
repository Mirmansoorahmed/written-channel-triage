"""Train the learned classifiers (Round 3, `make train`).

Fits the category and injection logistic-regression heads on data/train.jsonl ONLY,
chooses the injection decision threshold on data/dev.jsonl ONLY, and writes:

  models/category_lr.joblib
  models/injection_lr.joblib
  models/manifest.json   (seed, library versions, embedding model, labels,
                          sha256 of train.jsonl, dev-chosen injection threshold)

Deterministic: fixed random_state, sorted labels, no network beyond the (cached)
embedding model. Needs the `learned` extra (scikit-learn, joblib, numpy,
sentence-transformers); it is meant to run on your machine, not in CI.

The category model is trained on category-bearing families only (normal, pii_heavy,
out_of_hours, injection_negative, phishing_negative) -- the attack families
(phishing, injection) are detector problems, not category problems.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA_DIR = os.path.join(ROOT, "data")
MODELS_DIR = os.path.join(ROOT, "models")

CATEGORY_FAMILIES = {
    "normal", "pii_heavy", "out_of_hours", "injection_negative", "phishing_negative",
}


def _load(split: str) -> list[dict]:
    rows = []
    with open(os.path.join(DATA_DIR, f"{split}.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if not obj.get("_meta"):
                    rows.append(obj)
    return rows


def _versions() -> dict:
    import sklearn
    import numpy

    out = {"scikit_learn": sklearn.__version__, "numpy": numpy.__version__, "python": sys.version.split()[0]}
    try:
        import sentence_transformers as st
        out["sentence_transformers"] = st.__version__
    except Exception:
        out["sentence_transformers"] = "unknown"
    return out


def _choose_injection_threshold(model, dev_rows: list[dict], min_precision: float = 0.9) -> dict:
    """Pick the threshold on dev maximising F1 subject to precision >= min_precision.

    Scores the model on pii.mask(text) -- the same text the pipeline feeds it at
    serve time (Round 4 #7), so the chosen threshold matches evaluation.
    """
    from triage import pii

    scored = [(model.proba(pii.mask(r["text"]).masked_text), bool(r["is_injection"]))
              for r in dev_rows]
    best = {"threshold": 0.5, "f1": -1.0, "precision": 0.0, "recall": 0.0}
    for i in range(1, 100):
        thr = i / 100
        tp = sum(1 for p, y in scored if p >= thr and y)
        fp = sum(1 for p, y in scored if p >= thr and not y)
        fn = sum(1 for p, y in scored if p < thr and y)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        if prec >= min_precision and f1 > best["f1"]:
            best = {"threshold": round(thr, 2), "f1": round(f1, 4),
                    "precision": round(prec, 4), "recall": round(rec, 4)}
    # If nothing met the precision floor, fall back to best F1 overall and say so.
    if best["f1"] < 0:
        for i in range(1, 100):
            thr = i / 100
            tp = sum(1 for p, y in scored if p >= thr and y)
            fp = sum(1 for p, y in scored if p >= thr and not y)
            fn = sum(1 for p, y in scored if p < thr and y)
            prec = tp / (tp + fp) if (tp + fp) else 0.0
            rec = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
            if f1 > best["f1"]:
                best = {"threshold": round(thr, 2), "f1": round(f1, 4),
                        "precision": round(prec, 4), "recall": round(rec, 4),
                        "note": "precision floor not reachable on dev"}
    best["min_precision_target"] = min_precision
    return best


def train(embedder=None) -> dict:
    from triage import learned, pii

    embedder = embedder or learned.E5Embedder()
    train_rows = _load("train")
    dev_rows = _load("dev")

    def masked(r):
        # Round 4 #7: train on pii.mask(text), the SAME text seen at evaluation.
        return pii.mask(r["text"]).masked_text

    # Category model: category-bearing families only; calibrate on DEV (prefit).
    cat_rows = [r for r in train_rows if r["family"] in CATEGORY_FAMILIES]
    dev_cat_rows = [r for r in dev_rows if r["family"] in CATEGORY_FAMILIES]
    cat_model = learned.fit_category_model(
        [masked(r) for r in cat_rows], [r["category"] for r in cat_rows], embedder,
        calib_texts=[masked(r) for r in dev_cat_rows],
        calib_labels=[r["category"] for r in dev_cat_rows],
    )

    # Injection model: every train row, labelled is_injection, on masked text.
    inj_model = learned.fit_injection_model(
        [masked(r) for r in train_rows], [bool(r["is_injection"]) for r in train_rows], embedder
    )

    os.makedirs(MODELS_DIR, exist_ok=True)
    learned.save_model(cat_model, os.path.join(MODELS_DIR, "category_lr.joblib"))
    learned.save_model(inj_model, os.path.join(MODELS_DIR, "injection_lr.joblib"))

    inj_threshold = _choose_injection_threshold(inj_model, dev_rows)

    manifest = {
        "seed": learned.RANDOM_STATE,
        "embedding_model": learned.EMBED_MODEL,
        "versions": _versions(),
        "category_labels": cat_model.labels,
        "train_sha256": learned.sha256_of(os.path.join(DATA_DIR, "train.jsonl")),
        "n_train_category": len(cat_rows),
        "n_train_injection": len(train_rows),
        "injection_threshold": inj_threshold,
        "calibration": {
            "method": "sigmoid",
            "fit_on": "dev (CalibratedClassifierCV cv='prefit'; base LR fit on train)",
        },
        "trained_on": "pii.mask(text)  -- same text as evaluation (no train/serve skew)",
        "note": "Synthetic data only; fictional NordTel GmbH. Base LR fit on train; "
                "probability calibration fit on dev; injection threshold chosen on dev.",
    }
    with open(os.path.join(MODELS_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return manifest


def main() -> None:
    manifest = train()
    print("wrote models/category_lr.joblib, models/injection_lr.joblib, models/manifest.json")
    print(f"category labels: {manifest['category_labels']}")
    print(f"injection threshold (dev): {manifest['injection_threshold']}")


if __name__ == "__main__":
    main()
