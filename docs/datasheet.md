# Datasheet — synthetic written-support corpus (v2)

This file is **generated** by `data/datasheet.py` from `data/*.jsonl`. Every number below is counted from the data; none is hand-typed. Regenerate with `make datasheet`.

## What this is

Synthetic German/English written customer-support messages (email + form text) for the **fictional** NordTel GmbH. All values are invented and in obviously fake ranges. There is no real brand, person, or data, and this is not a certification. The set is produced by a seeded generator so it is identical for anyone who runs it.

- Generator seed: `20251031`
- Total items: **2056**
- Splits: train 893, dev 569, test 594 (test is held out)

The test split is held out: the eval reads only `test.jsonl` and the generator never tunes on it.

## Split sizes

| split | items | share |
|---|---|---|
| train | 893 | 43.4% |
| dev | 569 | 27.7% |
| test | 594 | 28.9% |
| total | 2056 | 100.0% |

## Category distribution (per split)

| category | train | dev | test | total |
|---|---|---|---|---|
| Beschwerde | 53 | 46 | 46 | 145 |
| Datenschutz | 46 | 46 | 46 | 138 |
| Kündigung | 46 | 46 | 46 | 138 |
| Rechnung | 252 | 123 | 134 | 509 |
| Sonstiges | 122 | 82 | 82 | 286 |
| Störung | 99 | 46 | 46 | 191 |
| Tarifwechsel | 46 | 46 | 53 | 145 |
| Technik-Setup | 91 | 42 | 49 | 182 |
| Umzug | 46 | 46 | 46 | 138 |
| Vertrag | 92 | 46 | 46 | 184 |

## Family distribution (per split)

| family | train | dev | test | total |
|---|---|---|---|---|
| injection_base64 | 20 | 10 | 10 | 40 |
| injection_homoglyph | 20 | 10 | 10 | 40 |
| injection_negative | 21 | 7 | 14 | 42 |
| injection_plain | 20 | 10 | 10 | 40 |
| injection_spaced | 20 | 10 | 10 | 40 |
| normal | 600 | 400 | 400 | 1400 |
| out_of_hours | 30 | 20 | 20 | 70 |
| phishing | 78 | 52 | 52 | 182 |
| phishing_negative | 36 | 18 | 36 | 90 |
| pii_heavy | 48 | 32 | 32 | 112 |

## Email authentication results (whole corpus)

| auth | items | share |
|---|---|---|
| fail | 341 | 16.6% |
| missing | 1285 | 62.5% |
| pass | 430 | 20.9% |

## Label prevalence (whole corpus)

| label | positives | share |
|---|---|---|
| is_phishing | 182 | 8.9% |
| is_injection | 160 | 7.8% |
| has_pii | 428 | 20.8% |
| out_of_hours | 223 | 10.8% |

## Source (eml vs form)

| source | items | share |
|---|---|---|
| eml | 1012 | 49.2% |
| form | 1044 | 50.8% |

## How it was generated

- Numbered templates per category with a tone knob (formal / casual / annoyed), a seeded typo injector applied to the whole message (including PII labels, so the masker is tested against noise), and a German/English phrase mixer.
- Email items carry a realistic `Authentication-Results` header drawn from {pass, fail, missing}; form items have no headers.
- Attack/PII families are generated explicitly: phishing (with near-miss legitimate-invoice negatives), prompt injection in four obfuscation modes (plain, spaced-out, homoglyph, base64) plus benign look-alikes, PII-heavy, and out-of-hours.
- Split is **by template family**: each template is assigned to exactly one split, so a template string never appears in more than one split. The `data/overlap_check.py` gate enforces that no test item is >= 0.9 similar to a train or model-facing example.
- Each item records `pii_truth`, the raw PII values actually placed, so leak checks compare against ground truth rather than the masker's own regex.

## Known limits

This is synthetic data built to exercise the pipeline, not a sample of real traffic. Results measured on it describe behaviour on these cases only and are not a benchmark.

