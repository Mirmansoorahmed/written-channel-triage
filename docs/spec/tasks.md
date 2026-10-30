# Tasks — written-channel-triage

Small, reviewable tasks. One module (plus its tests) per task. I check the box when the
module is written and its tests pass.

- [x] 1. Scaffold: package layout, `pyproject.toml`, data models in `src/triage/models.py`.
      _Covers: project setup._

- [x] 2. Ingest + sender trust (`ingest.py`).
      Parse `.eml` and form text; read SPF/DKIM/DMARC from `Authentication-Results`;
      phishing rules (fake invoice, lookalike domain, urgent payment link); explainable.
      _R1–R5._

- [x] 3. PII masking (`pii.py`).
      Reversible masking for name, IBAN, phone, email, address, customer number;
      in-memory token map; restore; never leak to log.
      _R6–R9._

- [x] 4. Categories + classify + LLM (`categories.py`, `llm.py`, `classify.py`).
      ~10 own categories with required fields; local retrieval; pluggable LLM with an
      offline deterministic default and a mock; confidence; field extraction.
      _R10–R13._

- [x] 5. Prompt-injection detector (`injection.py`).
      Run on masked text; record matched pattern; block tool use on hit.
      _R14–R16._

- [x] 6. Policy gate (`policy.py`).
      Account-changing actions -> pending approval, never executed; read-only allowed.
      _R17–R19._

- [x] 7. Output + hours + audit (`output.py`, `audit.py`).
      AI-disclosure line (AI Act Art. 50); handoff summary; out-of-hours queue with ETA;
      hash-chained JSONL audit log.
      _R20–R23._

- [x] 8. Pipeline orchestration (`pipeline.py`).
      Wire steps end to end; return a `TriageResult`.
      _All runtime R's._

- [x] 9. Synthetic corpus (`eval/corpus.py`).
      ~100 synthetic German messages: normal, phishing, injection, PII-heavy, out-of-hours.
      _R24._

- [x] 10. Eval harness (`eval/harness.py`).
      Run the pipeline over the corpus; measure precision/recall per check and category
      accuracy; write `eval/results.json` with only numbers the run produces.
      _R25._

- [x] 11. Control mapping (`docs/control-mapping.md`, `soa.json`).
      Map each control to ISO 27001 Annex A / ISO 42001 / NIS2 Art. 21 / AI Act by ID and
      my own-words title only.
      _R26._

- [x] 12. README, GitHub Actions (pytest + eval), `LEARNINGS.md`.
      3-minute skim, left-to-right diagram, interview-ready "why" notes.
      _R27._
