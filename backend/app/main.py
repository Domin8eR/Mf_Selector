"""AltStreet FastAPI application entry point."""

from datetime import date

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import auth, chat, compare, metrics, rankings, rules, schemes
from app.routers.alerts import router as alerts_router
from app.routers.audit import router as audit_router
from app.routers.reports import reports_router, compliance_router
from app.routers.workspaces import (
    router as workspaces_router,
    _interpret_router as workspace_interpret_router,
)
from app.insights.router import router as insights_router
# app.research_chat.router is decommissioned as of the 2026-07-17 merge — its
# capability was folded into app.ai.tools / app.routers.chat (/chat). Left
# unimported here deliberately; the module itself is left in place, not
# deleted, so this is reversible if something surfaces that still needs it.
# app.routers.data_quality is decommissioned as of this session — same
# pattern as research_chat above: the standalone nav destination/route was
# already removed from the frontend, and this fully unwires the backend too
# rather than leaving it reachable via direct API call with no UI in front
# of it. Left unimported here deliberately; the module itself (and its real
# Altstreet_AI queries) is left in place, not deleted — reversible by adding
# one import + one include_router line back.
from app.schemas.base import VersionedResponse

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="AltStreet API",
    description=(
        "Client-rule-based mutual fund research workspace. "
        "Surfaces ranked funds, structural improvement signals, and research insights. "
        "Does not provide investment recommendations."
    ),
    version="0.4.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else settings.allowed_origins,
    allow_credentials=not settings.debug,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(schemes.router)
app.include_router(rankings.router)
app.include_router(metrics.router)
app.include_router(rules.router)
app.include_router(chat.router)
app.include_router(compare.router)
app.include_router(insights_router)
app.include_router(alerts_router)
app.include_router(workspaces_router)
app.include_router(workspace_interpret_router)
app.include_router(audit_router)
app.include_router(reports_router)
app.include_router(compliance_router)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/version", response_model=VersionedResponse, tags=["ops"])
def version() -> VersionedResponse:
    """Return current data/rule/calculation version pointers."""
    return VersionedResponse(
        data_version=settings.data_version,
        rule_version=settings.rule_version,
        calculation_version=settings.calculation_version,
        as_of_date=date.today(),
    )
