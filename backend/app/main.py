"""
VERITAS seller backend application.

Run:  uvicorn app.main:app --host 127.0.0.1 --port 8020   (from backend/)
The worker pool runs inside the same process and is started/stopped by the lifespan.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.adapter import VeritasAgentAdapter
from app.api import ApiError, api_error, router
from app.config import settings
from app.logging_setup import configure_logging
from app.store import JobStore
from app.worker import JobWorker

configure_logging(settings.log_level)
log = logging.getLogger("veritas.app")


def build_worker(store: JobStore) -> JobWorker:
    adapter = VeritasAgentAdapter(
        timeout_seconds=settings.agent_timeout_seconds,
        depth=settings.agent_depth,
        max_sources=settings.agent_max_sources,
    )
    return JobWorker(
        store, adapter,
        concurrency=settings.worker_concurrency,
        poll_seconds=settings.worker_poll_seconds,
        lease_seconds=settings.lease_seconds,
        retry_backoff_seconds=settings.retry_backoff_seconds,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = JobStore(settings.db_path)
    app.state.worker = build_worker(app.state.store)
    if getattr(app.state, "start_worker", True):
        app.state.worker.start()
    log.info("VERITAS seller backend started (env=%s, workers=%d)", settings.env, settings.worker_concurrency)
    try:
        yield
    finally:
        await app.state.worker.stop()
        log.info("VERITAS seller backend stopped")


app = FastAPI(
    title="VERITAS Seller API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        allow_credentials=False,
    )


@app.middleware("http")
async def limit_body_and_harden(request: Request, call_next):
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) > settings.max_body_bytes:
                return api_error(413, "PAYLOAD_TOO_LARGE", "Request body is too large.")
        except ValueError:
            return api_error(400, "INVALID_REQUEST", "Invalid Content-Length header.")
    elif request.method == "POST":
        body = await request.body()  # chunked upload: Starlette caches it for the route
        if len(body) > settings.max_body_bytes:
            return api_error(413, "PAYLOAD_TOO_LARGE", "Request body is too large.")
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return api_error(exc.status, exc.code, exc.message, exc.headers)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    return api_error(400, "INVALID_REQUEST", "The request is invalid.")


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    return api_error(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), "Request could not be served.")


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    log.error("unhandled error: %s", type(exc).__name__)
    return api_error(500, "INTERNAL_ERROR", "An internal error occurred.")


@app.get("/health")
async def health(request: Request):
    try:
        db_ok = request.app.state.store.ping()
    except Exception:
        db_ok = False
    worker_ok = request.app.state.worker.running or not getattr(request.app.state, "start_worker", True)
    ok = db_ok and worker_ok
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "database": db_ok, "worker": worker_ok,
                 "agent": request.app.state.worker.adapter.identity},
    )


app.include_router(router)
