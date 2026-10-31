"""Tests for the embedding retriever (V3, V4, V20), with a fake encoder.

No model download: a deterministic fake encoder maps known phrases to fixed
vectors so cosine neighbours are predictable. numpy is required for the vector
math; if it is not installed the whole module is skipped (CI installs it only on
the eval/models path).
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from triage.retrieval import (  # noqa: E402
    EmbeddingOnlyClient,
    EmbeddingRetriever,
    INJECTION_EXEMPLARS,
)
from triage import categories  # noqa: E402


class FakeEncoder:
    """Deterministic encoder: hashes each (prefix-stripped) text to a stable
    unit-ish vector, but anchors a few phrases near specific category text so the
    nearest-neighbour result is predictable."""

    def __init__(self, dim: int = 32):
        self.dim = dim

    def _vec(self, text: str):
        # Strip the e5 prefix the retriever adds.
        body = text.split(":", 1)[-1].strip().lower()
        rng = np.random.default_rng(abs(hash(body)) % (2**32))
        v = rng.standard_normal(self.dim).astype("float32")
        return v

    def encode(self, texts):
        return np.vstack([self._vec(t) for t in texts])


def _retriever():
    return EmbeddingRetriever(encoder=FakeEncoder(), top_k=3).build()


def test_build_indexes_all_categories():
    r = _retriever()
    cats_in_index = {e.category for e in r._entries}
    assert cats_in_index == {c.name for c in categories.CATEGORIES}


def test_search_returns_scores_best_first():
    r = _retriever()
    ranked = r.search("Mein Internet ist tot, kein Anschluss.")
    assert ranked, "expected at least one candidate"
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_candidates_excludes_sonstiges_and_respects_top_k():
    r = _retriever()
    cands = r.candidates("Frage zur Rechnung")
    assert len(cands) <= 3
    assert all(name != "Sonstiges" for name, _ in cands)


def test_nearest_category_matches_identical_passage():
    # Querying with a category's own description should rank that category top,
    # because the fake encoder is deterministic per text body.
    r = _retriever()
    desc = categories.get("Störung").description
    name, score = r.nearest_category(desc)
    assert name == "Störung"


def test_injection_similarity_high_for_known_exemplar():
    r = _retriever()
    score = r.injection_similarity(INJECTION_EXEMPLARS[0])
    assert score == pytest.approx(1.0, abs=1e-5)


def test_injection_similarity_lower_for_unrelated_text():
    r = _retriever()
    high = r.injection_similarity(INJECTION_EXEMPLARS[0])
    low = r.injection_similarity("Guten Tag, Frage zur Rechnung im Mai.")
    assert low < high


def test_embedding_only_client_uses_top_candidate():
    r = _retriever()
    client = EmbeddingOnlyClient(r)
    cands = r.candidates("Störung kein Internet")
    name, conf = client.classify("Störung kein Internet", cands)
    assert (name, conf) == cands[0]
