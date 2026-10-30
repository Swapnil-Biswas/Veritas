"""
HireCrew seller API (seller-hosted-api-v1).

  POST /jobs            -> {"jobId", "status": "queued" | <existing status>}
  GET  /jobs/{jobId}    -> queued | running | delivered | failed (see docs/API.md)

Both endpoints require `Authorization: Bearer <HIRECREW_SELLER_TOKEN>`.
POST also requires `Idempotency-Key`. Errors use {"error": {"code", "message"}}
and never include stack traces, request bodies or credentials.
"""

import json
import re
import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import settings
from app.store import IdempotencyConflict, JobStore

JOB_ID_RE = re.compile(r"^veritas-job-[0-9a-f]{32}$")
router = APIRouter()


def api_error(status: int, code: str, message: str, headers: Optional[Dict[str, str]] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}}, headers=headers)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: Optional[Dict[str, str]] = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers


class SubmitJobRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    orderId: str = Field(..., min_length=1, max_length=settings.max_order_id_chars)
    brief: str = Field(..., min_length=5, max_length=settings.max_brief_chars)

    @field_validator("orderId")
    @classmethod
    def _order_id_charset(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", v):
            raise ValueError("orderId may contain only letters, digits, '.', '_', ':' and '-'")
        return v


# ------------------------------------------------------------------ deps


def get_store(request: Request) -> JobStore:
    return request.app.state.store


def require_seller(authorization: Optional[str] = Header(None)) -> None:
    if not authorization:
        raise ApiError(401, "UNAUTHORIZED", "Missing Authorization header.", {"WWW-Authenticate": "Bearer"})
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "UNAUTHORIZED", "Expected 'Authorization: Bearer <token>'.", {"WWW-Authenticate": "Bearer"})
    if not secrets.compare_digest(token.strip().encode(), settings.seller_token.encode()):
        raise ApiError(403, "FORBIDDEN", "Invalid seller token.")


# ---------------------------------------------------------------- views


def job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    view: Dict[str, Any] = {"jobId": job["job_id"], "orderId": job["order_id"], "status": job["status"]}
    if job["status"] == "delivered":
        view.update({
            "report": job["report"],
            "sources": json.loads(job["sources_json"] or "[]"),
            "retrievedAt": job["retrieved_at"],
            "limitations": json.loads(job["limitations_json"] or "[]"),
            "agent": {"id": job["agent_id"], "version": job["agent_version"]},
        })
    elif job["status"] == "failed":
        view["error"] = {"code": job["error_code"], "message": job["error_message"]}
        questions = json.loads(job["clarification_json"] or "[]")
        if questions:
            view["clarificationQuestions"] = questions
        limitations = json.loads(job["limitations_json"] or "[]")
        if limitations:
            view["limitations"] = limitations
    return view


# --------------------------------------------------------------- routes


@router.post("/jobs", dependencies=[Depends(require_seller)])
async def submit_job(
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    store: JobStore = Depends(get_store),
):
    key = (idempotency_key or "").strip()
    if not key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "The Idempotency-Key header is required.")
    if len(key) > settings.max_idempotency_key_chars or not key.isprintable():
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "The Idempotency-Key header is invalid.")

    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "INVALID_JSON", "Request body must be a JSON object.")
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_JSON", "Request body must be a JSON object.")
    try:
        req = SubmitJobRequest.model_validate(body)
    except ValidationError as e:
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in e.errors()})
        raise ApiError(400, "INVALID_REQUEST", f"Invalid or missing field(s): {', '.join(fields)}.")

    try:
        job, created = store.create_or_get(req.orderId, req.brief, key, settings.max_attempts)
    except IdempotencyConflict as e:
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", str(e))

    # 200 for both new and replayed submissions; replays return the existing job's current status.
    return JSONResponse(status_code=200, content={"jobId": job["job_id"], "status": job["status"]})


@router.get("/jobs/{job_id}", dependencies=[Depends(require_seller)])
async def get_job(job_id: str, store: JobStore = Depends(get_store)):
    if not JOB_ID_RE.match(job_id):
        raise ApiError(404, "JOB_NOT_FOUND", "Job not found.")
    job = store.get(job_id)
    if not job:
        raise ApiError(404, "JOB_NOT_FOUND", "Job not found.")
    return JSONResponse(content=job_view(job), headers={"Cache-Control": "no-store"})
