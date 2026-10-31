"""Tests for the v2 harness offline subset (V11, V15, V17).

Runs over the committed held-out test split. No model: Systems B and C must be
reported as pending, System A measured, detectors measured, and nothing invented.
"""

from __future__ import annotations

import os

import pytest

from eval.harness_v2 import run_eval, TEST_PATH


pytestmark = pytest.mark.skipif(
    not os.path.exists(TEST_PATH),
    reason="dataset not generated (run `make data`)",
)


def test_offline_subset_runs_system_a_and_marks_bc_pending():
    r = run_eval(real=False)
    assert r["test_split_size"] > 0
    sys = r["systems"]
    assert sys["A_v1_regex"]["status"] == "measured"
    assert 0.0 <= sys["A_v1_regex"]["accuracy"] <= 1.0
    assert sys["B_embeddings_only"]["status"] == "pending real run"
    assert sys["C_embeddings_slm"]["status"] == "pending real run"
    # B/C must carry no invented numbers.
    assert "accuracy" not in sys["B_embeddings_only"]
    assert "accuracy" not in sys["C_embeddings_slm"]


def test_detectors_are_measured_not_invented():
    r = run_eval(real=False)
    det = r["detectors"]
    for fam in ("phishing", "injection"):
        assert det[fam]["precision"] is not None
        assert det[fam]["recall"] is not None
    assert det["pii_masking"]["cases"] >= 0


def test_system_a_macro_f1_present():
    r = run_eval(real=False)
    a = r["systems"]["A_v1_regex"]
    assert "macro_f1" in a
    assert "latency" in a and a["latency"]["p50_ms"] is not None
