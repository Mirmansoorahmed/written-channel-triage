from eval.corpus import build_corpus
from eval.harness import run_eval


def test_corpus_has_all_families():
    c = build_corpus()
    assert len(c) >= 100
    assert sum(x.is_phishing for x in c) >= 1
    assert sum(x.is_injection for x in c) >= 1
    assert sum(x.has_pii for x in c) >= 1
    assert sum(x.out_of_hours for x in c) >= 1


def test_eval_runs_and_reports_numbers():
    r = run_eval()
    assert r["corpus_size"] == len(build_corpus())
    assert 0.0 <= r["category_accuracy"]["accuracy"] <= 1.0
    # safety checks should at least be measured on this corpus
    assert r["checks"]["phishing_detection"]["recall"] != "not measured"
    assert r["checks"]["injection_detection"]["recall"] != "not measured"
    assert r["checks"]["pii_masking"]["recall"] != "not measured"


def test_eval_is_deterministic():
    assert run_eval() == run_eval()
