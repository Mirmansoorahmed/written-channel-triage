# Control mapping

This maps each control in the triage pipeline to the frameworks I care about. I use
only the control/clause **ID** plus a **short title in my own words** — I do not copy
any text from ISO/IEC 27001, 27002, 42001, BSI C5, IT-Grundschutz, DORA or NIS2.

This is a portfolio project on a fictional telco. Nothing here is a certification, and
I do not claim "certified", "compliant" or "audit-ready". The machine-readable version
is in `soa.json` and reuses the shape from my `iso27001-evidence-as-code` project.

Framework IDs referenced:
- **ISO 27001 Annex A** (2022 control numbering, e.g. A.5.x / A.8.x)
- **ISO 42001** (AI management system Annex A, e.g. A.6.2.x)
- **NIS2 Article 21(2)** risk-management measures, by sub-point (a–j)
- **EU AI Act** by article (Art.12 logging, Art.14 human oversight, Art.50 transparency)

| Control (my words) | Code | ISO 27001 | ISO 42001 | NIS2 Art.21 | AI Act |
|---|---|---|---|---|---|
| Sender-trust check (SPF/DKIM/DMARC) | `ingest.py` | A.5.14, A.8.16 | A.6.2.6 | 21.2.d | — |
| Rule-based phishing flags | `ingest.py` | A.5.7, A.8.23 | — | 21.2.a | — |
| Mask PII before any model call | `pii.py` | A.5.34, A.8.11 | A.7.4 | 21.2.i | — |
| Local classification over my categories | `classify.py`, `categories.py`, `llm.py` | A.8.25 | A.6.2.2, A.6.2.4 | — | — |
| Prompt-injection detector on masked text | `injection.py` | A.8.26, A.8.28 | A.6.2.6 | 21.2.e | — |
| No auto-execution of account changes | `policy.py` | A.5.15, A.8.2 | A.9.2 | 21.2.d | Art.14 |
| AI transparency line on output | `output.py` | — | A.8.2 | — | Art.50 |
| Queue out-of-hours (never silently close) | `output.py` | A.5.26 | — | 21.2.b | — |
| Tamper-evident audit log (hash chain) | `audit.py` | A.8.15, A.8.16 | A.6.2.8 | 21.2.d | Art.12 |

## How to read this

Each row is one explainable control in the pipeline. "Code" points to where it lives so a
reviewer can jump straight to the implementation and its tests. The framework columns are
the IDs I think the control speaks to — my own judgement, not an auditor's finding.

For the "why" behind each decision, see `LEARNINGS.md`. For the numbers the controls
produce on the synthetic corpus, see `eval/results.json`.
