"""v2 eval harness (V11-V17).

Compares up to three systems on the HELD-OUT test split (data/test.jsonl):
  A  v1 regex/keyword      (always runs; stdlib only)
  B  embeddings-only       (needs the embedding model)
  C  embeddings + SLM      (needs the embedding model + Ollama)

For each system it records category accuracy, macro-F1, per-class precision/recall,
a confusion matrix (JSON here, PNG+CSV on disk), and latency p50/p95. It also runs
the phishing / injection / PII detectors once over the split and reports their
precision/recall. All numbers come from the run; nothing is invented.

Offline vs real:
  * By default (and in CI) only System A runs. Systems B and C are written to the
    results as {"status": "pending real run"} with no numbers, and the confusion
    PNG/CSV + error analysis are produced for System A only.
  * Set TRIAGE_EVAL_REAL=1 (``make eval-real``) to build B and C with the real
    models. If the model libraries or the Ollama server are missing, the harness
    degrades to the offline subset and records why.

Outputs:
  eval/results-v2.json
  eval/confusion_<system>.csv           (per system that ran)
  eval/confusion_<system>.png           (if matplotlib is available)
  docs/error-analysis.md                (from the real misclassifications)
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
TEST_PATH = os.path.join(ROOT, "data", "test.jsonl")
RESULTS_PATH = os.path.join(HERE, "results-v2.json")
ERROR_ANALYSIS_PATH = os.path.join(ROOT, "docs", "error-analysis.md")

NOTE = ("Synthetic data only; fictional NordTel GmbH. Not a certification. "
        "All numbers are produced by this eval run over the held-out test split.")


def _load_test() -> list[dict]:
    rows = []
    with open(TEST_PATH, encoding="utf-8") as f:
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


# --- per-system category scoring + latency --------------------------------


def _score_system(system, rows: list[dict]) -> tuple[dict, list[dict]]:
    """Return (metrics_block, errors) for one system over the test rows."""
    y_true: list[str] = []
    y_pred: list[str] = []
    latencies: list[float] = []
    errors: list[dict] = []

    for r in rows:
        masked = _masked(r["text"])
        t0 = time.perf_counter()
        label, _conf = system.classify(masked)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        y_true.append(r["category"])
        y_pred.append(label)
        if label != r["category"]:
            errors.append({
                "id": r["id"],
                "family": r["family"],
                "expected": r["category"],
                "predicted": label,
                "masked_excerpt": masked[:160].replace("\n", " "),
            })

    report = metrics.classification_report(y_true, y_pred)
    report["latency"] = metrics.latency_summary(latencies)
    report["status"] = "measured"
    return report, errors


# --- detectors over the split ---------------------------------------------


def _score_detectors(rows: list[dict]) -> dict:
    ph_true, ph_pred = [], []
    inj_true, inj_pred = [], []
    pii_true, pii_pred = [], []

    for r in rows:
        req_source = Source.EML if r["source"] == "eml" else Source.FORM
        result = pipeline.run(r["text"], source=req_source)
        ph_true.append(bool(r["is_phishing"]))
        ph_pred.append(result.phishing.suspected)
        inj_true.append(bool(r["is_injection"]))
        inj_pred.append(result.injection.detected)
        # PII "detection" = for PII-heavy cases, no raw PII survives masking.
        if r["has_pii"]:
            pii_true.append(True)
            masked = _masked(r["text"])
            pii_pred.append(not pii.contains_raw_pii(masked))

    out = {
        "phishing": metrics.detection_prf(ph_true, ph_pred),
        "injection": metrics.detection_prf(inj_true, inj_pred),
    }
    if pii_true:
        ok = sum(1 for p in pii_pred if p)
        out["pii_masking"] = {
            "cases": len(pii_true),
            "no_leak": ok,
            "recall": round(ok / len(pii_true), 4),
        }
    else:
        out["pii_masking"] = {"cases": 0, "no_leak": 0, "recall": None}
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


def _write_error_analysis(all_errors: dict[str, list[dict]]) -> None:
    lines = ["# Error analysis (v2)\n"]
    lines.append(
        "This file is **generated** by `eval/harness_v2.py` from the actual "
        "misclassifications of the latest run over the held-out test split. If a system "
        "did not run (pending real model), it has no section here.\n"
    )
    for key, errors in all_errors.items():
        lines.append(f"## System {key}\n")
        lines.append(f"- Misclassified: **{len(errors)}**\n")
        if not errors:
            lines.append("No category errors on the test split.\n")
            continue
        # Most common confusion pairs.
        pairs = Counter((e["expected"], e["predicted"]) for e in errors)
        lines.append("### Most common confusions\n")
        lines.append("| expected | predicted | count |")
        lines.append("|---|---|---|")
        for (exp, pred), n in pairs.most_common(10):
            lines.append(f"| {exp} | {pred} | {n} |")
        lines.append("")
        lines.append("### Examples\n")
        lines.append("| id | family | expected | predicted | masked excerpt |")
        lines.append("|---|---|---|---|---|")
        for e in errors[:15]:
            excerpt = e["masked_excerpt"].replace("|", "\\|")
            lines.append(
                f"| {e['id']} | {e['family']} | {e['expected']} | "
                f"{e['predicted']} | {excerpt} |"
            )
        lines.append("")
    os.makedirs(os.path.dirname(ERROR_ANALYSIS_PATH), exist_ok=True)
    with open(ERROR_ANALYSIS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# --- main ------------------------------------------------------------------


def run_eval(real: bool | None = None) -> dict:
    if real is None:
        real = os.environ.get("TRIAGE_EVAL_REAL") == "1"

    rows = _load_test()
    systems = [SystemA()]
    pending: dict[str, str] = {}
    real_status = "offline subset (System A only)"

    if real:
        try:
            extra, _retriever = build_real_systems()
            systems.extend(extra)
            real_status = "all three systems (real models)"
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            pending["B_embeddings_only"] = f"pending real run: {type(exc).__name__}: {exc}"
            pending["C_embeddings_slm"] = f"pending real run: {type(exc).__name__}: {exc}"
            real_status = f"offline subset (real models unavailable: {type(exc).__name__})"
    else:
        pending["B_embeddings_only"] = "pending real run"
        pending["C_embeddings_slm"] = "pending real run"

    systems_block: dict[str, dict] = {}
    all_errors: dict[str, list[dict]] = {}

    for system in systems:
        report, errors = _score_system(system, rows)
        report["label"] = system.label
        systems_block[system.key] = report
        all_errors[system.key] = errors
        _write_confusion_csv(system.key, report)
        png = _write_confusion_png(system.key, report)
        report["confusion_png"] = os.path.relpath(png, ROOT) if png else "not rendered (matplotlib absent)"

    for key, status in pending.items():
        systems_block[key] = {"status": status}

    detectors = _score_detectors(rows)

    _write_error_analysis(all_errors)

    results = {
        "note": NOTE,
        "run_mode": real_status,
        "test_split_size": len(rows),
        "systems": systems_block,
        "detectors": detectors,
    }
    return results


def main() -> None:
    results = run_eval()
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"run mode: {results['run_mode']}")
    print(f"test split: {results['test_split_size']} items")
    for key, block in results["systems"].items():
        if block.get("status", "measured") != "measured":
            print(f"  {key}: {block['status']}")
        else:
            print(f"  {key}: acc={block['accuracy']} macroF1={block['macro_f1']} "
                  f"p50={block['latency']['p50_ms']}ms p95={block['latency']['p95_ms']}ms")
    print(f"wrote {os.path.relpath(RESULTS_PATH, ROOT)}")


if __name__ == "__main__":
    main()
