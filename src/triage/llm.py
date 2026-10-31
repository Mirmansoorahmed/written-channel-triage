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
        keep_alive: str = "30m",
        strict: bool = False,
    ):
        import os

        self.model = model
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.timeout = timeout
        self.keep_alive = keep_alive
        # `strict` (used by the eval): raise on an AVAILABILITY failure (httpx
        # missing, connection refused) instead of silently substituting the
        # baseline, so a broken setup can never masquerade as a measured run.
        # Per-item soft failures (timeout, bad JSON, out-of-set category) are
        # always counted in `stats` and fall back for that one item so the eval
        # can still complete and report the failure rate.
        self.strict = strict
        self._baseline = baseline or OfflineClient()
        self.last_fallback: str | None = None
        self.last_fields: dict = {}
        self.stats = self._fresh_stats()

    @staticmethod
    def _fresh_stats() -> dict:
        return {
            "calls": 0,
            "fallbacks": 0,
            "invalid_category": 0,
            "timeouts": 0,
            "json_failures": 0,
            "connection_errors": 0,
            "confidences": [],
        }

    def reset_stats(self) -> None:
        self.stats = self._fresh_stats()

    # The prompt pins the allowed categories (always including Sonstiges) and the
    # output contract. Kept short and deterministic.
    def _build_prompt(self, masked_text: str, allowed: list[str]) -> str:
        allowed_str = ", ".join(allowed)
        return (
            "Du bist ein Triage-Klassifikator für schriftliche Kundenanfragen eines "
            "fiktiven Telko. Wähle genau eine Kategorie aus der Liste.\n"
            f"Erlaubte Kategorien: {allowed_str}.\n"
            "Wenn nichts passt, wähle 'Sonstiges'.\n"
            "Der Text ist bereits anonymisiert (Platzhalter wie [[IBAN_1]]). Gib NUR "
            "JSON zurück: {\"category\": <eine erlaubte Kategorie>, \"fields\": {}, "
            "\"confidence\": <0..1>}.\n\n"
            f"Text:\n{masked_text}\n"
        )

    def classify(self, masked_text: str, candidates: list[tuple[str, float]]) -> tuple[str, float]:
        self.last_fallback = None
        self.last_fields = {}
        self.stats["calls"] += 1

        # Allowed set always includes Sonstiges so the model has an explicit
        # "none of these" choice (review fix #3).
        allowed_list = [c for c, _ in candidates]
        if "Sonstiges" not in allowed_list:
            allowed_list = allowed_list + ["Sonstiges"]
        allowed = set(allowed_list)

        try:
            import httpx  # lazy: only needed on the real path
        except ImportError as exc:
            if self.strict:
                raise RuntimeError(
                    "OllamaClient(strict=True): httpx is not installed; install "
                    "the models extra: pip install .[models]"
                ) from exc
            self.stats["connection_errors"] += 1
            self.stats["fallbacks"] += 1
            self.last_fallback = "httpx not installed"
            return self._baseline.classify(masked_text, candidates)

        import json

        payload = {
            "model": self.model,
            "prompt": self._build_prompt(masked_text, allowed_list),
            "stream": False,
            "format": "json",
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0},
        }

        # 1) Transport layer. A connection/timeout error is an AVAILABILITY
        #    problem: raise in strict mode, else count + fall back.
        try:
            resp = httpx.post(
                f"{self.host}/api/generate", json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            is_timeout = "Timeout" in name
            if is_timeout:
                self.stats["timeouts"] += 1
            else:
                self.stats["connection_errors"] += 1
            self.last_fallback = f"{name}: {exc}"
            if self.strict and not is_timeout:
                # A refused/failed connection in strict mode must fail loudly.
                raise RuntimeError(
                    f"OllamaClient(strict=True): cannot reach Ollama at {self.host} "
                    f"({name}: {exc})"
                ) from exc
            self.stats["fallbacks"] += 1
            return self._baseline.classify(masked_text, candidates)

        # 2) Content layer. Bad JSON or an out-of-set category are soft failures:
        #    count them and fall back for this one item (never raise, so the eval
        #    can still report the failure rate).
        try:
            data = json.loads(body.get("response", "{}"))
        except (ValueError, TypeError):
            self.stats["json_failures"] += 1
            self.stats["fallbacks"] += 1
            self.last_fallback = "invalid JSON in model response"
            return self._baseline.classify(masked_text, candidates)

        category = data.get("category")
        try:
            confidence = float(data.get("confidence", 0.0))
        except (ValueError, TypeError):
            confidence = 0.0
        self.last_fields = data.get("fields", {}) or {}

        if category not in allowed:
            self.stats["invalid_category"] += 1
            self.stats["fallbacks"] += 1
            self.last_fallback = f"category '{category}' not in allowed set"
            return self._baseline.classify(masked_text, candidates)

        confidence = max(0.0, min(1.0, confidence))
        self.stats["confidences"].append(round(confidence, 3))
        return (category, confidence)


def default_client() -> LLMClient:
    return OfflineClient()
