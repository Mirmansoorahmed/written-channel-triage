# v2 Requirements — written-channel-triage

This is the v2 scope for the written-channel triage project. The company **NordTel GmbH**
is fictional, every piece of test text is synthetic German/English I generate in this
repo with a fixed seed, and there is no real customer data. Nothing here is a
certification and no numbers are reported unless a run in this repo produced them.

v1 shipped a safe, explainable, offline pipeline (see `docs/spec/requirements.md`). v2
turns it into something a Forward Deployed Engineer could hand a customer: real models
behind the existing protocol, a bigger seeded dataset, a three-way system comparison,
the security gaps from v1 closed, a FastAPI delivery surface, and architecture + threat
documentation.

I keep EARS form and keep the v1 IDs (R1–R27) valid. v2 adds IDs with a `V` prefix so
the two generations trace separately.

## 1. What v2 must not break

- **V0.1** The system shall keep `OfflineClient` as the default LLM and the v1 baseline,
  so the whole pipeline still runs with the Python standard library and no network.
- **V0.2** The system shall keep all v1 unit tests passing, and any new unit test shall
  run with no model download and no network (real models are mocked in tests).
- **V0.3** The system shall keep the v1 project rules: synthetic data only, no real
  brand, no copied standard text, no "certified/compliant" claims, and every reported
  number traceable to a file a run produced.

## 2. Real models behind the LLMClient protocol

- **V1** The system shall add an `OllamaClient` that implements the existing `LLMClient`
  protocol and calls a local Ollama HTTP server, with a configurable model that defaults
  to `qwen2.5:1.5b-instruct`.
- **V2** The `OllamaClient` shall request constrained JSON output of the shape
  `{category, fields, confidence}`, set temperature 0 for determinism, apply a request
  timeout, and on any error (timeout, bad JSON, connection refused) shall fall back to
  the baseline client so the pipeline never fails because a model is unavailable.
- **V3** The system shall add an `EmbeddingRetriever` that computes local multilingual
  embeddings (sentence-transformers, model `intfloat/multilingual-e5-small`) over my own
  category descriptions and few-shot examples, holds them in a small vector index
  (numpy-based, FAISS optional), and returns the top-k nearest categories for a piece of
  masked text.
- **V4** The system shall pass the retriever's top-k candidates to the SLM so the SLM
  chooses among grounded options (embeddings + SLM), and shall also expose an
  embeddings-only mode that returns the nearest category directly.
- **V5** The system's unit tests shall mock both `OllamaClient` (HTTP) and
  `EmbeddingRetriever` (vectors) so CI needs no model, and the repo shall provide a
  `make eval-real` path that uses the real models on a machine that has them.

## 3. Seeded synthetic dataset

- **V6** The system shall ship a generator script under `data/` that produces realistic
  synthetic German support emails and form texts from templates, using a fixed random
  seed so the dataset is identical for anyone who runs it.
- **V7** The generated items shall vary tone and include typos, mixed German/English, and
  realistic email headers whose `Authentication-Results` are pass, fail, or missing.
- **V8** The dataset shall include phishing, prompt-injection (including obfuscated:
  spaced-out, homoglyph, and base64-encoded), PII-heavy, and out-of-hours cases, each
  with ground-truth labels.
- **V9** The dataset shall contain roughly 2,000 items and shall be written to `data/`
  with a train/dev/test split **by template family** (a template appears in exactly one
  split); the test split shall be held out (the generator and eval shall not train or
  tune on it), and a leakage gate shall fail the build if any test item is >= 0.9 similar
  to a train or model-facing example.
- **V10** The system shall generate `docs/datasheet.md` from the data, containing the
  distribution tables (per category, per family, per split, per auth result), so the
  datasheet never contains a hand-typed count.

## 4. Three-system evaluation

- **V11** The eval shall compare three systems on the same held-out test split:
  (a) v1 regex/keyword retrieval, (b) embeddings-only nearest category, and
  (c) embeddings + SLM.
- **V12** For each system the eval shall report overall accuracy, macro-F1, and per-class
  precision/recall for the category task.
- **V13** The eval shall produce a confusion matrix per system as both a PNG and a CSV.
- **V14** The eval shall measure latency per system and report p50 and p95.
- **V15** The eval shall report detection precision and recall for phishing, prompt
  injection, and PII (no unmasked PII surviving), measured on the test split.
- **V16** The eval shall write all numbers to `eval/results-v2.json`, and shall generate
  `docs/error-analysis.md` from the actually misclassified examples of the run.
- **V17** The eval shall report only numbers a run produced; where a real-model run has
  not happened, the artifacts shall be marked "pending real run" and shall contain no
  invented values.

## 5. Security fixes (close the v1 gaps)

- **V18** The system shall normalise Unicode, collapse spacing, and fold homoglyphs
  before the injection detector runs, so obfuscated attempts (e.g. `I G N O R E`,
  Cyrillic/Greek lookalikes) are caught; the detector shall still run on the masked text.
- **V19** The system shall add patterns for "repeat/verbatim your instructions" style
  attacks and shall attempt to decode short base64 blobs and re-scan the decoded text.
- **V20** The system shall offer an optional embedding-similarity injection check that
  flags text close to known injection exemplars, usable when embeddings are available and
  degrading gracefully (no-op) when they are not.
- **V21** The phishing payment-link heuristic shall match on word boundaries so a URL
  path like `/payload` no longer matches the `pay` cue (fixes the v1 false positive).
- **V22** After the SLM returns, the system shall re-check that the SLM output contains no
  unmasked PII, and shall drop/flag the output if it does.

## 6. Architecture documentation

- **V23** The system shall provide `docs/architecture.md` with a context view, a
  container/deployment view (FastAPI service, an out-of-hours queue, an Ollama container,
  the vector index, and the audit store), explicit trust boundaries, a data-flow view
  that marks where PII exists, scaling notes, and ops/observability (structured log
  shape and metric names).
- **V24** The architecture doc shall include a cost table derived from measured CPU
  latency (marked "pending real run" until a run produces the latency numbers).
- **V25** The system shall provide 5–6 ADRs under `docs/adr/`, each stating context,
  decision, and consequences.
- **V26** The architecture diagrams shall be simple left-to-right Mermaid with few boxes,
  readable as a draw.io-style sketch.

## 7. Threat model

- **V27** The system shall provide `docs/threat-model.md` applying STRIDE per trust
  boundary, each threat mapped to the relevant OWASP LLM Top 10 (2025) item and a MITRE
  ATLAS technique ID, with the mitigation and the specific test that covers it.

## 8. Delivery

- **V28** The system shall expose a FastAPI endpoint `POST /triage` that accepts a written
  message and returns the triage result as JSON (reusing the existing pipeline).
- **V29** The system shall provide a `Dockerfile` and a `docker-compose` that brings up
  the API together with an Ollama service.
- **V30** The README shall be rewritten as problem → solution → results table →
  architecture → "run it in 10 minutes", with results marked "pending real run" until a
  run fills them in.
- **V31** `LEARNINGS.md` shall be updated with the v2 decisions and the honest limits of
  the v2 work.

## 9. Non-functional (carried from v1, reaffirmed)

- **N1** Offline and free by default: the default path and CI need no cloud, no paid API,
  no model download.
- **N2** Explainability: every verdict keeps a human-readable reason string.
- **N3** Determinism: the default offline path and the real SLM at temperature 0 are
  reproducible; the dataset is seeded.
- **N4** Privacy: synthetic values only, in obviously fake ranges.
