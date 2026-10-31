"""Datasheet generator (V10).

Reads data/{train,dev,test}.jsonl and writes docs/datasheet.md with distribution
tables computed straight from the data -- no number in the datasheet is ever typed
by hand. Pure standard library.

The datasheet follows the spirit of a "datasheet for datasets": what the data is,
how it was made, and the measured distributions. It states plainly that the data
is synthetic and seeded.
"""

from __future__ import annotations

import json
import os
from collections import Counter

SPLITS = ("train", "dev", "test")
DATA_DIR = os.path.dirname(__file__)
OUT_PATH = os.path.join(DATA_DIR, "..", "docs", "datasheet.md")


def _load(split: str) -> list[dict]:
    path = os.path.join(DATA_DIR, f"{split}.jsonl")
    rows = []
    seed = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("_meta"):
                seed = obj.get("seed")
                continue
            rows.append(obj)
    return rows, seed


def _table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _count_by(rows: list[dict], key: str) -> Counter:
    return Counter(r[key] for r in rows)


def build() -> str:
    data = {s: _load(s) for s in SPLITS}
    seed = next((seed for (_rows, seed) in data.values() if seed is not None), None)
    all_rows = [r for s in SPLITS for r in data[s][0]]
    total = len(all_rows)

    lines: list[str] = []
    lines.append("# Datasheet — synthetic written-support corpus (v2)\n")
    lines.append(
        "This file is **generated** by `data/datasheet.py` from `data/*.jsonl`. Every "
        "number below is counted from the data; none is hand-typed. Regenerate with "
        "`make datasheet`.\n"
    )
    lines.append("## What this is\n")
    lines.append(
        "Synthetic German/English written customer-support messages (email + form text) "
        "for the **fictional** NordTel GmbH. All values are invented and in obviously "
        "fake ranges. There is no real brand, person, or data, and this is not a "
        "certification. The set is produced by a seeded generator so it is identical for "
        "anyone who runs it.\n"
    )
    lines.append(f"- Generator seed: `{seed}`")
    lines.append(f"- Total items: **{total}**")
    lines.append(f"- Splits: " + ", ".join(
        f"{s} {len(data[s][0])}" for s in SPLITS) + " (test is held out)\n")

    lines.append(
        "The test split is held out: the eval reads only `test.jsonl` and the generator "
        "never tunes on it.\n"
    )

    # Per-split totals
    lines.append("## Split sizes\n")
    lines.append(_table(
        ["split", "items", "share"],
        [[s, len(data[s][0]), f"{len(data[s][0]) / total:.1%}"] for s in SPLITS]
        + [["total", total, "100.0%"]]
    ))
    lines.append("")

    # Category distribution per split
    lines.append("## Category distribution (per split)\n")
    cats = sorted({r["category"] for r in all_rows})
    per = {s: _count_by(data[s][0], "category") for s in SPLITS}
    rows = []
    for c in cats:
        rows.append([c] + [per[s].get(c, 0) for s in SPLITS]
                    + [sum(per[s].get(c, 0) for s in SPLITS)])
    lines.append(_table(["category", *SPLITS, "total"], rows))
    lines.append("")

    # Family distribution per split
    lines.append("## Family distribution (per split)\n")
    fams = sorted({r["family"] for r in all_rows})
    perf = {s: _count_by(data[s][0], "family") for s in SPLITS}
    rows = []
    for fam in fams:
        rows.append([fam] + [perf[s].get(fam, 0) for s in SPLITS]
                    + [sum(perf[s].get(fam, 0) for s in SPLITS)])
    lines.append(_table(["family", *SPLITS, "total"], rows))
    lines.append("")

    # Auth-result distribution
    lines.append("## Email authentication results (whole corpus)\n")
    auth = _count_by(all_rows, "auth")
    lines.append(_table(
        ["auth", "items", "share"],
        [[a, auth[a], f"{auth[a] / total:.1%}"] for a in sorted(auth)]
    ))
    lines.append("")

    # Label prevalence
    lines.append("## Label prevalence (whole corpus)\n")
    flags = ["is_phishing", "is_injection", "has_pii", "out_of_hours"]
    lines.append(_table(
        ["label", "positives", "share"],
        [[fl, sum(1 for r in all_rows if r[fl]),
          f"{sum(1 for r in all_rows if r[fl]) / total:.1%}"] for fl in flags]
    ))
    lines.append("")

    # Source distribution
    lines.append("## Source (eml vs form)\n")
    src = _count_by(all_rows, "source")
    lines.append(_table(
        ["source", "items", "share"],
        [[s, src[s], f"{src[s] / total:.1%}"] for s in sorted(src)]
    ))
    lines.append("")

    lines.append("## How it was generated\n")
    lines.append(
        "- Templates per category with a tone knob (formal / casual / annoyed), a seeded "
        "typo injector, and a German/English phrase mixer.\n"
        "- Email items carry a realistic `Authentication-Results` header drawn from "
        "{pass, fail, missing}; form items have no headers.\n"
        "- Attack/PII families are generated explicitly: phishing (with near-miss "
        "legitimate-invoice negatives), prompt injection in four obfuscation modes "
        "(plain, spaced-out, homoglyph, base64) plus benign look-alikes, PII-heavy, and "
        "out-of-hours.\n"
        "- Split is stratified by `(category, family)` so each class appears in every "
        "split.\n"
    )
    lines.append("## Known limits\n")
    lines.append(
        "This is synthetic data built to exercise the pipeline, not a sample of real "
        "traffic. Results measured on it describe behaviour on these cases only and are "
        "not a benchmark.\n"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    text = build()
    out = os.path.normpath(OUT_PATH)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
