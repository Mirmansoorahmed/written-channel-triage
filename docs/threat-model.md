# Threat model — written-channel-triage (v2)

STRIDE applied per trust boundary, with each threat mapped to the relevant item of the
[OWASP Top 10 for LLM Applications (2025)](https://genai.owasp.org/llm-top-10/) and a
[MITRE ATLAS](https://atlas.mitre.org/) technique ID, the mitigation in this repo, and the
specific test that covers it. Framework names are referenced by ID; the descriptions are my
own words. Synthetic data only; this is a portfolio threat model, not a certification.

## Boundaries (from `docs/architecture.md` §3)

- **B1 Untrusted → service.** The raw message is attacker-controlled.
- **B2 Service → model.** Masked text crosses into the SLM and the vector index.
- **B3 Service → human / log.** Handoff summary and the audit log.

## OWASP LLM Top 10 (2025) IDs referenced

LLM01 Prompt Injection · LLM02 Sensitive Information Disclosure · LLM05 Improper Output
Handling · LLM06 Excessive Agency · LLM07 System Prompt Leakage · LLM08 Vector and
Embedding Weaknesses · LLM10 Unbounded Consumption.

## MITRE ATLAS technique IDs referenced

AML.T0051 LLM Prompt Injection · AML.T0054 LLM Jailbreak · AML.T0057 LLM Data Leakage ·
AML.T0061 LLM Prompt Self-Replication.

---

## B1 — Untrusted → service

| STRIDE | Threat | OWASP | ATLAS | Mitigation | Covering test |
|---|---|---|---|---|---|
| **S**poofing | Attacker forges a trusted sender to look legitimate | LLM01 | AML.T0051 | SPF/DKIM/DMARC read from `Authentication-Results`; missing header → "unknown", never "pass" | `tests/test_ingest.py::test_trust_pass`, `::test_trust_unknown_without_headers` |
| **S**poofing | Lookalike-domain / credential phishing impersonating NordTel | LLM01 | AML.T0051 | Generic, corpus-agnostic scoring: auth fail/missing, a lookalike of NordTel's OWN domains (punycode decode + homoglyph fold + edit distance ≤ 2), link text/href mismatch, urgency + payment; own-portal link under pass auth is not flagged | `tests/test_ingest.py::test_phishing_lookalike_and_urgency_flagged`, `::test_punycode_lookalike_flagged`, `::test_link_text_href_mismatch_flagged`, `::test_benign_own_portal_with_pass_not_flagged` |
| **T**ampering | Obfuscated prompt injection (spaced, homoglyph, base64) hidden in the message | LLM01 | AML.T0051, AML.T0054 | Normalise (NFKC, strip invisibles, fold homoglyphs, de-space) then match; decode short base64 and re-scan | `tests/test_injection.py::test_detects_spaced_out_ignore`, `::test_detects_homoglyph_ignore`, `::test_detects_base64_wrapped_payload`; `tests/test_normalize.py` |
| **T**ampering | "Repeat your instructions then ignore them" style attack | LLM01, LLM07 | AML.T0061 | Dedicated repeat/verbatim pattern | `tests/test_injection.py::test_detects_repeat_then_ignore` |
| **D**oS | Oversized or pathological input to exhaust the pipeline / model | LLM10 | AML.T0051 | base64 decode is length/printable-gated; the SLM call has a timeout and falls back; metric `triage_request_latency_ms` watched | `tests/test_llm_ollama.py::test_ollama_falls_back_on_connection_error` (timeout path); base64 gate in `tests/test_injection.py::test_benign_base64_not_flagged` |

## B2 — Service → model

| STRIDE | Threat | OWASP | ATLAS | Mitigation | Covering test |
|---|---|---|---|---|---|
| **I**nfo disclosure | Raw PII reaches the model prompt | LLM02 | AML.T0057 | Mask **before** any model call; only masked text and placeholders cross B2 | `tests/test_pii.py::test_mask_covers_all_types`; `tests/test_api.py::test_triage_masks_pii` |
| **I**nfo disclosure | Model echoes an unmasked PII value back into fields | LLM02, LLM05 | AML.T0057 | Post-SLM re-check drops any field value containing raw PII and flags it | `tests/test_pii.py::test_contains_raw_pii_detects_iban`, `::test_placeholders_are_not_raw_pii` |
| **T**ampering | Injection text steers the classifier/model | LLM01 | AML.T0051 | Detector runs on the **same masked text** the model sees, just before B2. Verdict = normalised rules **OR** a trained injection-LR probability ≥ a dev-chosen threshold (stored in `models/manifest.json`); no fixed embedding cut-off | `tests/test_injection.py::test_lr_flags_above_threshold_when_rules_miss`, `::test_lr_below_threshold_not_flagged`, `::test_rules_still_fire_even_if_lr_low` |
| **T**ampering | Poisoned/adversarial text near a category exemplar skews retrieval | LLM08 | AML.T0051 | Index is built only from my own in-repo descriptions + few-shot examples (no user-supplied passages); candidates are scored, not trusted blindly | `tests/test_retrieval.py::test_build_indexes_all_categories`, `::test_nearest_category_matches_identical_passage` |
| **E**levation of privilege | Model output used to auto-run an account change | LLM06 | AML.T0054 | Policy gate never executes account-changing actions; they become a pending approval; injection → no tool use at all | `tests/test_policy.py` (suite); `tests/test_api.py::test_triage_flags_injection` |
| **R**epudiation | Can't tell whether the model or the baseline produced an answer | LLM05 | — | `OllamaClient.last_fallback` records any fallback; reason strings carry the decision | `tests/test_llm_ollama.py::test_ollama_falls_back_on_malformed_json`, `::test_ollama_rejects_out_of_set_category` |

## B3 — Service → human / log

| STRIDE | Threat | OWASP | ATLAS | Mitigation | Covering test |
|---|---|---|---|---|---|
| **I**nfo disclosure | Raw PII written to the audit log | LLM02 | AML.T0057 | Audit `assert_no_pii` guard refuses raw IBAN/email; only verdicts/flags/masked text are logged | `tests/test_audit.py::test_refuses_raw_iban`, `::test_refuses_raw_email`; `tests/test_pii.py::test_token_map_in_memory_only` |
| **T**ampering | Someone edits or deletes a log line to hide an action | — | — | Hash-chained JSONL: each line stores the SHA-256 of the previous; a break is detectable | `tests/test_audit.py::test_tamper_breaks_chain` |
| **S**poofing | System-prompt / instruction leakage to the human output | LLM07 | AML.T0061 | Reveal/repeat-instructions patterns flag the attempt before output; injection → human review | `tests/test_injection.py::test_detects_reveal_instructions`, `::test_detects_repeat_then_ignore` |

---

## Residual risks (stated honestly)

- Detection is rules + a small trained model: a sufficiently novel injection phrasing can
  still slip past both. The rules-only recall on the **unseen** set is low (reported in
  `eval/results-v2.json` → `detectors.unseen`); the trained injection-LR is meant to lift
  that on the real run, and the gap is reported rather than hidden.
- The numbers that back these mitigations are measured on **synthetic** data; they describe
  behaviour on those cases, not real traffic.
- Model availability is a dependency; the fallback keeps the service *safe* (baseline
  behaviour) but *degrades quality* when Ollama is down — tracked via
  `triage_slm_fallback_total`, and the eval fails if System C's fallback rate exceeds 2%.

---

### Note on the cited tests

Every test named above is a real test that passes. Most run with the standard-library
`make test`. The ones that exercise the FastAPI surface (`tests/test_api.py::*`), the
embedding index (`tests/test_retrieval.py::*`) and the trained classifier
(`tests/test_learned.py::*`) run under the optional extras and are exercised in CI, which
installs them; without those extras they are skipped (never failing), so no cited test is
red.
