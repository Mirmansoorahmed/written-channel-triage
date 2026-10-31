"""Generate the README and architecture tables from eval/results-v2.json (Round 3).

Every number in the results, cost and calibration tables comes from a run -- none
is hand-typed. Pending systems render as "pending real run" with no invented value.
Run with `make docs` after an eval.

Cost model (documented, auditable): cost per 1,000 messages =
    cpu_seconds_per_item * 1000 * VM_HOURLY_USD / (3600 * VM_VCPUS)
The VM price is an ASSUMPTION, clearly labelled with its source and date; swap it
for your own. RAM needed is the measured peak RSS.

Markers in the target files:
  <!-- BEGIN:results-table --> ... <!-- END:results-table -->
  <!-- BEGIN:detector-table --> ... <!-- END:detector-table -->
  <!-- BEGIN:cost-table --> ... <!-- END:cost-table -->
  <!-- BEGIN:calibration-table --> ... <!-- END:calibration-table -->
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
RESULTS_PATH = os.path.join(ROOT, "eval", "results-v2.json")
README_PATH = os.path.join(ROOT, "README.md")
ARCH_PATH = os.path.join(HERE, "architecture.md")

# --- VM price assumption (clearly labelled; not a measured number) ----------
# Example on-demand price for a general-purpose 4 vCPU / 16 GB Linux VM. Source
# and date are shown in the rendered table so a reader can replace it.
VM_VCPUS = 4
VM_RAM_GB = 16
VM_HOURLY_USD = 0.1920  # assumption: AWS m6i.xlarge on-demand, eu-central-1
VM_PRICE_SOURCE = "example AWS m6i.xlarge on-demand, eu-central-1 (assumption, 2025)"

SYSTEM_ORDER = [
    ("A_v1_regex", "A - v1 regex/keyword"),
    ("B_embeddings_only", "B - embeddings-only"),
    ("C_embeddings_slm", "C - embeddings + SLM"),
    ("D_embeddings_lr", "D - embeddings + LR"),
    ("E_lr_then_slm", "E - LR, SLM on low conf"),
]


def _load() -> dict:
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _fmt(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.4f}"
    return f"{x}"


def _replace_block(text: str, marker: str, body: str) -> str:
    begin = f"<!-- BEGIN:{marker} -->"
    end = f"<!-- END:{marker} -->"
    if begin not in text or end not in text:
        raise SystemExit(f"marker '{marker}' not found in target file")
    pre = text.split(begin)[0]
    post = text.split(end, 1)[1]
    return f"{pre}{begin}\n{body}\n{end}{post}"


def _measured(block: dict) -> bool:
    return block.get("status", "measured") == "measured"


def _results_table(data: dict) -> str:
    rows = ["| system | split | accuracy | macro-F1 | latency p50 / p95 ms |",
            "|---|---|---|---|---|"]
    systems = data["systems"]
    for key, label in SYSTEM_ORDER:
        block = systems.get(key, {})
        if not _measured(block):
            rows.append(f"| {label} | - | pending real run | pending real run | pending real run |")
            continue
        for split in ("test", "unseen"):
            rep = block.get("by_split", {}).get(split, {})
            if not rep or rep.get("status") != "measured" or "accuracy" not in rep:
                continue
            lat = rep.get("latency", {})
            p50, p95 = lat.get("p50_ms"), lat.get("p95_ms")
            latcell = f"{_fmt(p50)} / {_fmt(p95)}" if p50 is not None else "-"
            shown = "test (held out)" if split == "test" else "unseen (hand-varied)"
            rows.append(f"| {label} | {shown} | {_fmt(rep.get('accuracy'))} | "
                        f"{_fmt(rep.get('macro_f1'))} | {latcell} |")
    return "\n".join(rows)


def _detector_table(data: dict) -> str:
    det = data.get("detectors", {})
    rows = ["| detector | split | precision | recall |", "|---|---|---|---|"]
    for split in ("test", "unseen"):
        block = det.get(split)
        if not block or block.get("status") == "pending real run":
            rows.append(f"| (all) | {split} | pending real run | pending real run |")
            continue
        for fam in ("phishing", "injection"):
            d = block.get(fam, {})
            rows.append(f"| {fam} | {split} | {_fmt(d.get('precision'))} | {_fmt(d.get('recall'))} |")
        p = block.get("pii_masking_ground_truth", {})
        rows.append(f"| PII masking (fuzzy ground-truth) | {split} | - | {_fmt(p.get('recall'))} |")
    return "\n".join(rows)


def _cost_table(data: dict) -> str:
    rows = [
        f"VM price assumption: **${VM_HOURLY_USD}/h** for {VM_VCPUS} vCPU / {VM_RAM_GB} GB "
        f"({VM_PRICE_SOURCE}).",
        "",
        "| system | CPU s / item | cost per 1k msg (USD) | peak RSS (MB) |",
        "|---|---|---|---|",
    ]
    systems = data["systems"]
    for key, label in SYSTEM_ORDER:
        block = systems.get(key, {})
        if not _measured(block):
            rows.append(f"| {label} | pending real run | pending real run | pending real run |")
            continue
        cost = block.get("cost", {})
        cpu = cost.get("cpu_seconds_per_item")
        rss = cost.get("peak_rss_mb")
        if cpu is None:
            rows.append(f"| {label} | - | - | {_fmt(rss)} |")
            continue
        per_1k = cpu * 1000 * VM_HOURLY_USD / (3600 * VM_VCPUS)
        rows.append(f"| {label} | {cpu:.6f} | {per_1k:.4f} | {_fmt(rss)} |")
    return "\n".join(rows)


def _calibration_table(data: dict) -> str:
    rows = ["| system | ECE (test) | note |", "|---|---|---|"]
    systems = data["systems"]
    for key, label in SYSTEM_ORDER:
        block = systems.get(key, {})
        if not _measured(block):
            rows.append(f"| {label} | pending real run | - |")
            continue
        cal = block.get("overall_test", {}).get("calibration", {})
        ece = cal.get("ece") if cal else None
        note = ""
        if key == "C_embeddings_slm":
            note = "self-reported confidence near-constant; not used to route"
        elif key == "D_embeddings_lr":
            note = "calibrated on dev (sigmoid); used for the review threshold"
        rows.append(f"| {label} | {_fmt(ece)} | {note} |")
    return "\n".join(rows)


def main() -> None:
    data = _load()

    with open(README_PATH, encoding="utf-8") as f:
        readme = f.read()
    readme = _replace_block(readme, "results-table", _results_table(data))
    readme = _replace_block(readme, "detector-table", _detector_table(data))
    if "<!-- BEGIN:cost-table -->" in readme:
        readme = _replace_block(readme, "cost-table", _cost_table(data))
    if "<!-- BEGIN:calibration-table -->" in readme:
        readme = _replace_block(readme, "calibration-table", _calibration_table(data))
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(readme)

    with open(ARCH_PATH, encoding="utf-8") as f:
        arch = f.read()
    arch = _replace_block(arch, "cost-table", _cost_table(data))
    if "<!-- BEGIN:calibration-table -->" in arch:
        arch = _replace_block(arch, "calibration-table", _calibration_table(data))
    with open(ARCH_PATH, "w", encoding="utf-8") as f:
        f.write(arch)

    print("regenerated README + architecture tables from eval/results-v2.json")


if __name__ == "__main__":
    main()
