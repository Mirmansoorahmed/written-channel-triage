"""The three systems compared in the v2 eval (V11).

Each system exposes one method: `classify(masked_text) -> (label, confidence)`.
The harness treats them uniformly, times them, and scores the labels.

  System A — v1 regex/keyword retrieval + OfflineClient. Needs nothing (stdlib).
  System B — embeddings-only: the nearest category from the embedding retriever.
  System C — embeddings + SLM: retriever supplies top-k, the SLM picks one.

Systems B and C need optional models. They are constructed lazily and a factory
reports whether they are available, so the harness can run the offline subset
(System A) and mark B/C "pending real run" when the models are absent.
"""

from __future__ import annotations

from triage import classify as classify_mod
from triage.llm import OfflineClient, OllamaClient


class SystemA:
    """v1 regex/keyword retrieval + deterministic offline client."""

    key = "A_v1_regex"
    label = "v1 regex/keyword"

    def __init__(self):
        self._client = OfflineClient()

    def classify(self, masked_text: str) -> tuple[str, float]:
        result = classify_mod.classify(masked_text, client=self._client)
        return result.category, result.confidence


class SystemB:
    """Embeddings-only: nearest category from the retriever."""

    key = "B_embeddings_only"
    label = "embeddings-only (nearest category)"

    def __init__(self, retriever):
        self._retriever = retriever

    def classify(self, masked_text: str) -> tuple[str, float]:
        return self._retriever.nearest_category(masked_text)


class SystemC:
    """Embeddings + SLM: retriever top-k -> SLM picks one.

    The SLM client runs in strict mode so an unavailable model fails the run
    loudly rather than silently degrading to the baseline (review fix #3). Its
    per-item stats (fallbacks, invalid categories, timeouts, JSON failures,
    confidences) are exposed via `.stats` for the harness to report.
    """

    key = "C_embeddings_slm"
    label = "embeddings + SLM"

    def __init__(self, retriever, client=None, model: str = "qwen2.5:1.5b-instruct"):
        self._retriever = retriever
        self._client = client or OllamaClient(model=model, strict=True)

    def classify(self, masked_text: str) -> tuple[str, float]:
        result = classify_mod.classify(
            masked_text, client=self._client, retriever=self._retriever
        )
        return result.category, result.confidence

    @property
    def stats(self) -> dict:
        return getattr(self._client, "stats", {})


def build_real_systems(model: str = "qwen2.5:1.5b-instruct"):
    """Build B and C with real models. Returns (systems, retriever) or raises
    ImportError/RuntimeError if the model libraries are not installed, or if the
    Ollama server cannot be reached (strict preflight), so the harness marks B/C
    pending rather than reporting a silent-fallback run as if it were measured.
    """
    from triage.retrieval import EmbeddingRetriever

    retriever = EmbeddingRetriever().build()  # triggers the real encoder load
    # Preflight: a strict probe call. If Ollama is down this raises, and the
    # harness records "pending real run" instead of a baseline-in-disguise run.
    probe = OllamaClient(model=model, strict=True)
    probe.classify("Testanfrage zur Rechnung.", [("Rechnung", 0.5)])
    return [SystemB(retriever), SystemC(retriever, model=model)], retriever


def build_offline_systems():
    """Only System A, which needs no model."""
    return [SystemA()]
