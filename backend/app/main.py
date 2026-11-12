"""BankOps AI - FastAPI application entry point."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.ai.analysis_service import AnalysisService
from app.api.deps import DbSession
from app.api.routes import ai, analytics, applications, calendar, evidence, incidents, ml, rca, reports, users
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.services.user_service import ensure_default_users

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("bankops")



@asynccontextmanager
async def lifespan(_: FastAPI):
    # Background analyses do not survive a restart; don't leave them RUNNING forever.
    try:
        if interrupted := AnalysisService.fail_interrupted():
            logger.warning("Marked %s interrupted AI analyses as FAILED", interrupted)
    except SQLAlchemyError:
        logger.exception("Could not check for interrupted AI analyses")
    # Pre-trained ML models for databases that have none yet (the hosted demo)
    try:
        from app.ml.bundle import import_bundle_if_empty

        if get_settings().ml_bundle_autoload:
            with SessionLocal() as db:
                import_bundle_if_empty(db)
    except Exception:  # noqa: BLE001 - ML is optional; the API must still start
        logger.exception("Could not import the pre-trained ML bundle")
    # Hosted demo: 12 months of history, loaded in the background so the API answers at once
    if get_settings().load_large_demo:
        from app.ingestion.demo_large import start_in_background

        start_in_background()
    # The tool always has an administrator and one user per role (also after a demo reset)
    try:
        with SessionLocal() as db:
            if created := ensure_default_users(db):
                logger.info("Created %s default users", created)
    except SQLAlchemyError:
        logger.exception("Could not create the default users")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="BankOps AI",
    summary="Banking Operational Risk & IT Incident Intelligence Platform",
    description=(
        "Module 2 - IT Incident Intelligence. All data is synthetic. "
        "SLA targets are demonstration values, not universal banking requirements."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    """Log method, path, status and latency only - never headers or bodies (they may hold secrets)."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s -> %s (%.0f ms) rid=%s", request.method, request.url.path, response.status_code, elapsed_ms, request_id)
    response.headers["X-Request-ID"] = request_id
    return response


def _error(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message, "details": details or {}}})


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError):
    return _error(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]
    return _error(422, "validation_error", "Request validation failed", {"errors": errors})


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_: Request, exc: SQLAlchemyError):
    logger.exception("Database error: %s", type(exc).__name__)
    return _error(500, "database_error", "A database error occurred")


app.include_router(incidents.router)
app.include_router(rca.router)
app.include_router(analytics.router)
app.include_router(applications.router)
app.include_router(calendar.router)
app.include_router(evidence.router)
app.include_router(ai.router)
app.include_router(reports.router)
app.include_router(users.router)
app.include_router(ml.router)


@app.get("/api/health", tags=["Health"])
def health(db: DbSession):
    db.execute(text("SELECT 1"))
    out = {"status": "ok", "service": settings.app_name, "environment": settings.app_env, "database": "ok"}
    if get_settings().load_large_demo:
        from app.ingestion.demo_large import STATE

        out["demo_history"] = STATE.get("state")
    return out
