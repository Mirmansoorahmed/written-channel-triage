# written-channel-triage

One safe entry point for written customer support (email + web-form text) at the
**fictional** NordTel GmbH. It triages a message — checks the sender, masks personal
data, classifies the request, looks for prompt injection, and gates risky actions —
**before** anything reaches an LLM or a human.

Personal portfolio project. All data is synthetic German/English generated in this repo
with a fixed seed. No real brand, no real customer data, and **nothing here is a
certification**.

> **v2** adds a real local SLM and multilingual embedding retrieval behind the v1
> protocol, a seeded ~1,670-item dataset with a held-out test split, a three-system
> evaluation, hardened security, and a FastAPI + Docker delivery surface. The v1 baseline
> (offline, deterministic) still runs with the Python standard library alone.

## Problem

Many German telcos dropped a general support email address and spread written requests
across many web forms; chat handoff is slow and has no upload. There is no single written
front door that is safe by default: one that won't leak personal data into a model, won't
be steered by a prompt-injection string, and won't let an attacker trigger an account
change. I wanted to build that front door and be able to defend every decision in a
review.

## Solution

A fixed, explainable pipeline. Each step is a small module with its own tests and a reason
string, so one decision can be reviewed at a time.

```mermaid
flowchart LR
    A[raw .eml / form text] --> B[1 ingest + sender trust<br/>SPF/DKIM/DMARC, phishing]
    B --> C[2 mask PII<br/>reversible, in-memory]
    C --> D[3 classify<br/>regex or embeddings + SLM]
    C --> E[4 injection detector<br/>normalised masked text]
    D --> F[5 policy gate<br/>account change -> pending]
    E --> F
    F --> G[6 output<br/>disclosure, handoff, OOH queue]
    G --> H[(audit JSONL<br/>hash chain)]
```

**Safe by default:** mask before the model · injection detector on the masked text ·
no auto account changes (pending approval) · never silently close out of hours ·
tamper-evident audit log. v2 closes the two gaps the v1 eval exposed (obfuscated
injection, a phishing false positive) and adds a post-model PII re-check.

## Results

Numbers come only from a run. The eval compares three systems on the **held-out test
split** (`data/test.jsonl`): **A** v1 regex/keyword, **B** embeddings-only, **C**
embeddings + SLM. The full file is [`eval/results-v2.json`](eval/results-v2.json).

| system | category accuracy | macro-F1 | latency p50 / p95 |
|---|---|---|---|
| A — v1 regex/keyword | see `results-v2.json` (offline run) | see `results-v2.json` | see `results-v2.json` |
| B — embeddings-only | **pending real run** | pending real run | pending real run |
| C — embeddings + SLM | **pending real run** | pending real run | pending real run |

Detectors over the test split (measured on the offline run):

| detector | result |
|---|---|
| phishing | see `results-v2.json` |
| prompt injection (incl. spaced / homoglyph / base64) | see `results-v2.json` |
| PII masking (no raw leak) | see `results-v2.json` |

System B and C need the real models, so their rows stay **pending real run** until a
machine with Ollama + the embeddings model produces them — this repo never invents a
number. The confusion matrix (PNG + CSV) and [`docs/error-analysis.md`](docs/error-analysis.md)
are generated from the same run; the dataset distributions are in
[`docs/datasheet.md`](docs/datasheet.md).

## Architecture

- [`docs/architecture.md`](docs/architecture.md) — context, container/deployment, trust
  boundaries, data flow with PII, scaling, ops/observability, cost table.
- [`docs/adr/`](docs/adr/) — 6 ADRs behind the v2 decisions.
- [`docs/threat-model.md`](docs/threat-model.md) — STRIDE per boundary → OWASP LLM Top 10
  (2025) + MITRE ATLAS, mitigation and covering test.
- [`docs/spec/`](docs/spec/) — v1 and v2 requirements (EARS), design, tasks.

## Run it in 10 minutes

**Offline, no model (default — stdlib + pytest):**

```bash
make test                 # unit tests (models + API paths skip if extras absent)
make data                 # regenerate the seeded dataset into data/*.jsonl
make datasheet            # regenerate docs/datasheet.md from the data
make eval                 # offline eval: System A measured, B/C pending real run
```

**With the real models (your machine):**

```bash
# 1. Install extras
pip install -e ".[models,eval,api]"
# 2. Start Ollama and pull the default model
ollama serve &
ollama pull qwen2.5:1.5b-instruct
# 3. Run all three systems; writes results-v2.json, confusion PNG/CSV, error analysis
make eval-real
```

**As a service (Docker):**

```bash
docker compose up --build
docker compose exec ollama ollama pull qwen2.5:1.5b-instruct
curl -s localhost:8000/triage -H 'content-type: application/json' \
     -d '{"text":"Mein Internet ist tot, Störung.","source":"form"}'
```

When `make eval-real` finishes, paste the contents of `eval/results-v2.json` (and the
generated PNG/CSV) back and they get committed — the pending rows above are filled from
that file, nothing is typed by hand.

## Layout

```
src/triage/   pipeline modules + normalize.py, retrieval.py, api.py (v2), OllamaClient
data/         seeded generator + train/dev/test.jsonl + datasheet generator
eval/         v1 harness + v2 harness (three systems), metrics, results-v2.json
docs/         architecture, threat-model, datasheet, error-analysis, adr/, spec/
Dockerfile, docker-compose.yml, Makefile
LEARNINGS.md  the concepts, tools, and the "why" behind each decision
```

## Learnings and limits

[`LEARNINGS.md`](LEARNINGS.md) has the concepts and the "why" for every decision, v1 and
v2, including the honest limits: the scores are on synthetic data, they are not a
benchmark, and they say nothing about real traffic.
