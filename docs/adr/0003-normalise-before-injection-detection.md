# ADR 0003 — Normalise text before the injection detector

Status: accepted (v2)

## Context
v1's injection recall was 0.9259 on the larger corpus: it missed a spaced-out
`I G N O R E all previous instructions` and a "repeat the above … then ignore them"
phrasing. The regexes keyed on contiguous phrasing, so spacing, homoglyphs, and encoding
slipped past. The detector correctly runs on the masked text, but on the *raw* surface of
that text.

## Decision
Add a `normalize()` step (NFKC, strip zero-width/bidi characters, fold a small
Cyrillic/Greek homoglyph table, collapse deliberate single-letter spacing) and run the
injection patterns on the normalised masked text. Add a "repeat/verbatim/print the above
instructions" pattern, and decode short base64 tokens to re-scan the decoded content. Keep
an optional embedding-similarity check for novel phrasings, active only when a retriever is
supplied.

## Consequences
- The two v1 misses are closed, and the generated obfuscation families (plain, spaced,
  homoglyph, base64) are detected at full recall on the test split (`results-v2.json`).
- Normalisation is for *matching only*; the original text is kept for display, so I don't
  mangle what a human reads.
- The de-spacer is tuned to only collapse runs of ≥4 single characters, so ordinary short
  sequences like "a b c" are left intact — a precision/recall trade-off I made explicit.
- base64 decoding is bounded (readable-text check, length gate) so it is not a DoS or a
  false-positive engine.
