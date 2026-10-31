# v2 Tasks — written-channel-triage

Small, reviewable tasks, built one at a time on the `v2` branch. Each task keeps the
default path offline and dependency-free; heavy libraries are optional extras imported
lazily, and tests mock the model boundaries. A box is checked when the code is written
and its tests pass locally (stdlib + pytest, no network).

- [ ] 1. Spec docs: `docs/spec/v2-requirements.md`, `v2-design.md`, `v2-tasks.md`.
      _Covers: v2 planning._

- [ ] 2. Security — normalisation + injection hardening.
      New `src/triage/normalize.py` (NFKC, whitespace collapse, zero-width strip,
      homoglyph fold). Harden `injection.py`: normalise first, add repeat/verbatim
      pattern, decode short base64 and re-scan. Fix `pii.py` with `contains_raw_pii()`.
      Fix the phishing payment-link word boundary in `ingest.py`.
      _V18, V19, V21, V22._

- [ ] 3. Real models behind the protocol.
      `OllamaClient` in `llm.py` (constrained JSON, temp 0, timeout, fallback).
      `EmbeddingRetriever` + numpy index + optional embedding injection check in
      `src/triage/retrieval.py`. Optional `retriever` arg in `classify.py`.
      Lazy imports; unit tests mock HTTP and the encoder.
      _V1–V5, V20._

- [ ] 3b. `pyproject.toml` optional extras (`api`, `models`, `eval`) + `Makefile`
      (`test`, `eval`, `eval-real`, `data`, `datasheet`, `api`).
      _V5, V29._

- [ ] 4. Dataset generator.
      `data/generator.py`: ~1,500 seeded items, varied tone/typos/DE-EN, realistic
      headers (auth pass/fail/missing), families phishing/injection(plain, spaced,
      homoglyph, base64)/PII/out-of-hours; stratified train/dev/test; test held out.
      Writes `data/train.jsonl`, `data/dev.jsonl`, `data/test.jsonl`. Commit the files.
      _V6–V9._

- [ ] 5. Datasheet generator.
      `data/datasheet.py` reads the three JSONL files and writes `docs/datasheet.md`
      distribution tables computed from the data. Commit the generated datasheet.
      _V10._

- [ ] 6. Eval: metrics + three systems.
      `eval/metrics.py` (accuracy, per-class P/R/F1, macro-F1, confusion, latency p50/p95)
      and `eval/systems.py` (v1 regex, embeddings-only, embeddings+SLM behind one
      interface). Unit tests for metrics on toy inputs.
      _V11–V14._

- [ ] 7. Eval harness v2.
      `eval/harness_v2.py`: run systems over `data/test.jsonl`, detectors over the split,
      write `eval/results-v2.json`, confusion PNG+CSV, and generate
      `docs/error-analysis.md`. Offline subset runs System A and marks B/C
      "pending real run"; `make eval-real` runs all three.
      _V11–V17._

- [ ] 8. FastAPI delivery.
      `src/triage/api.py` (`POST /triage`, `GET /healthz`), lazy FastAPI import, test with
      the ASGI test client guarded so it skips when FastAPI is absent.
      _V28._

- [ ] 9. Docker + compose.
      `Dockerfile` (API) and `docker-compose.yml` (api + ollama).
      _V29._

- [ ] 10. Architecture doc + ADRs.
      `docs/architecture.md` (context, container/deployment, trust boundaries, data flow
      with PII, scaling, ops/observability, cost table marked pending) with LR Mermaid;
      5–6 ADRs in `docs/adr/`.
      _V23–V26._

- [ ] 11. Threat model.
      `docs/threat-model.md`: STRIDE per trust boundary → OWASP LLM Top 10 (2025) + MITRE
      ATLAS technique IDs, mitigation, and the covering test.
      _V27._

- [ ] 12. README rewrite + LEARNINGS + CI.
      README as problem → solution → results (pending) → architecture → run in 10 minutes;
      `LEARNINGS.md` v2 section; extend CI with the offline v2 harness subset.
      _V30, V31._

- [ ] 13. Open PR `v2` → `main`.
      Plain commit messages, first-person engineer voice, no tool names, no
      Co-authored-by. Numbers stay "pending real run" until the real-model outputs are
      pasted back and committed.
