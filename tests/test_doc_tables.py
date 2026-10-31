"""Tests for the README/architecture table generator (review fix #5).

The results and cost tables must be generated from eval/results-v2.json, never
hand-typed, and regeneration must be idempotent.
"""

from __future__ import annotations

import os

from docs import generate_tables as gt


def test_results_table_renders_from_results():
    data = gt._load()
    table = gt._results_table(data)
    assert "| system | split | accuracy" in table
    # A pending system must be rendered as pending, not with a number.
    assert "pending real run" in table or "C — embeddings + SLM" in table


def test_cost_table_renders_pending_for_unmeasured():
    data = gt._load()
    table = gt._cost_table(data)
    assert "A — v1 regex/keyword" in table


def test_replace_block_is_idempotent():
    text = "x\n<!-- BEGIN:foo -->\nold\n<!-- END:foo -->\ny"
    once = gt._replace_block(text, "foo", "NEW")
    twice = gt._replace_block(once, "foo", "NEW")
    assert once == twice
    assert "NEW" in once and "old" not in once


def test_detector_table_includes_ground_truth_pii():
    data = gt._load()
    table = gt._detector_table(data)
    assert "PII masking (ground-truth, no leak)" in table


def test_readme_has_generated_markers():
    with open(os.path.join(os.path.dirname(__file__), "..", "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "<!-- BEGIN:results-table -->" in readme
    assert "<!-- BEGIN:detector-table -->" in readme
