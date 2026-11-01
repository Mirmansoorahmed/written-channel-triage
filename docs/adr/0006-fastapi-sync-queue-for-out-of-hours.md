# ADR 0006 — FastAPI synchronous endpoint, queue for out-of-hours

Status: accepted (v2)

## Context
v2 needs a delivery surface a customer can call. The pipeline is fast except for the SLM
call, and the product rule from v1 is that a request outside business hours is never
silently closed — it is queued with an ETA. I want the simplest thing that honours both.

## Decision
Expose a synchronous `POST /triage` (plus `GET /healthz`) with FastAPI, reusing the
pipeline unchanged. In-hours requests are handled inline; out-of-hours requests are marked
`queued` with an ETA for the next opening (the pipeline already computes this). The
serialiser drops the token map so no raw PII leaves the process. FastAPI is an optional
extra, imported lazily; `app` is built at import time only when the extra is present so
`uvicorn triage.api:app` works, and is `None` otherwise.

## Consequences
- The API is stateless per request and scales horizontally; only the audit log and the
  queue are shared state.
- Synchronous handling is fine at portfolio/demo scale; a high-volume deployment would move
  the SLM call behind a task queue (Celery/RQ/arq) and return a job id — a later ADR if the
  load justifies it.
- The out-of-hours contract is preserved end-to-end: queued, never dropped.
- Keeping FastAPI optional means the core package and CI never depend on it.
