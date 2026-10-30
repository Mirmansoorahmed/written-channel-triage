# Learnings

Notes to myself, written so I can talk through them in an interview. First person,
plain English. Fictional telco, synthetic data, not a certification.

## What I built and why

I built one written entry point that triages a message before it reaches an LLM or a
human. The driver was a real annoyance: German telcos keep removing a general support
email and pushing people into dozens of web forms, and chat handoff is slow with no
upload. I wanted a single safe front door.

The design rule I kept coming back to: **do the dangerous-but-cheap checks first, in
code I can explain line by line, and only then let a model near the text.**

## Concepts I had to get right

### Email authentication (SPF, DKIM, DMARC)
These live in the `Authentication-Results` header. SPF says the sending server was
allowed for the domain; DKIM is a signature over the message; DMARC ties them to the
visible From domain and says what to do on failure. For trust I treat all-pass as pass,
two-or-more fails (or a DMARC fail) as fail, and anything in between as partial. No
header at all is "unknown", never "pass" — absence of evidence is not trust.

### Prompt injection
An attacker writes text that tries to override the system's instructions ("ignore all
previous instructions", "du bist jetzt…"). The key decision was **where** to run the
detector: on the *masked* text, because that is exactly what the model would see. If I
checked the raw text I would be testing the wrong string.

### PII masking that is reversible
I mask name, IBAN, phone, email, address and customer number into typed placeholders
(`[[IBAN_1]]`) and keep the reverse map **in memory only**. Reversible means I can
restore the original for the human if needed, but a leaked log or model prompt never
contains the real value. Order matters: mask the structured things (IBAN, email) before
the loose ones (phone) so I don't mis-split a value.

### Human-in-the-loop on risky actions
Tariff change, cancellation, address change and SEPA change can hurt a customer if done
wrongly — or by an attacker who slipped past earlier checks. So those are **never**
executed; they become a pending approval. Read-only answers can go ahead. This is the
single most important safety property, and it is a plain `if` in `policy.py`, not a model
decision.

### Hash-chained log
Each JSONL line carries the SHA-256 of the previous line. Edit or delete any line and the
chain breaks, so tampering is visible. I also added a guard that refuses to write raw IBANs
or emails to the log, so masking failures can't quietly leak into the audit trail.

## Tools and choices

- **Standard library only on the default path.** No cloud, no paid API, no download. The
  offline LLM client is deterministic, which keeps CI free and the tests stable.
- **Pluggable LLM behind a tiny protocol.** `OfflineClient` (default), `MockClient` (tests),
  and room for a real local model later — the pipeline never changes.
- **Rule-based where trust matters.** Ingest, phishing and injection are regex/heuristics
  so the decision has a reason string and no model risk.
- **pytest + a small eval harness.** Unit tests per module; the harness measures the
  pipeline end to end and writes only the numbers the run produces.

## Each security decision, with the "why"

1. **Mask before the model.** So the model, the handoff and the log never see raw PII.
2. **Injection detector on masked text.** So I test the exact string the model would see.
3. **No auto account changes.** The blast radius of a wrong tariff/cancellation/address
   change is high; a human approves.
4. **Queue out-of-hours, never close.** Silent closing is the failure mode I'm reacting to.
5. **Unknown ≠ trusted.** Missing auth headers yield "unknown", so I don't fake confidence.
6. **Tamper-evident log, no PII.** The audit trail must be trustworthy and must not become
   a new PII leak.

## What I would do next

- Replace the keyword retrieval with small sentence embeddings (still local) to lift the
  category accuracy above the current measured 0.8942 — the misses are near-neighbour
  categories like Vertrag vs. Tarifwechsel.
- Add a real local-model adapter (e.g. Ollama) behind the existing `LLMClient` protocol
  and re-run the eval to compare numbers honestly.
- Expand the phishing and injection corpora so the 1.0 scores are stress-tested against
  harder, more varied synthetic cases.

## Honest limits

The scores are on my own synthetic corpus, generated in this repo. They show the pipeline
behaves as designed on those cases; they are **not** a benchmark and say nothing about real
traffic. Nothing here is certified or audit-ready — it's a portfolio build.
