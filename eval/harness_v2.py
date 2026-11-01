"""v2 eval harness (Round 3).

Compares up to five systems on the dev, test and unseen splits:
  A  v1 regex/keyword          (stdlib only; always runs)
  B  embeddings-only           (needs the embedding model)
  C  embeddings + SLM          (needs embeddings + Ollama)
  D  embeddings + trained LR    (needs the saved models)
  E  LR, SLM on low confidence  (needs saved models + Ollama)

Per system and split it records category accuracy, macro-F1, per-class
precision/recall, a confusion matrix (JSON + CSV/PNG on disk), and latency
p50/p95, and -- per system overall -- CPU seconds/item and peak RSS. It scores the
phishing / injection / PII detectors per split, the PII check using the fuzzy
ground-truth comparison. Calibration (ECE + reliability + PNG) is reported for the
systems that expose a probability (C and D). All numbers come from the run.

Round 3 scoring rules:
  * Splits are dev, test, unseen. There is NO seen_template bucket.
  * Each split is scored exactly ONCE per system; overall_test is just the test
    split's report (no second pass).
  * slm_diagnostics counts each item once, per split.
  * Categories are scored only on CATEGORY-bearing families; phishing and
    injection items go to the detectors, not the category metric.
  * The run FAILS if System C's fallback rate exceeds 2%.

Offline vs real: by default only System A runs; B/C/D/E are "pending real run"
unless TRIAGE_EVAL_REAL=1 and the models/artifacts are present. Missing models
mark the relevant systems pending rather than fabricating a run.

The output directory is configurable (`out_dir=` / run_eval), so tests write to a
tmp path and leave the working tree clean.
"""

from __future__ import annotations

import json
import os
import resource
import time
from collections import Counter

from triage import injection as injection_mod
from triage import learned, pii, pipeline
from triage.models import Source
from eval import metrics
from eval.systems import SystemA, build_learned_systems, build_real_systems

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA_DIR = os.path.join(ROOT, "data")
MODELS_DIR = os.path.join(ROOT, "models")
UNSEEN_PATH = os.path.join(HERE, "unseen", "unseen.jsonl")
DEFAULT_RESULTS_PATH = os.path.join(HERE, "results-v2.json")
DEFAULT_ERROR_ANALYSIS_PATH = os.path.join(ROOT, "docs", "error-analysis.md")

SPLITS = ("dev", "test", "unseen")
# Families whose items carry a meaningful intent category.
CATEGORY_FAMILIES = {
    "normal", "pii_heavy", "out_of_hours", "injection_negative", "phishing_negative",
    "unseen_normal", "unseen_pii", "unseen_out_of_hours", "unseen_injection_negative",
    "unseen_benign_link",
}
FALLBACK_LIMIT = 0.02  # fail the run if C's fallback rate exceeds this

NOTE = ("Synthetic data only; fictional NordTel GmbH. Not a certification. All "
        "numbers are produced by this eval run. Split is by template family; the "
        "unseen set is hand-varied and never seen by the model.")


def _load(path: str) -> list[dict]:
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if not obj.get("_meta"):
                    rows.append(obj)
    return rows


def _load_splits() -> dict[str, list[dict]]:
    return {
        "dev": _load(os.path.join(DATA_DIR, "dev.jsonl")),
        "test": _load(os.path.join(DATA_DIR, "test.jsonl")),
        "unseen": _load(UNSEEN_PATH),
    }


def _masked(text: str) -> str:
    return pii.mask(text).masked_text


def _is_category_item(r: dict) -> bool:
    return r["family"] in CATEGORY_FAMILIES


# --- per-system scoring (each split scored exactly once) -------------------


def _score_split(system, rows: list[dict]) -> dict:
    """Score one system on one split in a SINGLE pass. Returns a result dict with
    per-row predictions, category metrics (category families only), latency,
    confidences+correctness (for calibration), errors, and SLM stats delta."""
    cat_rows = [r for r in rows if _is_category_item(r)]
    y_true, y_pred, latencies = [], [], []
    confidences, correct = [], []
    errors = []

    # Reset SLM stats so the per-split delta is counted once.
    client = getattr(system, "_client", None)
    if client is not None and hasattr(client, "reset_stats"):
        client.reset_stats()
    if hasattr(system, "calls"):
        system.calls = 0
        system.slm_calls = 0

    for r in cat_rows:
        masked = _masked(r["text"])
        t0 = time.perf_counter()
        label, conf = system.classify(masked)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        y_true.append(r["category"])
        y_pred.append(label)
        confidences.append(float(conf))
        correct.append(label == r["category"])
        if label != r["category"]:
            errors.append({
                "id": r["id"], "family": r["family"],
                "expected": r["category"], "predicted": label,
                "masked_excerpt": masked[:160].replace("\n", " "),
            })

    out = {"n_category_items": len(cat_rows), "status": "measured"}
    if cat_rows:
        report = metrics.classification_report(y_true, y_pred)
        out.update(report)
        out["latency"] = metrics.latency_summary(latencies)
        out["confidence_histogram"] = metrics.confidence_histogram(confidences)
        out["calibration"] = metrics.reliability_table(confidences, correct)
    out["_errors"] = errors

    # SLM diagnostics for this split (counted once).
    if client is not None and hasattr(client, "stats"):
        s = client.stats
        out["slm_diagnostics"] = {
            "calls": s.get("calls", 0), "fallbacks": s.get("fallbacks", 0),
            "invalid_category": s.get("invalid_category", 0),
            "timeouts": s.get("timeouts", 0), "json_failures": s.get("json_failures", 0),
            "connection_errors": s.get("connection_errors", 0),
            "fallback_rate": round(s.get("fallbacks", 0) / s.get("calls", 1), 4) if s.get("calls") else 0.0,
        }
    if hasattr(system, "slm_call_rate"):
        out["slm_call_rate"] = system.slm_call_rate
    return out


def _score_system(system, splits: dict[str, list[dict]]) -> tuple[dict, dict]:
    """Score a system across all splits (each once). Returns (block, errors_by_split)."""
    cpu0 = time.process_time()
    block: dict = {"label": system.label, "status": "measured", "by_split": {}}
    errors_by_split: dict[str, list[dict]] = {}
    total_items = 0

    for split in SPLITS:
        rep = _score_split(system, splits[split])
        errors_by_split[split] = rep.pop("_errors", [])
        total_items += rep.get("n_category_items", 0)
        block["by_split"][split] = rep

    # overall_test is simply the test split's report (no re-run).
    block["overall_test"] = {
        k: v for k, v in block["by_split"]["test"].items() if k != "slm_diagnostics"
    }

    cpu_total = time.process_time() - cpu0
    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    block["cost"] = {
        "cpu_seconds_per_item": round(cpu_total / total_items, 6) if total_items else None,
        "peak_rss_mb": round(peak_rss_kb / 1024, 1),  # Linux ru_maxrss is in KB
        "items_scored": total_items,
    }
    return block, errors_by_split


# --- detectors per split (PII via fuzzy ground truth) ----------------------


def _phishing_by_auth(rows: list[dict]) -> dict:
    """Phishing P/R split by auth pass vs fail/missing (Round 4, #6).

    So we can see whether the detector separates phishing from benign WITHOUT the
    auth shortcut: the auth-pass slice contains phishing that passed auth and
    benign mail, the fail/missing slice the opposite.
    """
    out = {}
    for name, keep in (("auth_pass", lambda r: r.get("auth") == "pass"),
                       ("auth_fail_or_missing", lambda r: r.get("auth") != "pass")):
        sub = [r for r in rows if keep(r)]
        if not sub:
            out[name] = {"n": 0}
            continue
        yt, yp = [], []
        for r in sub:
            src = Source.EML if r["source"] == "eml" else Source.FORM
            yt.append(bool(r["is_phishing"]))
            yp.append(pipeline.run(r["text"], source=src).phishing.suspected)
        d = metrics.detection_prf(yt, yp)
        d["n"] = len(sub)
        out[name] = d
    return out


def _score_detectors(rows: list[dict], label: str,
                     injection_model=None, injection_threshold: float | None = None) -> dict:
    ph_true, ph_pred = [], []
    inj_true = []
    inj_rules_pred, inj_combined_pred = [], []
    model_only_catches: list[dict] = []
    pii_cases = pii_leaks = 0
    leaked_examples: list[dict] = []

    for r in rows:
        req_source = Source.EML if r["source"] == "eml" else Source.FORM
        result = pipeline.run(r["text"], source=req_source)
        ph_true.append(bool(r["is_phishing"]))
        ph_pred.append(result.phishing.suspected)

        # Injection: score rules-only AND rules-OR-model on the same masked text.
        masked = _masked(r["text"])
        rules_v = injection_mod.detect_injection(masked)
        combined_v = injection_mod.detect_injection(
            masked, injection_model=injection_model, threshold=injection_threshold)
        inj_true.append(bool(r["is_injection"]))
        inj_rules_pred.append(rules_v.detected)
        inj_combined_pred.append(combined_v.detected)
        if combined_v.detected and not rules_v.detected and len(model_only_catches) < 10:
            model_only_catches.append({"id": r["id"], "rules": rules_v.matched_rules,
                                        "combined": combined_v.matched_rules})

        if r.get("pii_truth"):  # Round 4 #5: ALL items with ground-truth PII
            pii_cases += 1
            leaks = pii.fuzzy_ground_truth_leaks(masked, r["pii_truth"])
            if leaks:
                pii_leaks += 1
                if len(leaked_examples) < 10:
                    leaked_examples.append({"id": r["id"], "leaked": leaks})

    return {
        "split": label,
        "phishing": metrics.detection_prf(ph_true, ph_pred),
        "phishing_by_auth": _phishing_by_auth(rows),
        "injection_rules_only": metrics.detection_prf(inj_true, inj_rules_pred),
        "injection_combined": metrics.detection_prf(inj_true, inj_combined_pred),
        "injection_model_wired": injection_model is not None,
        "injection_model_only_catches": model_only_catches,
        "pii_masking_ground_truth": {
            "cases": pii_cases, "leaks": pii_leaks, "no_leak": pii_cases - pii_leaks,
            "recall": round((pii_cases - pii_leaks) / pii_cases, 4) if pii_cases else None,
            "leaked_examples": leaked_examples,
        },
    }


# --- artifacts -------------------------------------------------------------


def _write_confusion_csv(out_dir: str, key: str, report: dict) -> str | None:
    if "confusion_matrix" not in report:
        return None
    labels = report["confusion_matrix"]["labels"]
    mat = report["confusion_matrix"]["matrix"]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"confusion_{key}.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("true\\pred," + ",".join(labels) + "\n")
        for lab, row in zip(labels, mat):
            f.write(lab + "," + ",".join(str(c) for c in row) + "\n")
    return path


def _write_confusion_png(out_dir: str, key: str, report: dict) -> str | None:
    if "confusion_matrix" not in report:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    labels = report["confusion_matrix"]["labels"]
    mat = report["confusion_matrix"]["matrix"]
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(mat, cmap="Blues")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(labels)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(f"Confusion - {key} (test)")
    for i in range(len(labels)):
        for j in range(len(labels)):
            if mat[i][j]:
                ax.text(j, i, str(mat[i][j]), ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"confusion_{key}.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _write_reliability_png(out_dir: str, key: str, calibration: dict) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    rows = calibration.get("table", [])
    xs = [(r["bin"][0] + r["bin"][1]) / 2 for r in rows]
    accs = [r["accuracy"] if r["accuracy"] is not None else 0 for r in rows]
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect")
    ax.bar(xs, accs, width=0.08, alpha=0.7, label="accuracy")
    ax.set_xlabel("confidence")
    ax.set_ylabel("accuracy")
    ax.set_title(f"Reliability - {key} (ECE={calibration.get('ece')})")
    ax.legend()
    fig.tight_layout()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"reliability_{key}.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _write_error_analysis(path: str, all_errors: dict[str, dict[str, list[dict]]]) -> None:
    lines = ["# Error analysis (v2, Round 3)\n"]
    lines.append(
        "Generated by `eval/harness_v2.py` from the latest run's misclassifications, "
        "per split (dev, test, unseen). Only category-bearing families are scored here; "
        "phishing and injection are detector problems, reported separately.\n"
    )
    for key, by_split in all_errors.items():
        lines.append(f"## System {key}\n")
        for split in SPLITS:
            errs = by_split.get(split, [])
            lines.append(f"### Split: {split}\n")
            lines.append(f"- Misclassified: **{len(errs)}**\n")
            if not errs:
                lines.append("No category errors in this split.\n")
                continue
            pairs = Counter((e["expected"], e["predicted"]) for e in errs)
            lines.append("| expected | predicted | count |")
            lines.append("|---|---|---|")
            for (exp, pred), n in pairs.most_common(8):
                lines.append(f"| {exp} | {pred} | {n} |")
            lines.append("")
            lines.append("| id | family | expected | predicted | masked excerpt |")
            lines.append("|---|---|---|---|---|")
            for e in errs[:10]:
                excerpt = e["masked_excerpt"].replace("|", "\\|")
                lines.append(f"| {e['id']} | {e['family']} | {e['expected']} | "
                             f"{e['predicted']} | {excerpt} |")
            lines.append("")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# --- gates -----------------------------------------------------------------


def _assert_no_leakage(threshold: float = 0.9) -> None:
    from data.overlap_check import check, check_unseen

    v = check(threshold)
    vu = check_unseen(threshold)
    if v or vu:
        raise SystemExit(
            f"ABORT: leakage gate failed (test={len(v)}, unseen={len(vu)}). "
            f"Run `python -m data.overlap_check` for detail."
        )


def _assert_fallback_ok(systems_block: dict) -> None:
    for key in ("C_embeddings_slm", "E_lr_then_slm"):
        blk = systems_block.get(key, {})
        if blk.get("status", "measured") != "measured":
            continue
        for split, rep in blk.get("by_split", {}).items():
            diag = rep.get("slm_diagnostics")
            if diag and diag.get("fallback_rate", 0.0) > FALLBACK_LIMIT:
                raise SystemExit(
                    f"ABORT: System {key} fallback rate {diag['fallback_rate']} on "
                    f"split '{split}' exceeds {FALLBACK_LIMIT}. The SLM run is not healthy."
                )


def _choose_thresholds_on_dev(cat_model, dev_rows: list[dict],
                              target_auto_accuracy: float = 0.95) -> dict:
    """Choose, on DEV only, the human-review threshold and E's routing threshold
    from D's calibrated probabilities (Round 4 #4).

    Method: for each candidate threshold t, items with prob >= t are auto-handled;
    pick the SMALLEST t whose auto-handled accuracy >= target_auto_accuracy, and
    report the expected review rate (fraction with prob < t). E routes on the same
    threshold: it trusts D at/above t and escalates to the SLM below it. Scored on
    pii.mask(text), the same text used at evaluation.
    """
    scored = []
    for r in dev_rows:
        if r["family"] not in CATEGORY_FAMILIES:
            continue
        label, prob = cat_model.predict(_masked(r["text"]))
        scored.append((prob, label == r["category"]))
    if not scored:
        return {"status": "no dev category items"}
    n = len(scored)
    best = None
    for i in range(0, 100):
        t = i / 100
        auto = [c for p, c in scored if p >= t]
        if not auto:
            continue
        acc = sum(auto) / len(auto)
        review_rate = 1 - len(auto) / n
        if acc >= target_auto_accuracy:
            best = {"threshold": round(t, 2), "auto_accuracy": round(acc, 4),
                    "expected_review_rate": round(review_rate, 4)}
            break
    if best is None:
        # Target not reachable; report the highest-accuracy operating point.
        t_best, a_best = 0.0, -1.0
        for i in range(0, 100):
            t = i / 100
            auto = [c for p, c in scored if p >= t]
            if not auto:
                continue
            acc = sum(auto) / len(auto)
            if acc > a_best:
                a_best, t_best = acc, t
        auto = [c for p, c in scored if p >= t_best]
        best = {"threshold": round(t_best, 2), "auto_accuracy": round(a_best, 4),
                "expected_review_rate": round(1 - len(auto) / n, 4),
                "note": f"target auto-accuracy {target_auto_accuracy} not reachable on dev"}
    return {
        "method": (f"smallest dev threshold whose auto-handled (prob>=t) accuracy "
                   f">= {target_auto_accuracy}; scored on masked text"),
        "target_auto_accuracy": target_auto_accuracy,
        "human_review_threshold": best["threshold"],
        "expected_review_rate": best["expected_review_rate"],
        "auto_accuracy_at_threshold": best["auto_accuracy"],
        "e_routing_threshold": best["threshold"],
        **({"note": best["note"]} if "note" in best else {}),
    }


# --- main ------------------------------------------------------------------


def run_eval(real: bool | None = None, out_dir: str | None = None,
             results_path: str | None = None, error_analysis_path: str | None = None) -> dict:
    if real is None:
        real = os.environ.get("TRIAGE_EVAL_REAL") == "1"
    out_dir = out_dir or HERE
    results_path = results_path or DEFAULT_RESULTS_PATH
    error_analysis_path = error_analysis_path or DEFAULT_ERROR_ANALYSIS_PATH

    _assert_no_leakage()

    splits = _load_splits()
    systems = [SystemA()]
    thresholds: dict = {"status": "pending real run"}
    pending: dict[str, str] = {
        "B_embeddings_only": "pending real run",
        "C_embeddings_slm": "pending real run",
        "D_embeddings_lr": "pending real run",
        "E_lr_then_slm": "pending real run",
    }
    run_mode = "offline subset (System A only)"

    if real:
        try:
            extra, _ = build_real_systems()
            systems.extend(extra)
            for s in extra:
                pending.pop(s.key, None)
        except Exception as exc:  # noqa: BLE001
            msg = f"pending real run: {type(exc).__name__}: {exc}"
            pending["B_embeddings_only"] = pending["C_embeddings_slm"] = msg
        try:
            learned_systems, cat_model = build_learned_systems(MODELS_DIR)
            # Choose the review + E routing thresholds on DEV from D's probabilities.
            thresholds = _choose_thresholds_on_dev(cat_model, splits["dev"])
            e_thr = thresholds.get("e_routing_threshold")
            for s in learned_systems:
                if s.key == "E_lr_then_slm" and e_thr is not None:
                    s.threshold = e_thr  # replace the hard-coded default
            systems.extend(learned_systems)
            for s in learned_systems:
                pending.pop(s.key, None)
        except Exception as exc:  # noqa: BLE001
            msg = f"pending real run: {type(exc).__name__}: {exc}"
            pending.setdefault("D_embeddings_lr", msg)
            pending.setdefault("E_lr_then_slm", msg)
        run_mode = "real models" if len(systems) > 1 else run_mode

    systems_block: dict[str, dict] = {}
    all_errors: dict[str, dict[str, list[dict]]] = {}

    for system in systems:
        block, errors_by_split = _score_system(system, splits)
        # artifacts from the test-split report
        test_rep = block["by_split"]["test"]
        csv = _write_confusion_csv(out_dir, system.key, test_rep)
        png = _write_confusion_png(out_dir, system.key, test_rep)
        block["overall_test"]["confusion_csv"] = os.path.relpath(csv, ROOT) if csv else None
        block["overall_test"]["confusion_png"] = (
            os.path.relpath(png, ROOT) if png else "not rendered (matplotlib absent)")
        # reliability PNG for systems that expose probabilities (C and D especially)
        cal = test_rep.get("calibration")
        if cal and system.key in ("C_embeddings_slm", "D_embeddings_lr"):
            rp = _write_reliability_png(out_dir, system.key, cal)
            block["overall_test"]["reliability_png"] = (
                os.path.relpath(rp, ROOT) if rp else "not rendered (matplotlib absent)")
        systems_block[system.key] = block
        all_errors[system.key] = errors_by_split

    for key, status in pending.items():
        systems_block[key] = {"status": status}

    _assert_fallback_ok(systems_block)

    # Load the trained injection detector (model + dev threshold) so the detector
    # metrics report rules-only AND rules-OR-model (Round 4, #1). None when the
    # artifacts are absent -> both columns equal the rules-only result.
    inj_model, inj_threshold = learned.load_injection_detector(MODELS_DIR)
    detectors = {
        split: _score_detectors(splits[split], split, inj_model, inj_threshold)
        for split in SPLITS
    }

    # Standalone-style fuzzy PII leak summary over test+unseen (#7).
    from eval.pii_leak_check import run_check as pii_leak_run
    pii_leak_summary = pii_leak_run()

    _write_error_analysis(error_analysis_path, all_errors)

    return {
        "note": NOTE,
        "run_mode": run_mode,
        "sizes": {s: len(splits[s]) for s in SPLITS},
        "category_families": sorted(CATEGORY_FAMILIES),
        "systems": systems_block,
        "detectors": detectors,
        "thresholds": thresholds,
        "pii_leak_check": pii_leak_summary,
        "fallback_limit": FALLBACK_LIMIT,
    }


def pending_results() -> dict:
    """A fully-pending results file for the COMMITTED state.

    Per the run rules, every metric/cost/calibration table says 'pending real run'
    until the maintainer runs `TRIAGE_EVAL_REAL=1 ... eval.harness_v2` on a machine
    with the models. This is what we commit so no number in the repo is unsanctioned;
    a local `make eval` / `make eval-real` overwrites it with measured numbers.
    """
    splits = _load_splits()
    return {
        "note": NOTE + " COMMITTED STATE: pending real run -- run the harness locally "
                "to populate real numbers (make eval / make eval-real).",
        "run_mode": "pending real run (committed placeholder)",
        "sizes": {s: len(splits[s]) for s in SPLITS},
        "category_families": sorted(CATEGORY_FAMILIES),
        "systems": {key: {"status": "pending real run"}
                    for key, _ in [("A_v1_regex", 0), ("B_embeddings_only", 0),
                                   ("C_embeddings_slm", 0), ("D_embeddings_lr", 0),
                                   ("E_lr_then_slm", 0)]},
        "detectors": {s: {"status": "pending real run"} for s in SPLITS},
        "thresholds": {"status": "pending real run"},
        "pii_leak_check": {"status": "pending real run"},
        "fallback_limit": FALLBACK_LIMIT,
    }


def main() -> None:
    # `--pending` writes the committed placeholder (all tables pending). A plain
    # run measures what it can (System A offline; B/C/D/E pending without models).
    import sys

    if "--pending" in sys.argv:
        results = pending_results()
        # Also write a pending error-analysis so the committed docs are consistent.
        os.makedirs(os.path.dirname(DEFAULT_ERROR_ANALYSIS_PATH) or ".", exist_ok=True)
        with open(DEFAULT_ERROR_ANALYSIS_PATH, "w", encoding="utf-8") as f:
            f.write("# Error analysis (v2, Round 3)\n\n"
                    "**pending real run** — run `make eval` (System A) or "
                    "`TRIAGE_EVAL_REAL=1 ... eval.harness_v2` to populate per-split "
                    "misclassifications (dev, test, unseen). No numbers are committed "
                    "until a run produces them.\n")
    else:
        results = run_eval()
    with open(DEFAULT_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"run mode: {results['run_mode']}")
    print(f"sizes: {results['sizes']}")
    for key, block in results["systems"].items():
        if block.get("status", "measured") != "measured":
            print(f"  {key}: {block['status']}")
            continue
        ot = block["overall_test"]
        uns = block["by_split"]["unseen"]
        print(f"  {key}: test acc={ot.get('accuracy')} macroF1={ot.get('macro_f1')} "
              f"| unseen acc={uns.get('accuracy')} | cost {block['cost']['cpu_seconds_per_item']}s/item")
    plc = results.get("pii_leak_check", {})
    if "items_with_leak" in plc:
        print(f"pii leak check: {plc['items_with_leak']} items leak")
    print(f"wrote {os.path.relpath(DEFAULT_RESULTS_PATH, ROOT)}")


if __name__ == "__main__":
    main()
