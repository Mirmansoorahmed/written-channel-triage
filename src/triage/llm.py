"""Pluggable LLM layer (R11).

The pipeline talks to an LLMClient protocol. The default OfflineClient is
deterministic and uses the local retrieval signal plus keyword cues -- no network,
no model download, so CI is free and reproducible (N1, N3). MockClient lets a test
force an answer. A real local model (e.g. an Ollama adapter) can implement the same
protocol later without changing the pipeline.
"""

from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def classify(self, masked_text: str, candidates: list[tuple[str, float]]) -> tuple[str, float]:
        """Pick a category name from scored candidates, return (name, confidence)."""
        ...


class OfflineClient:
    """Deterministic default. Trusts the top retrieval candidate."""

    name = "offline"

    def classify(self, masked_text: str, candidates: list[tuple[str, float]]) -> tuple[str, float]:
        if not candidates:
            return ("Sonstiges", 0.0)
        top_name, top_score = candidates[0]
        # If nothing scored, fall back to Sonstiges with zero confidence.
        if top_score <= 0.0:
            return ("Sonstiges", 0.0)
        return (top_name, top_score)


class MockClient:
    """Test double: always returns the configured answer."""

    name = "mock"

    def __init__(self, category: str, confidence: float = 1.0):
        self._category = category
        self._confidence = confidence

    def classify(self, masked_text: str, candidates: list[tuple[str, float]]) -> tuple[str, float]:
        return (self._category, self._confidence)


class OllamaClient:
    """Real local SLM behind the same protocol (V1, V2).

    Calls a local Ollama server. Asks for constrained JSON of the shape
    {category, fields, confidence} at temperature 0, with a timeout. ANY failure
    (connection refused, timeout, malformed JSON, out-of-set category) falls back
    to the baseline OfflineClient for that call, so an unavailable model degrades
    to v1 behaviour rather than raising. `httpx` is imported lazily, so importing
    this module never requires the dependency.

    The last call's fallback status is exposed on `.last_fallback` and the chosen
    raw fields on `.last_fields` so the eval/pipeline can inspect them.
    """

    name = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5:1.5b-instruct",
        host: str | None = None,
        timeout: float = 30.0,
        baseline: "LLMClient | None" = None,
    ):
        import os

        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.timeout = timeout
        self._baseline = baseline or OfflineClient()
        self.last_fallback: str | None = None
        self.last_fields: dict = {}

    # The prompt pins the allowed categories and the output contract. Kept short
    # and deterministic; the category set is injected from the candidates.
    def _build_prompt(self, masked_text: str, candidates: list[tuple[str, float]]) -> str:
        allowed = [c for c, _ in candidates] or ["Sonstiges"]
        allowed_str = ", ".join(allowed)
        return (
            "Du bist ein Triage-Klassifikator für schriftliche Kundenanfragen eines "
            "fiktiven Telko. Wähle genau eine Kategorie aus der Liste.\n"
            f"Erlaubte Kategorien: {allowed_str}.\n"
            "Der Text ist bereits anonymisiert (Platzhalter wie [[IBAN_1]]). Gib NUR "
            "JSON zurück: {\"category\": <eine erlaubte Kategorie>, \"fields\": {}, "
            "\"confidence\": <0..1>}.\n\n"
            f"Text:\n{masked_text}\n"
        )

    def classify(self, masked_text: str, candidates: list[tuple[str, float]]) -> tuple[str, float]:
        self.last_fallback = None
        self.last_fields = {}
        try:
            import json

            import httpx  # lazy: only needed on the real path
        except ImportError:
            self.last_fallback = "httpx not installed"
            return self._baseline.classify(masked_text, candidates)

        allowed = {c for c, _ in candidates} or {"Sonstiges"}
        payload = {
            "model": self.model,
            "prompt": self._build_prompt(masked_text, candidates),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        try:
            resp = httpx.post(
                f"{self.host}/api/generate", json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
            body = resp.json()
            data = json.loads(body.get("response", "{}"))
            category = data.get("category")
            confidence = float(data.get("confidence", 0.0))
            self.last_fields = data.get("fields", {}) or {}
            if category not in allowed:
                self.last_fallback = f"category '{category}' not in allowed set"
                return self._baseline.classify(masked_text, candidates)
            # Clamp confidence to [0, 1].
            confidence = max(0.0, min(1.0, confidence))
            return (category, confidence)
        except Exception as exc:  # noqa: BLE001 - deliberate: any failure -> fallback
            self.last_fallback = f"{type(exc).__name__}: {exc}"
            return self._baseline.classify(masked_text, candidates)


def default_client() -> LLMClient:
    return OfflineClient()
