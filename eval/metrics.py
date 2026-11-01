"""Eval metrics (V12-V14): accuracy, per-class P/R/F1, macro-F1, confusion, latency.

Kept pure standard library so the metrics are testable offline with no numpy. The
confusion matrix is returned as a labelled nested dict / 2-D list; rendering it to
a PNG is the harness's job (matplotlib, imported lazily there).

All numbers are computed from the predictions the caller passes in. Nothing is
assumed or filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ClassMetrics:
    label: str
    precision: float
    recall: float
    f1: float
    support: int


def accuracy(y_true: list[str], y_pred: list[str]) -> float:
    if not y_true:
        return 0.0
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return correct / len(y_true)


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def per_class(y_true: list[str], y_pred: list[str], labels: list[str] | None = None) -> list[ClassMetrics]:
    labels = labels or sorted(set(y_true) | set(y_pred))
    out: list[ClassMetrics] = []
    for lab in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p == lab)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != lab and p == lab)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p != lab)
        support = sum(1 for t in y_true if t == lab)
        pr, rc, f1 = _prf(tp, fp, fn)
        out.append(ClassMetrics(lab, round(pr, 4), round(rc, 4), round(f1, 4), support))
    return out


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str] | None = None) -> float:
    pcs = per_class(y_true, y_pred, labels)
    if not pcs:
        return 0.0
    return round(sum(c.f1 for c in pcs) / len(pcs), 4)


def confusion_matrix(y_true: list[str], y_pred: list[str], labels: list[str] | None = None):
    """Return (labels, matrix) where matrix[i][j] = count true=labels[i], pred=labels[j]."""
    labels = labels or sorted(set(y_true) | set(y_pred))
    index = {lab: i for i, lab in enumerate(labels)}
    mat = [[0 for _ in labels] for _ in labels]
    for t, p in zip(y_true, y_pred):
        if t in index and p in index:
            mat[index[t]][index[p]] += 1
    return labels, mat


def detection_prf(y_true: list[bool], y_pred: list[bool]) -> dict:
    """Precision/recall for a binary detector (phishing / injection / PII)."""
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)
    pr, rc, f1 = _prf(tp, fp, fn)
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(pr, 4), "recall": round(rc, 4), "f1": round(f1, 4),
        "fpr": round(fpr, 4),
    }


def percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile (no numpy). `pct` in [0, 100]."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if pct <= 0:
        return ordered[0]
    if pct >= 100:
        return ordered[-1]
    k = (pct / 100) * (len(ordered) - 1)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def latency_summary(samples_ms: list[float]) -> dict:
    if not samples_ms:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "mean_ms": None}
    return {
        "n": len(samples_ms),
        "p50_ms": round(percentile(samples_ms, 50), 2),
        "p95_ms": round(percentile(samples_ms, 95), 2),
        "mean_ms": round(sum(samples_ms) / len(samples_ms), 2),
    }


def confidence_histogram(values: list[float], bins: int = 10) -> dict:
    """Bucket confidences into `bins` equal-width buckets over [0, 1].

    Added for the review finding that the SLM's confidence is almost always ~0.95
    -- the histogram makes that collapse visible instead of hiding it behind a mean.
    """
    counts = [0 for _ in range(bins)]
    for v in values:
        v = max(0.0, min(1.0, float(v)))
        idx = min(bins - 1, int(v * bins))
        counts[idx] += 1
    edges = [round(i / bins, 2) for i in range(bins + 1)]
    return {
        "bins": bins,
        "edges": edges,
        "counts": counts,
        "n": len(values),
        "mean": round(sum(values) / len(values), 4) if values else None,
    }


def reliability_table(confidences: list[float], correct: list[bool], bins: int = 10) -> dict:
    """Binned reliability: for each confidence bucket, mean confidence vs accuracy.

    `confidences[i]` is the model's probability for its prediction on item i;
    `correct[i]` is whether that prediction was right. Returns per-bin counts, mean
    confidence and accuracy, plus the Expected Calibration Error (ECE).
    """
    edges = [i / bins for i in range(bins + 1)]
    rows = []
    n = len(confidences)
    ece = 0.0
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        # Last bin is closed on the right so p == 1.0 lands somewhere.
        idx = [i for i in range(n)
               if (confidences[i] >= lo and (confidences[i] < hi or (b == bins - 1 and confidences[i] <= hi)))]
        count = len(idx)
        if count:
            mean_conf = sum(confidences[i] for i in idx) / count
            acc = sum(1 for i in idx if correct[i]) / count
            ece += (count / n) * abs(acc - mean_conf)
        else:
            mean_conf = None
            acc = None
        rows.append({
            "bin": [round(lo, 2), round(hi, 2)],
            "count": count,
            "mean_confidence": round(mean_conf, 4) if mean_conf is not None else None,
            "accuracy": round(acc, 4) if acc is not None else None,
        })
    return {"bins": bins, "ece": round(ece, 4) if n else None, "n": n, "table": rows}


def classification_report(y_true: list[str], y_pred: list[str], labels: list[str] | None = None) -> dict:
    labels = labels or sorted(set(y_true) | set(y_pred))
    pcs = per_class(y_true, y_pred, labels)
    cm_labels, cm = confusion_matrix(y_true, y_pred, labels)
    return {
        "accuracy": round(accuracy(y_true, y_pred), 4),
        "macro_f1": macro_f1(y_true, y_pred, labels),
        "per_class": {c.label: {
            "precision": c.precision, "recall": c.recall, "f1": c.f1, "support": c.support
        } for c in pcs},
        "confusion_matrix": {"labels": cm_labels, "matrix": cm},
    }
