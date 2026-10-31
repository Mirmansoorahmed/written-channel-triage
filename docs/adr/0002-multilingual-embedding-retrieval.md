# ADR 0002 — Multilingual embedding retrieval over my own category text

Status: accepted (v2)

## Context
v1's keyword/regex retrieval confused near-neighbour categories (Vertrag vs. Tarifwechsel,
Kündigung vs. Vertrag), which the larger eval exposed. Customer text is German with some
English code-switching, so the retrieval signal has to be multilingual and semantic, not
lexical.

## Decision
Add an `EmbeddingRetriever` using `intfloat/multilingual-e5-small` (local, via
sentence-transformers) over my own category descriptions plus a few hand-written few-shot
examples per category. Vectors are L2-normalised and held in a plain numpy matrix; cosine
similarity is a dot product. The retriever returns top-k candidates for the SLM
(embeddings + SLM) and can also answer directly (embeddings-only). FAISS is an optional
swap behind the same `.search()` method.

## Consequences
- Near-neighbour categories should separate better than with keywords; the eval measures
  whether they actually do (System B and C vs. System A).
- numpy / sentence-transformers are optional extras, imported lazily; the default path and
  CI stay dependency-free, with retriever tests skipped when numpy is absent.
- e5 requires `query:`/`passage:` prefixes — the retriever owns that detail so callers
  don't have to know it.
- A tiny index means no separate vector service; this is deliberately scoped to a small
  category set.
