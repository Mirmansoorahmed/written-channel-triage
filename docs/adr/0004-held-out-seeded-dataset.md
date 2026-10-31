# ADR 0004 — A seeded, held-out synthetic dataset

Status: accepted (v2)

## Context
v1's 199-case corpus was enough to expose two real gaps, but too small to trust a
three-system comparison, and it was defined inline in the eval. To compare systems fairly
I need a larger set, a held-out test split, and bit-for-bit reproducibility so the customer
and I run the identical data.

## Decision
Add `data/generator.py`: ~1,670 labelled items from templates with a tone knob, a seeded
typo injector, a German/English mixer, realistic `Authentication-Results` headers, and
explicit attack/PII families (phishing + legitimate-invoice negatives; injection in four
obfuscation modes + benign look-alikes; PII-heavy; out-of-hours). One fixed seed
(`20251031`) makes the set identical for everyone; the seed is recorded in each file. Split
is stratified by `(category, family)` into train/dev/test; the test split is held out and
the eval reads only `test.jsonl`. `data/datasheet.py` generates the distribution tables.

## Consequences
- Anyone who runs the generator gets the exact same files (verified by hashing two runs).
- The eval numbers describe behaviour on a known, documented distribution, and the test
  split is never tuned on.
- It is still synthetic data: results are not a benchmark and say nothing about real
  traffic. The datasheet states this plainly.
- Committing ~1,670 JSONL lines to the repo is a deliberate trade for reproducibility over
  repo size.
