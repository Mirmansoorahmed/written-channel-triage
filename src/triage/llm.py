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


def default_client() -> LLMClient:
    return OfflineClient()
