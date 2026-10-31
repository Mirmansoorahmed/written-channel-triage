"""Tests for the README/architecture table generator (Round 3).

The results, cost, calibration and detector tables are generated from
eval/results-v2.json, never hand-typed. These tests exercise the rendering on a
synthetic MEASURED dict (so they don't depend on whether the committed results are
pending) and confirm pending inputs render as 'pending real run'.
"""

from __future__ import annotations

import os

from docs import generate_tables as gt

_MEASURED = {
    "systems": {
        "A_v1_regex": {
            "status": "measured",
            "by_split": {
                "test": {"status": "measured", "accuracy": 0.79, "macro_f1": 0.74,
                         "latency": {"p50_ms": 0.07, "p95_ms": 0.09}},
                "unseen": {"status": "measured", "accuracy": 0.50, "macro_f1": 0.48,
                           "latency": {"p50_ms": 0.06, "p95_ms": 0.1}},
            },
            "overall_test": {"calibration": {"ece": 0.60}},
            "cost": {"cpu_seconds_per_item": 0.0003, "peak_rss_mb": 120.0},
        },
        "B_embeddings_only": {"status": "pending real run"},
        "C_embeddings_slm": {"status": "pending real run"},
        "D_embeddings_lr": {"status": "pending real run"},
        "E_lr_then_slm": {"status": "pending real run"},
    },
    "detectors": {
        "test": {
            "phishing": {"precision": 1.0, "recall": 1.0},
            "injection": {"precision": 1.0, "recall": 1.0},
            "pii_masking_ground_truth": {"recall": 1.0},
        },
        "unseen": {
            "phishing": {"precision": 1.0, "recall": 0.67},
            "injection": {"precision": 1.0, "recall": 0.16},
            "pii_masking_ground_truth": {"recall": 1.0},
        },
    },
}

_PENDING = {
    "systems": {k: {"status": "pending real run"} for k in
                ("A_v1_regex", "B_embeddings_only", "C_embeddings_slm",
                 "D_embeddings_lr", "E_lr_then_slm")},
    "detectors": {"test": {"status": "pending real run"},
                  "unseen": {"status": "pending real run"}},
}


def test_results_table_measured_and_pending_rows():
    table = gt._results_table(_MEASURED)
    assert "| system | split | accuracy" in table
    assert "0.7900" in table  # measured System A test accuracy
    assert "pending real run" in table  # B/C/D/E


def test_cost_table_uses_formula_and_labels_assumption():
    table = gt._cost_table(_MEASURED)
    assert "VM price assumption" in table
    assert "cost per 1k msg" in table
    # cost = 0.0003 * 1000 * 0.192 / (3600*4) = 4e-6 -> rounded to 0.0000
    assert "0.0003" in table  # cpu seconds/item shown


def test_calibration_table_present():
    table = gt._calibration_table(_MEASURED)
    assert "ECE (test)" in table
    assert "0.6000" in table


def test_detector_table_measured_and_pending():
    assert "PII masking (fuzzy ground-truth)" in gt._detector_table(_MEASURED)
    assert "pending real run" in gt._detector_table(_PENDING)


def test_replace_block_is_idempotent():
    text = "x\n<!-- BEGIN:foo -->\nold\n<!-- END:foo -->\ny"
    once = gt._replace_block(text, "foo", "NEW")
    twice = gt._replace_block(once, "foo", "NEW")
    assert once == twice
    assert "NEW" in once and "old" not in once


def test_readme_has_all_generated_markers():
    with open(os.path.join(os.path.dirname(__file__), "..", "README.md"), encoding="utf-8") as f:
        readme = f.read()
    for marker in ("results-table", "detector-table", "cost-table", "calibration-table"):
        assert f"<!-- BEGIN:{marker} -->" in readme


def test_committed_results_are_pending():
    # The committed results-v2.json must be the pending placeholder (run rules).
    data = gt._load()
    assert all(b.get("status") == "pending real run" for b in data["systems"].values())
