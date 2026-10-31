"""Tests for the v2 harness offline subset (V11, V15, V17; review fixes #1/#2/#3/#5).

Runs over the committed held-out test split. No model: Systems B and C must be
reported as pending, System A measured across all split buckets, detectors measured
with a ground-truth PII check, and nothing invented. The eval is run once and
shared, because each run also executes the (not-free) leakage gate.
"""

from __future__ import annotations

import os

import pytest

from eval.harness_v2 import run_eval, TEST_PATH


pytestmark = pytest.mark.skipif(
    not os.path.exists(TEST_PATH),
    reason="dataset not generated (run `make data`)",
)


@pytest.fixture(scope="module")
def results():
    return run_eval(real=False)


def test_leakage_gate_passed_and_seen_template_empty(results):
    # The template-family split must leave no test item sharing a train template.
    assert results["sizes"]["seen_template"] == 0
    assert results["sizes"]["unseen_template"] > 0


def test_offline_subset_runs_system_a_and_marks_bc_pending(results):
    sysb = results["systems"]
    a = sysb["A_v1_regex"]
    assert a["status"] == "measured"
    assert 0.0 <= a["overall_test"]["accuracy"] <= 1.0
    assert sysb["B_embeddings_only"]["status"] == "pending real run"
    assert sysb["C_embeddings_slm"]["status"] == "pending real run"
    assert "accuracy" not in sysb["B_embeddings_only"]
    assert "accuracy" not in sysb["C_embeddings_slm"]


def test_per_split_buckets_present(results):
    a = results["systems"]["A_v1_regex"]
    for bucket in ("seen_template", "unseen_template", "unseen"):
        assert bucket in a["by_split"]
    # The unseen set is scored separately.
    assert a["by_split"]["unseen"]["n"] == results["sizes"]["unseen_handvaried"]


def test_detectors_use_ground_truth_pii(results):
    det = results["detectors"]["test"]
    for fam in ("phishing", "injection"):
        assert det[fam]["precision"] is not None
        assert det[fam]["recall"] is not None
    pii_block = det["pii_masking_ground_truth"]
    assert pii_block["cases"] >= 0
    assert "leaks" in pii_block and "leaked_examples" in pii_block


def test_unseen_detectors_reported(results):
    assert results["detectors"]["unseen"] is not None
    assert "injection" in results["detectors"]["unseen"]


def test_system_a_macro_f1_and_latency(results):
    a = results["systems"]["A_v1_regex"]["overall_test"]
    assert "macro_f1" in a
    assert a["latency"]["p50_ms"] is not None
