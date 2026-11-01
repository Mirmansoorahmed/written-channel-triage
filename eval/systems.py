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


class SystemD:
    """Embeddings + trained LogisticRegression (Round 3).

    The calibrated category model from triage/learned.py. Reports the calibrated
    probability of its chosen label as the confidence, which the harness uses for
    ECE/reliability and which System E routes on.
    """

    key = "D_embeddings_lr"
    label = "embeddings + LR (trained)"

    def __init__(self, category_model):
        self._model = category_model

    def classify(self, masked_text: str) -> tuple[str, float]:
        return self._model.predict(masked_text)


class SystemE:
    """System D, escalating to the SLM only when D's calibrated confidence is below
    the routing threshold. Reports the SLM call rate.

    The threshold passed here is a placeholder default; the harness overwrites
    `self.threshold` with the value chosen on DEV from D's probabilities
    (_choose_thresholds_on_dev), so routing is never a hard-coded 0.5 in a real run.
    This is the cost/quality trade: trust the cheap trained head when it is
    confident, pay for the SLM only on the uncertain tail.
    """

    key = "E_lr_then_slm"
    label = "LR, SLM on low confidence"

    def __init__(self, category_model, retriever, slm_client=None,
                 model: str = "qwen2.5:1.5b-instruct", threshold: float = 0.5):
        self._model = category_model
        self._retriever = retriever
        self._client = slm_client or OllamaClient(model=model, strict=True)
        self.threshold = threshold
        self.calls = 0
        self.slm_calls = 0

    def classify(self, masked_text: str) -> tuple[str, float]:
        self.calls += 1
        label, prob = self._model.predict(masked_text)
        if prob >= self.threshold:
            return label, prob
        # Low confidence -> escalate to the SLM over the retriever's candidates.
        self.slm_calls += 1
        result = classify_mod.classify(
            masked_text, client=self._client, retriever=self._retriever
        )
        return result.category, result.confidence

    @property
    def slm_call_rate(self) -> float:
        return round(self.slm_calls / self.calls, 4) if self.calls else 0.0

    @property
    def stats(self) -> dict:
        s = dict(getattr(self._client, "stats", {}))
        s["slm_call_rate"] = self.slm_call_rate
        s["escalations"] = self.slm_calls
        s["total"] = self.calls
        return s


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


def build_learned_systems(models_dir: str, model: str = "qwen2.5:1.5b-instruct",
                          e_threshold: float = 0.5):
    """Build D (and E) from saved artifacts. Raises if artifacts/libs are missing
    so the harness can mark them pending rather than fabricate a run.
    """
    import os

    from triage import learned
    from triage.retrieval import EmbeddingRetriever

    embedder = learned.E5Embedder()
    cat_model = learned.load_category_model(
        os.path.join(models_dir, "category_lr.joblib"), embedder
    )
    systems = [SystemD(cat_model)]
    # E needs both the LR and a working SLM + retriever. If the SLM is down, the
    # strict probe raises and E is marked pending by the caller.
    retriever = EmbeddingRetriever().build()
    probe = OllamaClient(model=model, strict=True)
    probe.classify("Testanfrage zur Rechnung.", [("Rechnung", 0.5)])
    systems.append(SystemE(cat_model, retriever, model=model, threshold=e_threshold))
    return systems, cat_model


def build_offline_systems():
    """Only System A, which needs no model."""
    return [SystemA()]
