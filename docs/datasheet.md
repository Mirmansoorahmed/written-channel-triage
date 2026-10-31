# Datasheet — synthetic written-support corpus (v2)

This file is **generated** by `data/datasheet.py` from `data/*.jsonl`. Every number below is counted from the data; none is hand-typed. Regenerate with `make datasheet`.

## What this is

Synthetic German/English written customer-support messages (email + form text) for the **fictional** NordTel GmbH. All values are invented and in obviously fake ranges. There is no real brand, person, or data, and this is not a certification. The set is produced by a seeded generator so it is identical for anyone who runs it.

- Generator seed: `20251031`
- Total items: **1670**
- Splits: train 1154, dev 244, test 272 (test is held out)

The test split is held out: the eval reads only `test.jsonl` and the generator never tunes on it.

## Split sizes

| split | items | share |
|---|---|---|
| train | 1154 | 69.1% |
| dev | 244 | 14.6% |
| test | 272 | 16.3% |
| total | 1670 | 100.0% |

## Category distribution (per split)

| category | train | dev | test | total |
|---|---|---|---|---|
| Beschwerde | 89 | 18 | 22 | 129 |
| Datenschutz | 85 | 18 | 20 | 123 |
| Kündigung | 85 | 18 | 20 | 123 |
| Rechnung | 276 | 59 | 65 | 400 |
| Sonstiges | 187 | 40 | 41 | 268 |
| Störung | 89 | 19 | 22 | 130 |
| Tarifwechsel | 89 | 18 | 22 | 129 |
| Technik-Setup | 84 | 18 | 20 | 122 |
| Umzug | 85 | 18 | 20 | 123 |
| Vertrag | 85 | 18 | 20 | 123 |

## Family distribution (per split)

| family | train | dev | test | total |
|---|---|---|---|---|
| injection_base64 | 28 | 6 | 6 | 40 |
| injection_homoglyph | 28 | 6 | 6 | 40 |
| injection_negative | 25 | 4 | 11 | 40 |
| injection_plain | 28 | 6 | 6 | 40 |
| injection_spaced | 28 | 6 | 6 | 40 |
| normal | 700 | 150 | 150 | 1000 |
| out_of_hours | 50 | 10 | 20 | 80 |
| phishing | 125 | 27 | 28 | 180 |
| phishing_negative | 62 | 13 | 15 | 90 |
| pii_heavy | 80 | 16 | 24 | 120 |

## Email authentication results (whole corpus)

| auth | items | share |
|---|---|---|
| fail | 301 | 18.0% |
| missing | 1022 | 61.2% |
| pass | 347 | 20.8% |

## Label prevalence (whole corpus)

| label | positives | share |
|---|---|---|
| is_phishing | 180 | 10.8% |
| is_injection | 160 | 9.6% |
| has_pii | 354 | 21.2% |
| out_of_hours | 197 | 11.8% |

## Source (eml vs form)

| source | items | share |
|---|---|---|
| eml | 803 | 48.1% |
| form | 867 | 51.9% |

## How it was generated

- Templates per category with a tone knob (formal / casual / annoyed), a seeded typo injector, and a German/English phrase mixer.
- Email items carry a realistic `Authentication-Results` header drawn from {pass, fail, missing}; form items have no headers.
- Attack/PII families are generated explicitly: phishing (with near-miss legitimate-invoice negatives), prompt injection in four obfuscation modes (plain, spaced-out, homoglyph, base64) plus benign look-alikes, PII-heavy, and out-of-hours.
- Split is stratified by `(category, family)` so each class appears in every split.

## Known limits

This is synthetic data built to exercise the pipeline, not a sample of real traffic. Results measured on it describe behaviour on these cases only and are not a benchmark.

