# Secure Written-Channel Triage: a safe front door for customer emails and web forms

**Problem:** Support messages carry personal data, phishing and prompt-injection text. If they go straight to an AI model or an agent, data leaks and an attacker can trigger account changes.
**What it does:** Every message goes through fixed, explainable steps *before* any model or human sees it: sender check (SPF/DKIM/DMARC) and phishing flags, PII masking, German intent classification, prompt-injection detection on the masked text, and a policy gate. Account changes are never auto-run; they wait for a human. Every step is written to a hash-chained audit log. Fictional German telco, synthetic data.

**Run it in 3 steps** (Python 3.10+, no network, no model download):
```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
PYTHONPATH=src python3 -m eval.harness
```

**What you'll see:** on 199 synthetic German messages: PII masking 27/27 with no raw leak, phishing recall 1.0 (precision 0.963), injection precision 1.0 / recall 0.9259 (2 obfuscated misses, reported), category accuracy 0.8894.

**Read more:** [Design (spec)](docs/spec/design.md) · [Requirements](docs/spec/requirements.md) · [Control mapping (ISO 27001 / ISO 42001 / NIS2 / EU AI Act)](docs/control-mapping.md) · [Learnings and the "why" of each decision](LEARNINGS.md) · [How I built this](#how-i-built-this)

---

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
synthetic corpus of **199** German messages. I only report numbers the run produces.

| Check | Result |
|---|---|
| Category accuracy | 0.8894 (177/199) |
| Phishing detection | precision 0.963, recall 1.0 (tp 26, fp 1, fn 0) |
| Prompt-injection detection | precision 1.0, recall 0.9259 (tp 25, fp 0, fn 2) |
| PII masking (no raw leak) | recall 1.0 (27/27 PII-heavy cases) |
| Out-of-hours queueing | recall 1.0 (14/14 cases) |

These are results on my own synthetic corpus, not a benchmark and not a guarantee on
real traffic. The larger corpus deliberately includes hard cases, and it exposed real
gaps I am reporting as-is:
- The injection detector misses **2** obfuscated attempts: a spaced-out `I G N O R E …`
  and a "repeat … then ignore them" phrasing my patterns do not cover (recall 0.9259).
- Phishing shows **1** false positive: a malicious `wget http://…/payload` line counted
  as a payment link via the `pay` substring. It is genuinely malicious, just the wrong
  label, which is why precision is 0.963.
- The 22 category misses are the honest signal of where the simple retrieval classifier
  confuses near-neighbour categories (e.g. Vertrag vs. Tarifwechsel).

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

## How I built this

What I owned:
- **The problem and the rules:** mask before the model, check for injection on the masked text, never run an account change without a human, never silently close a request out of hours, and keep a tamper-evident log with no raw PII. These rules are in [LEARNINGS.md](LEARNINGS.md), with the reason for each one.
- **Threats and controls:** the mapping to ISO 27001, ISO 42001, NIS2 and the EU AI Act in [docs/control-mapping.md](docs/control-mapping.md).
- **Test cases:** the hard cases in the synthetic corpus (phishing, injection, PII-heavy, out of hours) and what counts as a pass.
- **Review and runs:** I ran the tests and the eval myself and only report numbers the run produced.

### What didn't work, and what I changed
1. **A small test set looked perfect and hid real gaps.** When I grew the corpus to 199 messages with hard cases, injection recall dropped to 0.9259. The regex missed a spaced-out `I G N O R E ...` and a "repeat the above instructions, then ignore them" phrasing. I report the misses as they are. On the `v2` branch the text is normalised before the injection check (ADR 0003). *(README "Measured results"; LEARNINGS.md; v2 commit 2e8a4a4)*
2. **A phishing false positive.** A malicious `wget http://.../payload` line was labelled as a payment link because of the `pay` substring (precision 0.963). On `v2` I fixed the boundary and rewrote the phishing detector to use generic signals instead of the generator's own domains. *(README; LEARNINGS.md; v2 commits 2e8a4a4, f5d19f3)*
3. **Train/test leakage in the first v2 dataset.** Test messages came from the same templates as training messages, so scores were too optimistic. I split by template family and added a leakage gate that fails the build if any test or unseen item is 0.9 or more similar to training text. *(v2 commit 4ef45b9 "Fix train/test leakage, PII masking, and System C honesty"; v2 README; ADR 0004)*
