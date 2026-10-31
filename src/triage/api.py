"""FastAPI delivery surface (V28): POST /triage, GET /healthz.

Reuses the existing pipeline unchanged. FastAPI/pydantic are optional extras
(`pip install .[api]`); they are imported lazily inside `create_app()`, so this
module imports fine with only the standard library and the core package. `app` is
built at import time only when FastAPI is available, so uvicorn can find it; if the
extra is missing, importing `app` raises a clear instruction instead of a cryptic
error.

The endpoint takes `{text, source}` and returns the TriageResult as JSON. The
token map (raw PII) never leaves the process: only verdicts, categories, flags and
the masked handoff summary are serialised.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from .models import Source, TriageResult


def _result_to_dict(result: TriageResult) -> dict:
    """Serialise a TriageResult to JSON-safe primitives (no token map)."""
    d = asdict(result)
    # Enums -> their value.
    d["trust"]["level"] = result.trust.level.value
    d["policy"]["pending_approval"] = (
        asdict(result.policy.pending_approval) if result.policy.pending_approval else None
    )
    return d


def create_app():
    """Build the FastAPI app. Lazy import keeps the core dependency-free."""
    try:
        from fastapi import FastAPI
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "FastAPI is not installed. Install the API extra: pip install .[api]"
        ) from exc

    from . import pipeline

    class TriageRequest(BaseModel):
        text: str = Field(..., description="Raw .eml string or plain form text")
        source: str = Field("form", description="'eml' or 'form'")

    app = FastAPI(
        title="written-channel-triage",
        version="2.0.0",
        description="Secure written-channel triage for the fictional NordTel GmbH "
                    "(synthetic data only; not a certification).",
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}

    @app.post("/triage")
    def triage(req: TriageRequest) -> dict:
        source = Source.EML if req.source == "eml" else Source.FORM
        result = pipeline.run(req.text, source=source)
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
