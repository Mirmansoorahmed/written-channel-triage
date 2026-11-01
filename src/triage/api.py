"""FastAPI delivery surface (V28): POST /triage, GET /healthz.

Reuses the existing pipeline unchanged. FastAPI/pydantic are optional extras
(`pip install .[api]`). The request model is defined at module scope (guarded by
availability) rather than inside create_app(): a route's body model must be
resolvable from the module globals, otherwise FastAPI cannot bind the JSON body
and every request fails validation with 422. Note there is deliberately NO
``from __future__ import annotations`` here -- stringised annotations would make
FastAPI resolve "TriageRequest" by name at route-build time, which reintroduces
the same 422 bug.

The endpoint takes {text, source} and returns the TriageResult as JSON. The token
map (raw PII) never leaves the process: only verdicts, categories, flags and the
masked handoff summary are serialised.
"""

from dataclasses import asdict
from datetime import datetime, timezone

from .models import Source, TriageResult

# Build the request model at import time when pydantic is present. Keeping it at
# module scope (not inside create_app) is what makes FastAPI's body binding work.
try:
    from pydantic import BaseModel, Field

    class TriageRequest(BaseModel):
        text: str = Field(..., description="Raw .eml string or plain form text")
        source: str = Field("form", description="'eml' or 'form'")

    _HAVE_PYDANTIC = True
except ImportError:  # pragma: no cover - exercised only without the extra
    TriageRequest = None  # type: ignore[assignment]
    _HAVE_PYDANTIC = False


def _result_to_dict(result: TriageResult) -> dict:
    """Serialise a TriageResult to JSON-safe primitives (no token map)."""
    d = asdict(result)
    # Enums -> their value.
    d["trust"]["level"] = result.trust.level.value
    d["policy"]["pending_approval"] = (
        asdict(result.policy.pending_approval) if result.policy.pending_approval else None
    )
    return d


def create_app(injection_detector: "tuple | None" = None):
    """Build the FastAPI app. Lazy import keeps the core dependency-free.

    `injection_detector` is an optional `(model, threshold)` override so a test can
    inject a stub without on-disk artifacts; by default the real artifacts are
    loaded (and fall back to rules-only when absent).
    """
    try:
        from fastapi import FastAPI
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "FastAPI is not installed. Install the API extra: pip install .[api]"
        ) from exc
    if not _HAVE_PYDANTIC:  # pragma: no cover
        raise RuntimeError(
            "pydantic is not installed. Install the API extra: pip install .[api]"
        )

    from fastapi import Response

    from . import observability as obs
    from . import pipeline

    # Load the trained injection detector once (model + dev threshold). Returns
    # (None, None) when the artifacts are absent, so /triage then uses rules only.
    if injection_detector is not None:
        inj_model, inj_threshold = injection_detector
    else:
        from . import learned
        inj_model, inj_threshold = learned.load_injection_detector()

    app = FastAPI(
        title="written-channel-triage",
        version="2.0.0",
        description="Secure written-channel triage for the fictional NordTel GmbH "
                    "(synthetic data only; not a certification).",
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}

    @app.get("/metrics")
    def metrics() -> Response:
        # Prometheus text exposition from the in-process registry.
        return Response(
            content=obs.prometheus_text(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.post("/triage")
    def triage(req: TriageRequest) -> dict:
        source = Source.EML if req.source == "eml" else Source.FORM
        result = pipeline.run(
            req.text, source=source,
            injection_model=inj_model, injection_threshold=inj_threshold,
        )
        return _result_to_dict(result)

    return app


def _try_build_app():
    try:
        return create_app()
    except RuntimeError:
        return None


# Built at import time so `uvicorn triage.api:app` works; None when the extra is
# absent (importing the module never fails).
app = _try_build_app()
