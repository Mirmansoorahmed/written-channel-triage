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

---

# v2 — turning it into something I could hand a customer

v1 proved the pipeline behaves as designed and, importantly, exposed two real gaps once the
corpus was big enough. v2 is about closing those gaps honestly, putting real models behind
the protocol I already had, and building the dataset, eval, delivery and documentation a
Forward Deployed Engineer would hand over. The rule I kept: **the default path stays offline
and free, and no number appears unless a run produced it.**

## Real models, same seams

- **OllamaClient behind the v1 `LLMClient` protocol.** It asks a local SLM
  (`qwen2.5:1.5b-instruct`) for constrained JSON `{category, fields, confidence}` at
  temperature 0 with a timeout. The decision I'm proudest of is the **fallback**: any
  failure — connection refused, timeout, malformed JSON, a category outside the allowed set
  — returns the v1 baseline answer and records why. An unavailable model degrades quality,
  never safety, and never crashes a request. `httpx` is imported lazily so the module still
  imports with the standard library alone.
- **Embedding retrieval, local and multilingual.** `intfloat/multilingual-e5-small` over my
  own category descriptions plus a few few-shot examples. The point is the v1 misses were
  near-neighbour categories (Vertrag vs. Tarifwechsel), which keywords can't separate but
  embeddings should. The eval measures whether they actually do — I'm not assuming it.
- **Lazy imports everywhere.** numpy, sentence-transformers, matplotlib, fastapi all live
  inside the functions that use them. Importing any module with the stdlib must not raise;
  that invariant is what keeps CI green with no downloads, and the tests mock the model
  boundaries (fake httpx, fake encoder).

## Closing the v1 gaps

- **Injection recall was 0.9259** because the regexes keyed on contiguous phrasing. v2
  normalises first — NFKC, strip zero-width/bidi characters, fold a small
  Cyrillic/Greek homoglyph table, collapse deliberate single-letter spacing — then matches.
  I added a "repeat/verbatim your instructions" pattern (the second miss) and a step that
  decodes short base64 blobs and re-scans them. On the generated test split the four
  obfuscation families (plain, spaced, homoglyph, base64) are all caught, with zero false
  positives on the benign look-alikes. The de-spacer only collapses runs of ≥4 single
  characters, so I don't mangle ordinary short text — an explicit precision/recall trade.
- **The phishing false positive** (`wget …/payload` matched the `pay` substring) is fixed
  with a word-boundary payment-link rule. A genuine `pay-…/login` link still matches; the
  malicious `/payload` no longer counts as a payment link (it's still malicious, just not
  that label).
- **Post-model PII re-check.** After the SLM returns, any field value containing an
  unmasked IBAN/email/phone/customer-number is dropped and flagged. So even if a model
  echoes a raw value, it can't leak onward.

## Data and eval, done so the numbers mean something

- **Seeded dataset.** `data/generator.py` builds ~2,050 items from templates with a tone
  knob, a typo injector and a German/English mixer, realistic auth headers, and explicit
  attack/PII families — then writes a stratified train/dev/test split. One fixed seed means
  the customer and I run byte-for-byte identical data (I verified by hashing two runs). The
  test split is held out; the eval reads only `test.jsonl`.
- **Three systems, one interface.** v1 regex, embeddings-only, embeddings + SLM, scored the
  same way: accuracy, macro-F1, per-class precision/recall, confusion matrix (PNG + CSV),
  latency p50/p95, and detector precision/recall. The error analysis and datasheet are
  generated from the data, never typed.
- **Pending by design.** Offline (and in CI) only System A runs; B and C are written as
  `"pending real run"` with no numbers. `make eval-real` fills them on a machine with the
  models. This is the honest version of "here are my results" — the numbers show up when a
  real run produces them.

## Delivery and docs

A FastAPI `POST /triage` over the unchanged pipeline (serialised without the token map, so
no raw PII leaves the process), a Dockerfile and a compose file for api + ollama, an
architecture doc with trust boundaries and a data-flow view of where PII lives, 6 ADRs, and
a STRIDE threat model mapped to OWASP LLM Top 10 (2025) and MITRE ATLAS with the covering
test named for each threat.

## Honest limits (unchanged in spirit from v1)

Everything is measured on **synthetic** data generated in this repo. It shows the pipeline
behaves as designed on those cases and is **not** a benchmark or a statement about real
traffic. Detection is heuristic plus a small model, so a novel enough injection can still
slip past; the embedding-similarity check narrows that but does not close it. Nothing here
is certified or audit-ready — it's a portfolio build, written so I can defend every line.

---

# Round 3 — making the comparison honest

A second review caught the places where v2 still flattered itself. The fixes below are
less about new features and more about not fooling myself (or a reader).

## The eval was leaking and double-scoring

- **Split by template, score once.** The harness had been scoring the test split twice
  (once per "bucket" and once for `overall_test`) and still carried an always-empty
  `seen_template` bucket. Now the splits are simply dev / test / unseen, each scored
  exactly once, and `overall_test` is just the test report. `slm_diagnostics` is counted
  once per split.
- **Category metric only on category items.** Phishing and injection rows were being
  mixed into the category accuracy. They are detector problems; the category metric now
  runs only on the category-bearing families.
- **A real "unseen" set.** I grew `eval/unseen/` to 200+ hand-written items (every
  category in German / English / mixed, plus indirect/forwarded, obfuscated, role-play and
  base64/rot13/leetspeak injections, lookalike-domain phishing, and benign-with-links
  mail). The overlap gate now also checks the unseen set against the generator's raw
  templates, not just the materialised train rows. The test-vs-unseen gap is the honest
  headline: a regex that looks strong on held-out templates it has seen the shape of can
  still fall to ~0.5 on genuinely new phrasing.

## The detectors were cheating

- **Phishing knew the generator's domains.** The old lookalike regex literally listed the
  dataset's bad domains. I deleted it and scored generic signals instead: auth fail/missing,
  a lookalike of NordTel's *own* domains (punycode decode + homoglyph fold + edit distance),
  link text/href mismatch, and urgency+payment — weighted against a documented threshold. A
  test fails if any generator domain reappears in `src/`.
- **The injection "embedding check" flagged almost everything.** The fixed 0.80 cosine
  cut-off was flagging 99/100 normal messages. It is gone. The verdict is now the normalised
  rules OR a trained injection-LR whose threshold is chosen on dev (best F1 with precision
  ≥ 0.9) and stored in `models/manifest.json`.

## A model, trained properly

System D is a calibrated LogisticRegression on `multilingual-e5-small` embeddings, fit on
`train.jsonl` only, with the injection threshold chosen on `dev.jsonl` only. Artifacts are
seeded and deterministic (same seed → same coefficients, checked in a test with a fake
embedder) and ship with a manifest (seed, versions, embedding model, labels, sha256 of the
train file, threshold). System E trusts D when its calibrated probability is high and pays
for the SLM only on the low-confidence tail, reporting its SLM-call rate.

## Calibration, because confidence lied

C's self-reported confidence sits near 0.95 whether or not it is right, so I report its ECE
honestly and do **not** route on it. D is calibrated on dev, and its calibrated probability
drives the human-review threshold (ADR 0007). ECE and a reliability table/PNG are reported
for both.

## PII, checked against the truth

The masker now tolerates typo'd labels (edit distance ≤ 2), partial and country-code-typo'd
IBANs (ED44/D44), typo'd streets and cities, truncated-TLD emails, and signature names after
any greeting — and the generator records each PII value in both pre- and post-typo form. The
leak check (`eval/pii_leak_check.py`) fuzzy-searches every ground-truth value over all test
and unseen items (partial ratio ≥ 0.85, any 8+ char IBAN fragment counts). It runs in CI and
the committed count is 0, measured against the truth rather than the masker's own regex.

## Honest limits (Round 3)

Still synthetic, still not a benchmark. The committed `results-v2.json` is a **pending**
placeholder on purpose: every metric, cost and calibration table says "pending real run"
until the models are run locally, because only System A runs without them and a one-system
table would be misleading. Run `make train && make eval-real && make docs` to fill them in.
