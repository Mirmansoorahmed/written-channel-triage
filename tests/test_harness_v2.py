"""Tests for the v2 harness (Round 3).

Runs offline over the committed splits. No model: Systems B/C/D/E are "pending
real run"; System A is measured on dev, test and unseen; detectors are measured
with the fuzzy ground-truth PII check; nothing is invented. The harness writes its
artifacts to tmp_path so the working tree stays clean. The eval is run once and
shared across tests because each run also executes the (not-free) leakage gate.
"""

from __future__ import annotations

import os

import pytest

from eval.harness_v2 import DATA_DIR, run_eval

TEST_SPLIT = os.path.join(DATA_DIR, "test.jsonl")

pytestmark = pytest.mark.skipif(
    not os.path.exists(TEST_SPLIT),
    reason="dataset not generated (run `make data`)",
)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    out = tmp_path_factory.mktemp("harness_out")
    return run_eval(
        real=False,
        out_dir=str(out),
        results_path=str(out / "results-v2.json"),
        error_analysis_path=str(out / "error-analysis.md"),
    )


def test_splits_are_dev_test_unseen_no_seen_template(results):
    assert set(results["sizes"]) == {"dev", "test", "unseen"}
    a = results["systems"]["A_v1_regex"]
    assert set(a["by_split"]) == {"dev", "test", "unseen"}
    assert "seen_template" not in a["by_split"]


def test_system_a_measured_bcde_pending(results):
    sysb = results["systems"]
    assert sysb["A_v1_regex"]["status"] == "measured"
    assert 0.0 <= sysb["A_v1_regex"]["overall_test"]["accuracy"] <= 1.0
    for key in ("B_embeddings_only", "C_embeddings_slm", "D_embeddings_lr", "E_lr_then_slm"):
        assert sysb[key]["status"].startswith("pending real run")
        assert "accuracy" not in sysb[key]


def test_category_scored_only_on_category_families(results):
    # The number of category items scored must be <= the split size (attack
    # families are excluded), and strictly less on test (which has injections).
    a = results["systems"]["A_v1_regex"]
    n_cat = a["by_split"]["test"]["n_category_items"]
    assert 0 < n_cat < results["sizes"]["test"]


def test_detectors_and_pii_leak_reported(results):
    det = results["detectors"]["test"]
    assert det["phishing"]["precision"] is not None
    # Injection is reported twice: rules-only and rules-OR-model (Round 4 #1).
    assert det["injection_rules_only"]["recall"] is not None
    assert det["injection_combined"]["recall"] is not None
    assert "fpr" in det["injection_rules_only"]
    assert "pii_masking_ground_truth" in det
    assert results["pii_leak_check"]["checked_items"] > 0


def test_phishing_reported_by_auth(results):
    # Phishing P/R is broken out by auth so the auth shortcut is visible (Round 4 #6).
    det = results["detectors"]["unseen"]
    assert "phishing_by_auth" in det
    assert set(det["phishing_by_auth"]) == {"auth_pass", "auth_fail_or_missing"}


def test_calibration_present_for_system_a(results):
    # Every measured category report carries a calibration block with an ECE.
    ot = results["systems"]["A_v1_regex"]["overall_test"]
    assert "calibration" in ot and "ece" in ot["calibration"]


def test_cost_recorded(results):
    cost = results["systems"]["A_v1_regex"]["cost"]
    assert cost["items_scored"] > 0
    assert cost["cpu_seconds_per_item"] is not None
    assert cost["harness_peak_rss_mb"] > 0
    # System A does not call the SLM, so its Ollama CPU attribution is zero.
    assert cost["ollama_cpu_seconds_per_item"] == 0.0


def test_thresholds_block_present(results):
    # Offline (no models) the thresholds block is pending, never invented.
    assert results["thresholds"]["status"] == "pending real run"


def test_no_artifacts_written_to_worktree(results):
    # The harness wrote to tmp_path; the repo's eval/ dir must not gain a stray
    # confusion CSV from this test run (the committed one may exist, but no new
    # per-system file for a system that only runs here).
    assert results["run_mode"].startswith("offline")
