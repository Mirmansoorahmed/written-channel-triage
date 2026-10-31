# Requirements — written-channel-triage

This is a personal portfolio project. The company "NordTel GmbH" is fictional and
there is no real customer data anywhere. All test text is synthetic German I generate
in this repo. Nothing here is a certification.

I write requirements in EARS form (Easy Approach to Requirements Syntax). Each one has
an ID so I can trace it to design, code, tests, and the control mapping.

## 1. Problem and scope

Many German telcos dropped a general support email address and spread written requests
across many web forms. Chat handoff is slow and has no upload. I want one written entry
point that triages a message safely *before* anything reaches an LLM or a human.

In scope: parsing a written message (`.eml` or raw form text), deciding how much to trust
the sender, masking personal data, classifying the request, detecting prompt injection,
gating risky actions, and producing an explainable handoff plus an audit record.

Out of scope: actually sending replies, connecting to a real mailbox, any real brand,
any network calls to third parties.

## 2. Glossary

- **Request** — one incoming written message (email or form text).
- **Verdict** — a short, explainable decision with a reason string.
- **Token map** — the in-memory map from a masking placeholder back to the original value.
- **Pending approval** — a risky action parked for a human; never auto-executed.

## 3. Functional requirements (EARS)

### Ingest and sender trust

- **R1** When the system receives an `.eml` file, the system shall parse the subject,
  sender, body text, and the `Authentication-Results` header.
- **R2** When the system receives raw form text, the system shall accept it without
  requiring email headers and shall mark sender-trust as "unknown (no headers)".
- **R3** When `Authentication-Results` is present, the system shall read the SPF, DKIM,
  and DMARC results and produce a sender-trust verdict of pass, partial, or fail with a
  reason string.
- **R4** While scanning a request, when the text matches a known phishing pattern
  (fake invoice, lookalike domain, urgent payment link), the system shall flag the
  request as suspected phishing and record which rule matched.
- **R5** The system shall make every ingest and phishing decision rule-based and
  explainable; the system shall not use an LLM for the trust verdict.

### PII masking

- **R6** Before any LLM call, the system shall mask personal data in the text: name,
  IBAN, phone, email, postal address, and customer number.
- **R7** When the system masks a value, the system shall replace it with a typed
  placeholder (for example `[[IBAN_1]]`) and shall keep the reverse mapping only in
  memory for the lifetime of the request.
- **R8** The system shall be able to restore the original text from the masked text and
  the token map (reversible masking).
- **R9** The system shall never write an unmasked PII value into the audit log.

### Classification and field extraction

- **R10** When the system classifies a request, the system shall choose one of my own
  defined categories: Rechnung, Vertrag, Umzug, Störung, Kündigung, Datenschutz,
  Tarifwechsel, Technik-Setup, Beschwerde, Sonstiges.
- **R11** The system shall classify using a small local retrieval step over my own
  category descriptions; the LLM component shall be pluggable and shall default to an
  offline deterministic implementation so tests and CI need no network or model download.
- **R12** When a category is chosen, the system shall extract the fields that category
  requires and shall mark any missing required field as "missing".
- **R13** The system shall return a classification confidence derived from the retrieval
  score so a low-confidence result can be routed to a human.

### Prompt-injection detection

- **R14** The system shall run a prompt-injection detector on the *masked* text.
- **R15** While a request is flagged for prompt injection, the system shall not perform
  any tool use for that request.
- **R16** When injection is detected, the system shall record which pattern matched so
  the decision is explainable.

### Policy gate

- **R17** The system shall treat tariff change, cancellation, address change, and SEPA
  mandate change as account-changing actions.
- **R18** When a request asks for an account-changing action, the system shall never
  execute it and shall instead create a pending approval for a human.
- **R19** The system shall allow read-only answers (status, information) to proceed
  without a pending approval.

### Output, transparency, hours, audit

- **R20** The system shall add an AI-disclosure line to any machine-generated output,
  covering EU AI Act Article 50 transparency.
- **R21** The system shall produce a handoff summary for the human agent containing the
  category, extracted fields, trust verdict, and any flags.
- **R22** When the local time is outside 07:00–23:00, the system shall queue the request
  with an ETA for the next opening and shall never silently close it.
- **R23** The system shall append every decision to a JSONL audit log, and each line
  shall include the hash of the previous line so the log forms a tamper-evident chain.

### Evaluation

- **R24** The system shall ship a synthetic German corpus of about 100 messages covering
  normal, phishing, injection, PII-heavy, and out-of-hours cases, all generated in this repo.
- **R25** When the eval harness runs, the system shall write measured precision and recall
  per check and category accuracy into `eval/results.json`, and the system shall report
  only numbers that run produces.

### Documentation and traceability

- **R26** The system shall provide `docs/control-mapping.md` that maps each control to
  ISO 27001 Annex A, ISO 42001, NIS2 Article 21, and the EU AI Act by ID and my own-words
  title only, with a machine-readable `soa.json`.
- **R27** The repo shall run pytest and the eval in GitHub Actions on push.

## 4. Non-functional requirements

- **N1** Offline and free: no cloud accounts, no paid APIs, no real attacks. The default
  path runs with the Python standard library only.
- **N2** Explainability: every verdict carries a human-readable reason string.
- **N3** Determinism: with the default offline LLM, the same input gives the same output,
  so tests are stable.
- **N4** Privacy: no real personal data; synthetic values use obviously fake ranges.
