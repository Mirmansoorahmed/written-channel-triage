# ADR 0001 — A local SLM behind the existing LLMClient protocol

Status: accepted (v2)

## Context
v1 shipped a deterministic `OfflineClient` behind a tiny `LLMClient` protocol. For v2 I
want a real model to lift category accuracy, but the default path and CI must stay
offline, free, and reproducible, and a customer must be able to run everything locally
with no cloud account.

## Decision
Add an `OllamaClient` that implements the same protocol and calls a local Ollama server
(default `qwen2.5:1.5b-instruct`, configurable). It requests constrained JSON
`{category, fields, confidence}` at temperature 0 with a timeout, and on **any** failure
(connection, timeout, bad JSON, out-of-set category) falls back to the baseline client.
`httpx` is imported lazily so the module imports with the standard library alone.

## Consequences
- The pipeline never changes to gain a real model; the SLM is one swap at the boundary.
- An unavailable or slow model degrades to v1 behaviour instead of failing a request.
- Determinism holds: temperature 0 + a pinned model + the seeded dataset.
- A small model will still make mistakes; the eval compares it honestly against the
  baseline rather than assuming it is better.
