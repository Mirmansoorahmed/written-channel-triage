"""Tests for the eval metrics (V12-V14), on toy inputs with hand-checked values."""

from eval.metrics import (
    accuracy,
    classification_report,
    confusion_matrix,
    detection_prf,
    latency_summary,
    macro_f1,
    per_class,
    percentile,
)


def test_accuracy_simple():
    assert accuracy(["a", "b", "c"], ["a", "b", "x"]) == 2 / 3


def test_accuracy_empty():
    assert accuracy([], []) == 0.0


def test_per_class_precision_recall():
    y_true = ["a", "a", "b", "b"]
    y_pred = ["a", "b", "b", "b"]
    pcs = {c.label: c for c in per_class(y_true, y_pred)}
    # a: tp=1, fp=0, fn=1 -> precision 1.0, recall 0.5
    assert pcs["a"].precision == 1.0
    assert pcs["a"].recall == 0.5
    # b: tp=2, fp=1, fn=0 -> precision 2/3, recall 1.0
    assert pcs["b"].precision == round(2 / 3, 4)
    assert pcs["b"].recall == 1.0


def test_macro_f1_is_mean_of_class_f1():
    y_true = ["a", "a", "b", "b"]
    y_pred = ["a", "a", "b", "b"]
    assert macro_f1(y_true, y_pred) == 1.0


def test_confusion_matrix_counts():
    labels, mat = confusion_matrix(["a", "a", "b"], ["a", "b", "b"], labels=["a", "b"])
    assert labels == ["a", "b"]
    # row a: 1 predicted a, 1 predicted b; row b: 0 a, 1 b
    assert mat == [[1, 1], [0, 1]]


def test_detection_prf():
    y_true = [True, True, False, False]
    y_pred = [True, False, True, False]
    d = detection_prf(y_true, y_pred)
    assert d["tp"] == 1 and d["fp"] == 1 and d["fn"] == 1 and d["tn"] == 1
    assert d["precision"] == 0.5
    assert d["recall"] == 0.5


def test_percentile_nearest_rank():
    samples = [10, 20, 30, 40, 50]
    assert percentile(samples, 50) == 30
    assert percentile(samples, 0) == 10
    assert percentile(samples, 100) == 50


def test_latency_summary():
    s = latency_summary([10.0, 20.0, 30.0])
    assert s["n"] == 3
    assert s["p50_ms"] == 20.0
    assert s["mean_ms"] == 20.0


def test_latency_summary_empty():
    s = latency_summary([])
    assert s["n"] == 0
    assert s["p50_ms"] is None


def test_classification_report_shape():
    rep = classification_report(["a", "b"], ["a", "a"], labels=["a", "b"])
    assert "accuracy" in rep and "macro_f1" in rep
    assert set(rep["per_class"]) == {"a", "b"}
    assert rep["confusion_matrix"]["labels"] == ["a", "b"]


def test_system_a_offline_classifies():
    # System A must work with no model (stdlib path).
    from eval.systems import SystemA

    sys_a = SystemA()
    label, conf = sys_a.classify("mein internet ist tot, kein anschluss, störung")
    assert label == "Störung"
    assert conf > 0


# --- Round 3: calibration / reliability ---

from eval.metrics import reliability_table


def test_reliability_perfect_calibration_zero_ece():
    # In the 0.5 bucket, confidence 0.5 and exactly half correct -> |acc-conf|=0;
    # in the 1.0 bucket, confidence ~1.0 and all correct -> 0. ECE == 0.
    conf = [0.5, 0.5, 1.0, 1.0]
    correct = [True, False, True, True]
    rel = reliability_table(conf, correct, bins=10)
    assert rel["ece"] == 0.0
    assert rel["n"] == 4


def test_reliability_overconfident_has_positive_ece():
    # Always 0.95 confident but only half correct -> ECE around 0.45.
    conf = [0.95] * 10
    correct = [True, False] * 5
    rel = reliability_table(conf, correct, bins=10)
    assert rel["ece"] is not None and rel["ece"] > 0.4


def test_reliability_table_bins_sum_to_n():
    conf = [0.1, 0.2, 0.85, 0.95, 1.0]
    correct = [False, True, True, True, True]
    rel = reliability_table(conf, correct, bins=10)
    assert sum(row["count"] for row in rel["table"]) == len(conf)
