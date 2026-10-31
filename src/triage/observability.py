"""In-process metrics and structured logging (review fix #5).

The architecture doc lists metric names; this module makes them real so the names
are backed by code rather than aspiration. It is a tiny, dependency-free registry
(counters, a histogram, a gauge) that the pipeline increments. A Prometheus
exporter could read `snapshot()`; we deliberately do not pull in a client library
on the default path.

Metric names here are the single source of truth; `docs/architecture.md` lists the
same names, and `tests/test_observability.py` asserts they stay in sync.

Structured logging: `log_event()` emits one JSON object per decision to a logger,
never containing raw PII (only verdicts, categories, flags, counts).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict

_LOCK = threading.Lock()

# Counter name -> {label-tuple: count}. Labels are kept as a sorted tuple of
# (key, value) pairs so the same label set aggregates.
_COUNTERS: dict[str, dict[tuple, int]] = defaultdict(lambda: defaultdict(int))
# Histogram name -> list of observed values (ms). Bucketed on snapshot.
_HISTOGRAMS: dict[str, list[float]] = defaultdict(list)
# Gauge name -> value.
_GAUGES: dict[str, float] = defaultdict(float)

# The canonical metric names. Keep in sync with docs/architecture.md.
COUNTER_NAMES = (
    "triage_requests_total",
    "triage_injection_detected_total",
    "triage_phishing_suspected_total",
    "triage_policy_blocked_total",
    "triage_slm_fallback_total",
    "triage_pii_leak_blocked_total",
)
HISTOGRAM_NAMES = ("triage_request_latency_ms",)
GAUGE_NAMES = ("triage_queue_depth",)

_logger = logging.getLogger("triage")


def _labels_key(labels: dict | None) -> tuple:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def inc(name: str, value: int = 1, **labels) -> None:
    with _LOCK:
        _COUNTERS[name][_labels_key(labels)] += value


def observe(name: str, value_ms: float) -> None:
    with _LOCK:
        _HISTOGRAMS[name].append(float(value_ms))


def set_gauge(name: str, value: float) -> None:
    with _LOCK:
        _GAUGES[name] = float(value)


def reset() -> None:
    with _LOCK:
        _COUNTERS.clear()
        _HISTOGRAMS.clear()
        _GAUGES.clear()


def snapshot() -> dict:
    """Return a JSON-safe snapshot of all metrics (what an exporter would read)."""
    with _LOCK:
        counters = {
            name: {("{" + ",".join(f"{k}={v}" for k, v in key) + "}" if key else "_"): n
                   for key, n in series.items()}
            for name, series in _COUNTERS.items()
        }
        hists = {}
        for name, vals in _HISTOGRAMS.items():
            s = sorted(vals)
            n = len(s)
            def pct(p):
                if not s:
                    return None
                k = (p / 100) * (n - 1)
                lo = int(k)
                hi = min(lo + 1, n - 1)
                return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)
            hists[name] = {"count": n, "p50_ms": pct(50), "p95_ms": pct(95)}
        gauges = dict(_GAUGES)
    return {"counters": counters, "histograms": hists, "gauges": gauges}


def log_event(event: str, **fields) -> None:
    """Emit one structured JSON log line (no raw PII; caller passes only safe fields)."""
    record = {"event": event, **fields}
    _logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))
