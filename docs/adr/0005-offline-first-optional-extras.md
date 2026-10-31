# ADR 0005 — Offline-first core with optional extras and lazy imports

Status: accepted (v2)

## Context
v2 pulls in heavy libraries (sentence-transformers, numpy, matplotlib, fastapi, httpx) and
a model server. If any of those were required to import the package, CI would need
downloads, the default path would break offline, and a reviewer couldn't run the tests on
a plain machine.

## Decision
Keep the core install dependency-free. Group heavy libraries into optional extras in
`pyproject.toml` (`models`, `eval`, `api`) and import every heavy library **lazily**,
inside the function that uses it — never at module top level. Tests mock the model
boundaries (fake `httpx`, fake encoder) and skip the numpy-only paths when numpy is absent.
CI runs the stdlib pytest, the v1 eval, and the offline subset of the v2 harness.

## Consequences
- `import triage.*` works with the standard library alone, which is the invariant that
  keeps CI green and the review cheap.
- The real-model path (`make eval-real`, the API, Docker) is one `pip install .[extra]`
  away on the customer's machine.
- A missing optional library degrades a feature (no PNG, embeddings off) rather than
  crashing — enforced by the lazy-import try/except pattern.
- There is some ceremony (functions import their own deps), accepted as the cost of the
  offline guarantee.
