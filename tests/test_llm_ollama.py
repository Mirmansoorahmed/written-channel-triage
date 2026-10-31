"""Tests for the real-model clients, fully mocked (V5).

No network, no model download: the Ollama HTTP boundary is replaced with a fake
`httpx` module injected into sys.modules, and the embedding retriever is driven by
a deterministic fake encoder. CI runs these with the standard library only.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from triage.llm import OllamaClient, OfflineClient


def _install_fake_httpx(monkeypatch, *, response=None, raise_exc=None):
    """Install a fake `httpx` module that OllamaClient will import lazily."""
    fake = types.ModuleType("httpx")

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _post(url, json=None, timeout=None):  # noqa: A002 - mirror httpx API
        if raise_exc is not None:
            raise raise_exc
        return _Resp(response)

    fake.post = _post
    monkeypatch.setitem(sys.modules, "httpx", fake)
    return fake


def test_ollama_parses_valid_json(monkeypatch):
    model_json = {"response": json.dumps({"category": "Rechnung", "fields": {}, "confidence": 0.9})}
    _install_fake_httpx(monkeypatch, response=model_json)
    client = OllamaClient()
    name, conf = client.classify("Frage zur Rechnung", [("Rechnung", 0.5), ("Vertrag", 0.1)])
    assert name == "Rechnung"
    assert conf == 0.9
    assert client.last_fallback is None


def test_ollama_falls_back_on_connection_error(monkeypatch):
    _install_fake_httpx(monkeypatch, raise_exc=RuntimeError("connection refused"))
    client = OllamaClient()
    name, conf = client.classify("Frage zur Rechnung", [("Rechnung", 0.7)])
    # Fallback returns the baseline's top candidate.
    assert name == "Rechnung"
    assert client.last_fallback is not None
    assert "RuntimeError" in client.last_fallback


def test_ollama_falls_back_on_malformed_json(monkeypatch):
    _install_fake_httpx(monkeypatch, response={"response": "not json at all"})
    client = OllamaClient()
    name, conf = client.classify("x", [("Störung", 0.6)])
    assert name == "Störung"  # baseline fallback
    assert client.last_fallback is not None


def test_ollama_rejects_out_of_set_category(monkeypatch):
    model_json = {"response": json.dumps({"category": "NichtErlaubt", "confidence": 0.99})}
    _install_fake_httpx(monkeypatch, response=model_json)
    client = OllamaClient()
    name, conf = client.classify("x", [("Vertrag", 0.4)])
    assert name == "Vertrag"  # baseline fallback, out-of-set rejected
    assert "not in allowed set" in client.last_fallback


def test_ollama_clamps_confidence(monkeypatch):
    model_json = {"response": json.dumps({"category": "Vertrag", "confidence": 5.0})}
    _install_fake_httpx(monkeypatch, response=model_json)
    client = OllamaClient()
    name, conf = client.classify("x", [("Vertrag", 0.4)])
    assert name == "Vertrag"
    assert conf == 1.0


def test_ollama_fallback_when_httpx_missing(monkeypatch):
    # Simulate httpx not installed: importing it raises ImportError.
    monkeypatch.setitem(sys.modules, "httpx", None)
    client = OllamaClient()
    name, conf = client.classify("Frage zur Rechnung", [("Rechnung", 0.8)])
    assert name == "Rechnung"
    assert "httpx not installed" in client.last_fallback


def test_ollama_default_model_and_host():
    client = OllamaClient()
    assert client.model == "qwen2.5:1.5b-instruct"
    assert client.host.startswith("http")
