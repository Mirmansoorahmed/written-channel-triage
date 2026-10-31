"""v2 eval harness (V11-V17, review fixes #1/#2/#3/#5).

Compares up to three systems on the HELD-OUT test split (data/test.jsonl):
  A  v1 regex/keyword      (always runs; stdlib only)
  B  embeddings-only       (needs the embedding model)
  C  embeddings + SLM      (needs the embedding model + Ollama)

For each system it records category accuracy, macro-F1, per-class precision/recall,
a confusion matrix (JSON here, PNG+CSV on disk), and latency p50/p95. It also runs
the phishing / injection / PII detectors once over the split and reports their
precision/recall. All numbers come from the run; nothing is invented.

Scoring is broken out per split bucket (review fix #5):
  * seen-template   -- test items whose template_id also appears in train. With
    the template-family split this should be EMPTY; reporting it (as 0) is the
    evidence that leakage is gone.
  * unseen-template -- test items whose template was never in train (the normal
    held-out case under template-family splitting).
  * unseen          -- the hand-varied eval/unseen/ set (new phrasings and attack
    styles, legitimate portal emails). Reported as a separate score.

System C honesty (review fix #3): fallbacks / invalid categories / timeouts / JSON
failures are counted and reported, and a confidence histogram is emitted. The SLM
client runs strict, so an unavailable model fails loudly (the harness marks B/C
pending) instead of a silent-baseline run masquerading as measured.

Leakage gate (review fix #1): before scoring, the harness runs the overlap check;
if any test item is >= 0.9 similar to a train/example item it aborts with an error.

PII leak check (review fix #2): measured against the generator's ground-truth PII
values (`pii_truth`), not the masker's own regex.

Outputs:
  eval/results-v2.json
  eval/confusion_<system>.csv / .png     (per system that ran)
  docs/error-analysis.md                 (per split bucket)
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter

from triage import pii, pipeline
from triage.models import Source
from eval import metrics
from eval.systems import SystemA, build_real_systems

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA_DIR = os.path.join(ROOT, "data")
TEST_PATH = os.path.join(DATA_DIR, "test.jsonl")
TRAIN_PATH = os.path.join(DATA_DIR, "train.jsonl")
UNSEEN_PATH = os.path.join(HERE, "unseen", "unseen.jsonl")
RESULTS_PATH = os.path.join(HERE, "results-v2.json")
ERROR_ANALYSIS_PATH = os.path.join(ROOT, "docs", "error-analysis.md")

NOTE = ("Synthetic data only; fictional NordTel GmbH. Not a certification. "
        "All numbers are produced by this eval run. Split is by template family; "
        "the unseen set is hand-varied and never seen by the model.")


def _load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("_meta"):
                continue
            rows.append(obj)
    return rows


def _masked(text: str) -> str:
    return pii.mask(text).masked_text


def _bucketise(test_rows: list[dict], train_rows: list[dict]) -> dict[str, list[dict]]:
    """Split test rows into seen-template vs unseen-template buckets."""
    train_templates = {r.get("template_id") for r in train_rows if r.get("template_id")}
    seen, unseen = [], []
    for r in test_rows:
        if r.get("template_id") and r["template_id"] in train_templates:
            seen.append(r)
        else:
            unseen.append(r)
    return {"seen_template": seen, "unseen_template": unseen}


# --- per-system category scoring + latency --------------------------------


def _score_rows(system, rows: list[dict]) -> tuple[dict, list[dict]]:
    """Return (metrics_block, errors) for one system over `rows`."""
    y_true, y_pred, latencies, errors = [], [], [], []
    for r in rows:
        masked = _masked(r["text"])
        t0 = time.perf_counter()
        label, _conf = system.classify(masked)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        y_true.append(r["category"])
        y_pred.append(label)
        if label != r["category"]:
            errors.append({
                "id": r["id"], "family": r["family"],
                "expected": r["category"], "predicted": label,
                "masked_excerpt": masked[:160].replace("\n", " "),
            })
    if not rows:
        return {"status": "empty", "n": 0}, []
    report = metrics.classification_report(y_true, y_pred)
    report["latency"] = metrics.latency_summary(latencies)
    report["n"] = len(rows)
    report["status"] = "measured"
    return report, errors


def _score_system(system, buckets: dict[str, list[dict]], unseen_rows: list[dict]):
    """Score a system across all buckets. Returns (block, errors_by_bucket)."""
    block: dict = {"label": system.label, "status": "measured", "by_split": {}}
    errors_by_bucket: dict[str, list[dict]] = {}
    combined_true, combined_pred, combined_lat = [], [], []

    all_buckets = dict(buckets)
    all_buckets["unseen"] = unseen_rows
    for name, rows in all_buckets.items():
        rep, errs = _score_rows(system, rows)
        block["by_split"][name] = rep
        errors_by_bucket[name] = errs

    # Overall = the held-out test split (seen + unseen_template), not the unseen set.
    test_rows = buckets["seen_template"] + buckets["unseen_template"]
    overall, _ = _score_rows(system, test_rows)
    block["overall_test"] = overall

    # System C diagnostics (review fix #3).
    stats = getattr(system, "stats", None)
    if stats:
        block["slm_diagnostics"] = {
            "calls": stats.get("calls", 0),
            "fallbacks": stats.get("fallbacks", 0),
            "invalid_category": stats.get("invalid_category", 0),
            "timeouts": stats.get("timeouts", 0),
            "json_failures": stats.get("json_failures", 0),
            "connection_errors": stats.get("connection_errors", 0),
            "confidence_histogram": metrics.confidence_histogram(
                stats.get("confidences", [])
            ),
        }
    return block, errors_by_bucket


# --- detectors over the split (PII uses ground truth) ----------------------


def _score_detectors(rows: list[dict], label: str) -> dict:
    ph_true, ph_pred, inj_true, inj_pred = [], [], [], []
    pii_cases = pii_leaks = 0
    leaked_examples: list[dict] = []

    for r in rows:
        req_source = Source.EML if r["source"] == "eml" else Source.FORM
        result = pipeline.run(r["text"], source=req_source)
        ph_true.append(bool(r["is_phishing"]))
        ph_pred.append(result.phishing.suspected)
        inj_true.append(bool(r["is_injection"]))
        inj_pred.append(result.injection.detected)
        if r.get("has_pii"):
            pii_cases += 1
            masked = _masked(r["text"])
            # Ground-truth leak check (review fix #2): compare to the TRUE values.
            leaks = pii.ground_truth_leaks(masked, r.get("pii_truth", []))
            if leaks:
                pii_leaks += 1
                if len(leaked_examples) < 10:
                    leaked_examples.append({"id": r["id"], "leaked": leaks})

    out = {
        "split": label,
        "phishing": metrics.detection_prf(ph_true, ph_pred),
        "injection": metrics.detection_prf(inj_true, inj_pred),
        "pii_masking_ground_truth": {
            "cases": pii_cases,
            "leaks": pii_leaks,
            "no_leak": pii_cases - pii_leaks,
            "recall": round((pii_cases - pii_leaks) / pii_cases, 4) if pii_cases else None,
            "leaked_examples": leaked_examples,
        },
    }
    return out


# --- artifacts -------------------------------------------------------------


def _write_confusion_csv(system_key: str, report: dict) -> str:
    labels = report["confusion_matrix"]["labels"]
    mat = report["confusion_matrix"]["matrix"]
    path = os.path.join(HERE, f"confusion_{system_key}.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("true\\pred," + ",".join(labels) + "\n")
        for lab, row in zip(labels, mat):
            f.write(lab + "," + ",".join(str(c) for c in row) + "\n")
    return path


def _write_confusion_png(system_key: str, report: dict) -> str | None:
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
    ax.set_title(f"Confusion — {system_key}")
    for i in range(len(labels)):
        for j in range(len(labels)):
            if mat[i][j]:
                ax.text(j, i, str(mat[i][j]), ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    path = os.path.join(HERE, f"confusion_{system_key}.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _write_error_analysis(all_errors: dict[str, dict[str, list[dict]]]) -> None:
    lines = ["# Error analysis (v2)\n"]
    lines.append(
        "This file is **generated** by `eval/harness_v2.py` from the actual "
        "misclassifications of the latest run. Results are broken out per split "
        "bucket: **seen-template** (test items whose template is also in train -- "
        "empty under the template-family split, which is the point), "
        "**unseen-template** (the normal held-out test items), and **unseen** (the "
        "hand-varied `eval/unseen/` set). A system that did not run has no section.\n"
    )
    for key, by_bucket in all_errors.items():
        lines.append(f"## System {key}\n")
        for bucket in ("seen_template", "unseen_template", "unseen"):
            errors = by_bucket.get(bucket, [])
            lines.append(f"### Split: {bucket}\n")
            lines.append(f"- Misclassified: **{len(errors)}**\n")
            if not errors:
                lines.append("No category errors in this bucket.\n")
                continue
            pairs = Counter((e["expected"], e["predicted"]) for e in errors)
            lines.append("Most common confusions:\n")
            lines.append("| expected | predicted | count |")
            lines.append("|---|---|---|")
            for (exp, pred), n in pairs.most_common(8):
                lines.append(f"| {exp} | {pred} | {n} |")
            lines.append("")
            lines.append("Examples:\n")
            lines.append("| id | family | expected | predicted | masked excerpt |")
            lines.append("|---|---|---|---|---|")
            for e in errors[:10]:
                excerpt = e["masked_excerpt"].replace("|", "\\|")
                lines.append(
                    f"| {e['id']} | {e['family']} | {e['expected']} | "
                    f"{e['predicted']} | {excerpt} |"
                )
            lines.append("")
    os.makedirs(os.path.dirname(ERROR_ANALYSIS_PATH), exist_ok=True)
    with open(ERROR_ANALYSIS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# --- leakage gate ----------------------------------------------------------


def _assert_no_leakage(threshold: float = 0.9) -> None:
    from data.overlap_check import check

    violations = check(threshold)
    if violations:
        raise SystemExit(
            f"ABORT: leakage gate failed -- {len(violations)} test item(s) >= "
            f"{threshold} similar to a train/example item. Run "
            f"`python -m data.overlap_check` for detail."
        )


# --- main ------------------------------------------------------------------


def run_eval(real: bool | None = None) -> dict:
    if real is None:
        real = os.environ.get("TRIAGE_EVAL_REAL") == "1"

    _assert_no_leakage()  # review fix #1: hard gate before any scoring

    test_rows = _load_jsonl(TEST_PATH)
    train_rows = _load_jsonl(TRAIN_PATH)
    unseen_rows = _load_jsonl(UNSEEN_PATH) if os.path.exists(UNSEEN_PATH) else []
    buckets = _bucketise(test_rows, train_rows)

    systems = [SystemA()]
    pending: dict[str, str] = {}
    real_status = "offline subset (System A only)"

    if real:
        try:
            extra, _retriever = build_real_systems()
            systems.extend(extra)
            real_status = "all three systems (real models)"
        except Exception as exc:  # noqa: BLE001 - degrade to pending, never silent
            msg = f"pending real run: {type(exc).__name__}: {exc}"
            pending["B_embeddings_only"] = msg
            pending["C_embeddings_slm"] = msg
            real_status = f"offline subset (real models unavailable: {type(exc).__name__})"
    else:
        pending["B_embeddings_only"] = "pending real run"
        pending["C_embeddings_slm"] = "pending real run"

    systems_block: dict[str, dict] = {}
    all_errors: dict[str, dict[str, list[dict]]] = {}

    for system in systems:
        block, errors_by_bucket = _score_system(system, buckets, unseen_rows)
        systems_block[system.key] = block
        all_errors[system.key] = errors_by_bucket
        if "confusion_matrix" in block.get("overall_test", {}):
            _write_confusion_csv(system.key, block["overall_test"])
            png = _write_confusion_png(system.key, block["overall_test"])
            block["overall_test"]["confusion_png"] = (
                os.path.relpath(png, ROOT) if png else "not rendered (matplotlib absent)"
            )

    for key, status in pending.items():
        systems_block[key] = {"status": status}

    detectors = {
        "test": _score_detectors(test_rows, "test"),
        "unseen": _score_detectors(unseen_rows, "unseen") if unseen_rows else None,
    }

    _write_error_analysis(all_errors)

    return {
        "note": NOTE,
        "run_mode": real_status,
        "sizes": {
            "test": len(test_rows),
            "seen_template": len(buckets["seen_template"]),
            "unseen_template": len(buckets["unseen_template"]),
            "unseen_handvaried": len(unseen_rows),
            "train": len(train_rows),
        },
        "systems": systems_block,
        "detectors": detectors,
    }


def main() -> None:
    results = run_eval()
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"run mode: {results['run_mode']}")
    print(f"sizes: {results['sizes']}")
    for key, block in results["systems"].items():
        if block.get("status", "measured") != "measured":
            print(f"  {key}: {block['status']}")
            continue
        ot = block.get("overall_test", {})
        uns = block.get("by_split", {}).get("unseen", {})
        print(f"  {key}: test acc={ot.get('accuracy')} macroF1={ot.get('macro_f1')} "
              f"| unseen acc={uns.get('accuracy')}")
    print(f"wrote {os.path.relpath(RESULTS_PATH, ROOT)}")


if __name__ == "__main__":
    main()
