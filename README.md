# written-channel-triage

One safe entry point for written customer support (email + web-form text) at a
**fictional** German telco, *NordTel GmbH*. It triages a message — checks the sender,
masks personal data, classifies the request, looks for prompt injection, and gates
risky actions — **before** anything reaches an LLM or a human.

This is a personal portfolio project. All test data is synthetic German text generated
in this repo. There is no real brand, no real customer data, and **nothing here is a
certification**.

## Why

Many German telcos dropped a general support email address and spread written requests
across many web forms; chat handoff is slow and has no upload. I wanted a single written
entry point that is safe and explainable by default.

## Pipeline (3-minute skim)

```
 raw .eml / form text
        │
        ▼
 [1] ingest + sender trust   → SPF/DKIM/DMARC verdict, phishing flags  (rule-based)
        │
        ▼
 [2] mask PII                 → reversible, in-memory token map
        │
        ▼
 [3] classify + extract       → ~10 own categories, local retrieval, pluggable LLM
        │
        ▼
 [4] injection detector       → runs on the masked text; on hit → no tool use
        │
        ▼
 [5] policy gate              → account changes → pending approval (never auto-run)
        │
        ▼
 [6] output                   → AI disclosure (AI Act Art.50), handoff summary,
                                out-of-hours queue, hash-chained JSONL audit log
```

Each step is a small module with its own tests, so each decision can be reviewed on its
own. A Mermaid version of the diagram is in [`docs/spec/design.md`](docs/spec/design.md).

## What is safe by default

- **Mask before the model.** No raw PII reaches the LLM, the human handoff, or the log.
- **Injection → no tools.** The detector runs on the masked text; a hit blocks tool use.
- **No auto account changes.** Tariff change, cancellation, address change and SEPA
  change always become a *pending approval* for a human. Read-only answers may proceed.
- **Never silently close.** Outside 07:00–23:00 a request is queued with an ETA.
- **Tamper-evident log.** Each JSONL line stores the SHA-256 of the previous one.

## Measured results

Numbers below come from `eval/results.json`, produced by running the eval over a
synthetic corpus of **104** German messages. I only report numbers the run produces.

| Check | Result |
|---|---|
| Category accuracy | 0.8942 (93/104) |
| Phishing detection | precision 1.0, recall 1.0 (tp 6, fp 0, fn 0) |
| Prompt-injection detection | precision 1.0, recall 1.0 (tp 5, fp 0, fn 0) |
| PII masking (no raw leak) | recall 1.0 (7/7 PII-heavy cases) |
| Out-of-hours queueing | recall 1.0 (3/3 cases) |

These are results on my own synthetic corpus, not a benchmark and not a guarantee on
real traffic. The remaining 11 category misses are the honest signal of where the simple
retrieval classifier confuses near-neighbour categories.

## Run it

```bash
# tests
python3 -m pytest

# eval -> writes eval/results.json
PYTHONPATH=src python3 -m eval.harness
```

No network, no cloud account, no model download: the default LLM is an offline,
deterministic client (`src/triage/llm.py`). A real local model can implement the same
`LLMClient` protocol later without touching the pipeline.

## Layout

```
src/triage/   pipeline modules (ingest, pii, classify, llm, injection, policy, output, audit, pipeline)
eval/         synthetic corpus + harness + results.json
docs/spec/    requirements (EARS), design (Mermaid), tasks
docs/         control-mapping.md
soa.json      machine-readable control mapping
LEARNINGS.md  concepts, tools, and the "why" behind each security decision
```

## Mapping and learnings

- [`docs/control-mapping.md`](docs/control-mapping.md) — each control mapped to ISO 27001
  Annex A / ISO 42001 / NIS2 Art.21 / EU AI Act by **ID and my own-words title only**.
- [`LEARNINGS.md`](LEARNINGS.md) — the concepts, the tools, and why I made each decision.
