"""Generate the README results table and the architecture cost table (review #5).

Reads eval/results-v2.json and rewrites the marked blocks in README.md and
docs/architecture.md, so every number in those tables comes from a run -- none is
hand-typed. A system that is "pending real run" is rendered as such (no invented
values). Run with `make docs` after an eval.

Markers (kept verbatim in the target files):
  <!-- BEGIN:results-table --> ... <!-- END:results-table -->
  <!-- BEGIN:detector-table --> ... <!-- END:detector-table -->
  <!-- BEGIN:cost-table --> ... <!-- END:cost-table -->
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
RESULTS_PATH = os.path.join(ROOT, "eval", "results-v2.json")
README_PATH = os.path.join(ROOT, "README.md")
ARCH_PATH = os.path.join(HERE, "architecture.md")

SYSTEM_ORDER = [
    ("A_v1_regex", "A — v1 regex/keyword"),
    ("B_embeddings_only", "B — embeddings-only"),
    ("C_embeddings_slm", "C — embeddings + SLM"),
]


def _load() -> dict:
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _fmt(x) -> str:
    return "—" if x is None else (f"{x}" if not isinstance(x, float) else f"{x:.4f}")


def _replace_block(text: str, marker: str, body: str) -> str:
    begin = f"<!-- BEGIN:{marker} -->"
    end = f"<!-- END:{marker} -->"
    if begin not in text or end not in text:
        raise SystemExit(f"marker '{marker}' not found in target file")
    pre = text.split(begin)[0]
    post = text.split(end, 1)[1]
    return f"{pre}{begin}\n{body}\n{end}{post}"


def _results_table(data: dict) -> str:
    rows = ["| system | split | accuracy | macro-F1 | latency p50 / p95 ms |",
            "|---|---|---|---|---|"]
    systems = data["systems"]
    for key, label in SYSTEM_ORDER:
        block = systems.get(key, {})
        if block.get("status", "measured") != "measured":
            rows.append(f"| {label} | — | pending real run | pending real run | pending real run |")
            continue
        for split_name in ("overall_test", "unseen"):
            if split_name == "overall_test":
                rep = block.get("overall_test", {})
                shown = "test (held out)"
            else:
                rep = block.get("by_split", {}).get("unseen", {})
                shown = "unseen (hand-varied)"
            if not rep or rep.get("status") == "empty":
                continue
            lat = rep.get("latency", {})
            p50, p95 = lat.get("p50_ms"), lat.get("p95_ms")
            latcell = f"{_fmt(p50)} / {_fmt(p95)}" if p50 is not None else "—"
            rows.append(
                f"| {label} | {shown} | {_fmt(rep.get('accuracy'))} | "
                f"{_fmt(rep.get('macro_f1'))} | {latcell} |"
            )
    return "\n".join(rows)


def _detector_table(data: dict) -> str:
    det = data.get("detectors", {})
    rows = ["| detector | split | precision | recall |", "|---|---|---|---|"]
    for split in ("test", "unseen"):
        block = det.get(split)
        if not block:
            continue
        for fam in ("phishing", "injection"):
            d = block.get(fam, {})
            rows.append(
                f"| {fam} | {split} | {_fmt(d.get('precision'))} | {_fmt(d.get('recall'))} |"
            )
        pii = block.get("pii_masking_ground_truth", {})
        rows.append(
            f"| PII masking (ground-truth, no leak) | {split} | — | {_fmt(pii.get('recall'))} |"
        )
    return "\n".join(rows)


def _cost_table(data: dict) -> str:
    rows = ["| system | p50 latency ms | p95 latency ms | relative cost note |",
            "|---|---|---|---|"]
    notes = {
        "A_v1_regex": "~free (CPU, no model)",
        "B_embeddings_only": "one embedding encode per request",
        "C_embeddings_slm": "one encode + one SLM generate",
    }
    systems = data["systems"]
    for key, label in SYSTEM_ORDER:
        block = systems.get(key, {})
        note = notes[key]
        if block.get("status", "measured") != "measured":
            rows.append(f"| {label} | pending real run | pending real run | {note} |")
            continue
        lat = block.get("overall_test", {}).get("latency", {})
        rows.append(
            f"| {label} | {_fmt(lat.get('p50_ms'))} | {_fmt(lat.get('p95_ms'))} | {note} |"
        )
    return "\n".join(rows)


def main() -> None:
    data = _load()

    with open(README_PATH, encoding="utf-8") as f:
        readme = f.read()
    readme = _replace_block(readme, "results-table", _results_table(data))
    readme = _replace_block(readme, "detector-table", _detector_table(data))
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(readme)

    with open(ARCH_PATH, encoding="utf-8") as f:
        arch = f.read()
    arch = _replace_block(arch, "cost-table", _cost_table(data))
    with open(ARCH_PATH, "w", encoding="utf-8") as f:
        f.write(arch)

    print("regenerated README results/detector tables and architecture cost table "
          f"from {os.path.relpath(RESULTS_PATH, ROOT)}")


if __name__ == "__main__":
    main()
