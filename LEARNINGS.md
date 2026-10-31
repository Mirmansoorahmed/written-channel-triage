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

## What the larger eval exposed

I grew the corpus to 199 synthetic messages (at least 30 phishing, 30 injection, 20
PII-heavy, 10 out-of-hours), on purpose including hard cases. The bigger set changed the
numbers and that is the point — small sets can hide weaknesses. Measured this run:

- **Injection recall dropped to 0.9259**: the detector misses 2 obfuscated attempts — a
  spaced-out `I G N O R E all previous instructions` and `repeat the above instructions …
  then ignore them`. My regex patterns key on contiguous phrasing, so spacing and novel
  wording slip past. A real fix is normalising whitespace/leet before matching and adding
  a "repeat/verbatim your instructions" pattern.
- **Phishing precision dropped to 0.963**: one false positive, a malicious
  `wget http://…/payload` line that matched the payment-link rule via the `pay` substring
  in "payload". It is genuinely malicious, just mislabelled as phishing — a reminder that
  substring heuristics catch more than they name.
- **PII masking (27/27) and out-of-hours queueing (14/14)** held at recall 1.0.
- **Category accuracy is 0.8894 (177/199)**, close to the earlier small-set number; the
  misses are still near-neighbour categories.

The lesson: a 1.0 on a handful of cases told me almost nothing. The honest numbers only
showed up once the sets were big enough to contain the awkward inputs.

## What I would do next

- Normalise text (collapse spacing, de-leet) before the injection regex, and add patterns
  for "repeat/verbatim your instructions" to close the 2 misses above.
- Tighten the payment-link heuristic so it does not fire on `payload`-style substrings.
- Replace the keyword retrieval with small sentence embeddings (still local) to lift the
  measured category accuracy of 0.8894 — the misses are near-neighbour categories like
  Vertrag vs. Tarifwechsel.
- Add a real local-model adapter (e.g. Ollama) behind the existing `LLMClient` protocol
  and re-run the eval to compare numbers honestly.

## Honest limits

The scores are on my own synthetic corpus, generated in this repo. They show the pipeline
behaves as designed on those cases — including two cases where it does not — and they are
**not** a benchmark and say nothing about real traffic. Nothing here is certified or
audit-ready — it's a portfolio build.
