# v2 Tasks — written-channel-triage

Small, reviewable tasks, built one at a time on the `v2` branch. Each task keeps the
default path offline and dependency-free; heavy libraries are optional extras imported
lazily, and tests mock the model boundaries. A box is checked when the code is written
and its tests pass locally (stdlib + pytest, no network).

- [x] 1. Spec docs: `docs/spec/v2-requirements.md`, `v2-design.md`, `v2-tasks.md`.
      _Covers: v2 planning._

- [x] 2. Security — normalisation + injection hardening.
      New `src/triage/normalize.py` (NFKC, whitespace collapse, zero-width strip,
      homoglyph fold). Harden `injection.py`: normalise first, add repeat/verbatim
      pattern, decode short base64 and re-scan. Fix `pii.py` with `contains_raw_pii()`.
      Fix the phishing payment-link word boundary in `ingest.py`.
      _V18, V19, V21, V22._

- [x] 3. Real models behind the protocol.
      `OllamaClient` in `llm.py` (constrained JSON, temp 0, timeout, fallback).
      `EmbeddingRetriever` + numpy index + optional embedding injection check in
      `src/triage/retrieval.py`. Optional `retriever` arg in `classify.py`.
      Lazy imports; unit tests mock HTTP and the encoder.
      _V1–V5, V20._

- [x] 3b. `pyproject.toml` optional extras (`api`, `models`, `eval`) + `Makefile`
      (`test`, `eval`, `eval-real`, `data`, `datasheet`, `api`).
      _V5, V29._

- [x] 4. Dataset generator.
      `data/generator.py`: ~2,050 seeded items, varied tone/typos/DE-EN, realistic
      headers (auth pass/fail/missing), families phishing/injection(plain, spaced,
      homoglyph, base64)/PII/out-of-hours; stratified train/dev/test; test held out.
      Writes `data/train.jsonl`, `data/dev.jsonl`, `data/test.jsonl`. Commit the files.
      _V6–V9._

- [x] 5. Datasheet generator.
      `data/datasheet.py` reads the three JSONL files and writes `docs/datasheet.md`
      distribution tables computed from the data. Commit the generated datasheet.
      _V10._

- [x] 6. Eval: metrics + three systems.
      `eval/metrics.py` (accuracy, per-class P/R/F1, macro-F1, confusion, latency p50/p95)
      and `eval/systems.py` (v1 regex, embeddings-only, embeddings+SLM behind one
      interface). Unit tests for metrics on toy inputs.
      _V11–V14._

- [x] 7. Eval harness v2.
      `eval/harness_v2.py`: run systems over `data/test.jsonl`, detectors over the split,
      write `eval/results-v2.json`, confusion PNG+CSV, and generate
      `docs/error-analysis.md`. Offline subset runs System A and marks B/C
      "pending real run"; `make eval-real` runs all three.
      _V11–V17._

- [x] 8. FastAPI delivery.
      `src/triage/api.py` (`POST /triage`, `GET /healthz`), lazy FastAPI import, test with
      the ASGI test client guarded so it skips when FastAPI is absent.
      _V28._

- [x] 9. Docker + compose.
      `Dockerfile` (API) and `docker-compose.yml` (api + ollama).
      _V29._

- [x] 10. Architecture doc + ADRs.
      `docs/architecture.md` (context, container/deployment, trust boundaries, data flow
      with PII, scaling, ops/observability, cost table marked pending) with LR Mermaid;
      5–6 ADRs in `docs/adr/`.
      _V23–V26._

- [x] 11. Threat model.
      `docs/threat-model.md`: STRIDE per trust boundary → OWASP LLM Top 10 (2025) + MITRE
      ATLAS technique IDs, mitigation, and the covering test.
      _V27._

- [x] 12. README rewrite + LEARNINGS + CI.
      README as problem → solution → results (pending) → architecture → run in 10 minutes;
      `LEARNINGS.md` v2 section; extend CI with the offline v2 harness subset.
      _V30, V31._

- [x] 13. Open PR `v2` → `main`.
      Plain commit messages, first-person engineer voice, no tool names, no
      Co-authored-by. Numbers stay "pending real run" until the real-model outputs are
      pasted back and committed.

---

## Round 3 — credibility fixes

A review of the first real run exposed places where the eval and detectors still
flattered themselves. These tasks fix that; numbers stay "pending real run" until
`TRIAGE_EVAL_REAL=1 ... eval.harness_v2` is run with the models.

- [x] R3.1 Trained classifier. `src/triage/learned.py` (calibrated LR on e5 for
      category + a binary injection head), `eval/train_models.py` (`make train`,
      fits on train only, injection threshold chosen on dev, writes
      `models/*.joblib` + `manifest.json`), SystemD/E in `eval/systems.py`,
      scikit-learn/joblib extras, tests with a fake embedder.

- [x] R3.2 Phishing without generator knowledge. Delete the generator-domain
      lookalike regex; score generic signals (auth, own-domain lookalike via
      punycode+homoglyph+edit-distance, link text/href mismatch, urgency+payment)
      against a documented threshold. Test that no generator domain appears in src/.

- [x] R3.3 Injection. Remove the fixed 0.80 embedding threshold; verdict = rules OR
      injection-LR prob ≥ dev threshold (stored in manifest). Threat model cites only
      this mechanism and passing tests.

- [x] R3.4 Unseen set ≥ 200 hand-written items (≥30 injection incl. indirect /
      encoded / headers, ≥30 phishing, ≥30 benign-with-links), no generator overlap;
      `overlap_check` also compares unseen against train and generator templates.

- [x] R3.5 Calibration. ECE + reliability (table + PNG) for C and D; D calibrated on
      dev; C not routed on confidence; review threshold documented in ADR 0007.

- [x] R3.6 Harness. Score each split once (dev/test/unseen, no seen_template); build
      overall_test from the test report; count slm_diagnostics once per split; fail
      if C's fallback rate > 2%; category metric only on category-bearing families.

- [x] R3.7 PII masker. Typo-tolerant labels/IBAN/street/email/name; generator records
      pre- and post-typo truth; `eval/pii_leak_check.py` fuzzy-checks all test+unseen
      items; target 0 leaks, real count in results-v2.json.

- [x] R3.8 Cost + metrics. Per-system CPU seconds/item, peak RSS, latency p50/p95;
      `docs/generate_tables.py` cost-per-1k from CPU + a labelled VM price assumption;
      `GET /metrics` serves Prometheus text.

- [x] R3.9 Cleanup. Drop the paste-back paragraph; configurable harness output dir so
      tests use tmp_path; generated PNG/CSV git-ignored; `make docs` emits D/E, cost
      and calibration rows; error-analysis / datasheet / LEARNINGS updated; all tables
      say "pending real run" in the committed state.

---

## Round 4 — fixes from the second real run

A real run showed E was the best system but surfaced concrete defects: the injection
LR was never actually used, C's cost was ~16x too low (Ollama CPU not counted), tests
broke on scikit-learn 1.9, no review threshold was chosen in code, 4 test items still
leaked PII, and auth alone separated unseen phishing from benign. These tasks fix that;
every metric/cost/threshold table (and ADR 0007) stays "pending real run" until a local
`TRIAGE_EVAL_REAL=1 ... eval.harness_v2`.

- [x] R4.1 Wire the injection model. `learned.load_injection_detector` reads
      `injection_lr.joblib` + the dev threshold from the manifest (None when absent);
      the API and the harness detector use rules OR LR>=threshold and report injection
      P/R/FPR twice (rules-only and combined). A stub-model test shows the API and
      harness flag an item only the model catches.

- [x] R4.2 Cost and RAM. `eval/procstat.py` reads Ollama CPU (utime+stime) and RSS from
      /proc; cost per 1k = harness CPU-s + Ollama CPU-s; harness RSS ("process peak") and
      Ollama RSS reported separately. The VM price label states instance, region
      (us-east-1), date and source as an assumption. A fake-/proc test shows Ollama CPU
      in the cost.

- [x] R4.3 scikit-learn. Dropped `multi_class="auto"`; pinned `scikit-learn>=1.3,<2` in
      the eval and learned extras; tests pass on 1.7 and >= 1.8.

- [x] R4.4 Thresholds on dev, in code. The harness chooses the human-review threshold
      (method + expected review rate) and E's routing threshold from D's dev
      probabilities, stores both in results-v2.json, and `make docs` fills ADR 0007 and
      architecture S8. E has a 2% fallback gate. D is calibrated on dev via `cv='prefit'`
      so "calibrated on dev" is true.

- [x] R4.5 PII leak check. Runs on ALL `pii_truth` items (not only has_pii); the
      partial ratio is a real edit-distance match (insert/delete/swap); the generator
      records post-typo truth plus the pre-typo value; the masker handles a typo'd street
      before an [[ADDRESS]] token and signature names in non-PII items. Review examples
      added; 0 leaks reported.

- [x] R4.6 Unseen phishing without the auth shortcut. Added auth=PASS phishing
      (authenticated lookalike / combo-squat / brand-like domains) and auth=FAIL/missing
      benign mail (forwards, mailing lists, a customer writing "Mahnung ... sofort
      zahlen"), hand-written. A combo-squat signal fires when an own brand label appears
      in a foreign registrable domain; unseen phishing P/R is reported split by auth.

- [x] R4.7 Small items. README no longer implies links to git-ignored charts; D and the
      injection LR train on `pii.mask(text)` (no train/serve skew); error-analysis states
      C's unseen weakness, constant confidence and Sonstiges over-prediction.
