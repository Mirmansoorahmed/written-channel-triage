"""Trained classifiers on multilingual embeddings (Round 3, System D/E).

Two logistic-regression heads on top of `intfloat/multilingual-e5-small`
embeddings:
  (a) intent category  -- 10-way, the System D classifier.
  (b) injection yes/no -- a binary detector used by injection.py.

Design rules the review asked for:
  * Fit ONLY on data/train.jsonl. Thresholds are chosen on data/dev.jsonl.
  * Deterministic: fixed `random_state`, sorted labels, no network at fit time
    beyond the (cached) embedding model, and the artifacts are byte-stable for a
    given input.
  * Calibrated: the category model is wrapped in CalibratedClassifierCV (sigmoid)
    so its probabilities are usable for a human-review threshold.
  * Offline-testable: the embedder is injected. Tests pass a deterministic
    hash-based fake, so no model download happens in CI. sklearn / joblib / numpy
    are imported lazily inside the functions that need them.

Artifacts (written by eval/train_models.py):
  models/category_lr.joblib     the calibrated category classifier
  models/injection_lr.joblib    the binary injection classifier
  models/manifest.json          seed, versions, embedding model, labels,
                                sha256(train.jsonl), dev-chosen injection threshold
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

RANDOM_STATE = 20251031
EMBED_MODEL = "intfloat/multilingual-e5-small"


# --- embedder -------------------------------------------------------------


class E5Embedder:
    """Lazy wrapper around sentence-transformers multilingual-e5-small.

    e5 expects a "query:" prefix for short inputs; we use that for all items so
    train and inference match. Returns an L2-normalised float32 matrix.
    """

    model_name = EMBED_MODEL

    def __init__(self, model=None):
        self._model = model

    def _get(self):
        if self._model is not None:
            return self._model
        from sentence_transformers import SentenceTransformer  # lazy

        self._model = SentenceTransformer(EMBED_MODEL)
        return self._model

    def encode(self, texts: list[str]):
        import numpy as np  # lazy

        prefixed = [f"query: {t}" for t in texts]
        vecs = np.asarray(self._get().encode(prefixed), dtype="float32")
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms


# --- category classifier (System D) ---------------------------------------


@dataclass
class LearnedCategoryModel:
    """A calibrated LR over embeddings, plus the embedder used to featurise text."""

    clf: object          # fitted CalibratedClassifierCV
    labels: list[str]
    embedder: object

    def predict(self, text: str) -> tuple[str, float]:
        """Return (label, calibrated_probability_of_that_label)."""
        probs = self.predict_proba(text)
        best = max(probs, key=probs.get)
        return best, probs[best]

    def predict_proba(self, text: str) -> dict[str, float]:
        import numpy as np  # lazy

        x = self.embedder.encode([text])
        p = self.clf.predict_proba(x)[0]
        order = list(self.clf.classes_)
        return {str(order[i]): float(p[i]) for i in range(len(order))}


def fit_category_model(texts: list[str], labels: list[str], embedder) -> LearnedCategoryModel:
    """Fit a calibrated multinomial LR on embeddings. Deterministic."""
    import numpy as np  # noqa: F401 - ensures numpy present
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression

    X = embedder.encode(texts)
    y = labels
    base = LogisticRegression(
        max_iter=1000, random_state=RANDOM_STATE, C=1.0, multi_class="auto"
    )
    # Sigmoid calibration with a small CV; cv is capped by the smallest class count
    # so tiny stub datasets in tests still fit.
    from collections import Counter

    min_class = min(Counter(y).values())
    cv = max(2, min(3, min_class))
    clf = CalibratedClassifierCV(base, method="sigmoid", cv=cv)
    clf.fit(X, y)
    return LearnedCategoryModel(clf=clf, labels=sorted(set(y)), embedder=embedder)


# --- injection classifier --------------------------------------------------


@dataclass
class LearnedInjectionModel:
    clf: object
    embedder: object

    def proba(self, text: str) -> float:
        """Probability that `text` is an injection attempt."""
        x = self.embedder.encode([text])
        classes = list(self.clf.classes_)
        p = self.clf.predict_proba(x)[0]
        # Probability of the positive (True / 1) class.
        for cls, prob in zip(classes, p):
            if cls in (True, 1, "1", "true"):
                return float(prob)
        return float(p[-1])


def fit_injection_model(texts: list[str], labels: list[bool], embedder) -> LearnedInjectionModel:
    from sklearn.linear_model import LogisticRegression

    X = embedder.encode(texts)
    clf = LogisticRegression(max_iter=1000, random_state=RANDOM_STATE, C=1.0)
    clf.fit(X, [bool(v) for v in labels])
    return LearnedInjectionModel(clf=clf, embedder=embedder)


# --- persistence + manifest ------------------------------------------------


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def save_model(model, path: str) -> None:
    import joblib  # lazy

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # Persist only the fitted estimator + labels, not the embedder (which holds a
    # heavy model); the loader re-attaches an embedder.
    payload = {"clf": model.clf}
    if isinstance(model, LearnedCategoryModel):
        payload["labels"] = model.labels
    joblib.dump(payload, path)


def load_category_model(path: str, embedder) -> LearnedCategoryModel:
    import joblib  # lazy

    payload = joblib.load(path)
    return LearnedCategoryModel(clf=payload["clf"], labels=payload.get("labels", []), embedder=embedder)


def load_injection_model(path: str, embedder) -> LearnedInjectionModel:
    import joblib  # lazy

    payload = joblib.load(path)
    return LearnedInjectionModel(clf=payload["clf"], embedder=embedder)
