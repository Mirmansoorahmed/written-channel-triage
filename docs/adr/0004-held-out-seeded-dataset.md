# ADR 0004 — A seeded, template-family-split synthetic dataset

Status: accepted (v2; split method revised after a leakage review)

## Context
v1's 199-case corpus was enough to expose two real gaps, but too small to trust a
three-system comparison. The first v2 cut grew it but split train/dev/test **randomly
within each stratum**, which a review showed was leaky: the same template string landed in
both train and test, so ~67% of test items had a >=0.95-similar twin in train, and most
few-shot examples were verbatim copies of generator templates. Numbers measured that way
flatter the model.

## Decision
Add `data/generator.py`: ~2,050 labelled items from numbered templates with a tone knob, a
seeded typo injector (applied to the whole message, including PII labels), a German/English
mixer, realistic `Authentication-Results` headers, and explicit attack/PII families
(phishing + legitimate-invoice negatives; injection in four obfuscation modes + benign
look-alikes; PII-heavy; out-of-hours). One fixed seed (`20251031`) makes the set identical
for everyone, using a stable hashlib-based assignment so it is reproducible regardless of
`PYTHONHASHSEED`.

The split is **by template family**: every template is assigned to exactly one split, so a
template string never appears in more than one split. Injection payloads are split by
payload (all four obfuscation modes of a payload share a split), because an obfuscated copy
normalises back to its plain form. The model-facing few-shot and injection/phishing
exemplars are rewritten to be distinct from the generator. `data/overlap_check.py` is a
hard gate: the eval aborts if any test item is >= 0.9 similar to a train or example item.
Each item records `pii_truth` (the raw values placed) so leak checks use ground truth.

## Consequences
- Anyone who runs the generator gets the exact same files (verified by hashing two runs
  under different `PYTHONHASHSEED`).
- Test accuracy and detector recall now reflect **unseen templates**, and a separate
  hand-varied `eval/unseen/` set measures true generalisation. The gap between the two is
  reported on purpose.
- The leakage gate makes a regression (a leaked template, a copied exemplar) a build
  failure, not a silent credibility problem.
- Template-family splitting with only 3–5 templates per category makes the split sizes
  less even than a random split would; this is the honest cost of keeping templates out of
  each other's splits.
- It is still synthetic data: results are not a benchmark and say nothing about real
  traffic. The datasheet states this plainly.
