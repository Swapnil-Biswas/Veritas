# VERITAS Seller API

Implements HireCrew's `seller-hosted-api-v1`. Source: `backend/app/api.py`.

All requests need `Authorization: Bearer <HIRECREW_SELLER_TOKEN>`. Credentials are accepted only in that header, never in the URL. Every error has the form:

```json
{ "error": { "code": "MACHINE_READABLE_CODE", "message": "Human-readable explanation." } }
```

## POST /jobs — submit a research job

Headers: `Authorization`, `Idempotency-Key` (required, ≤255 printable characters), `Content-Type: application/json`.

```http
POST /jobs
Authorization: Bearer <token>
Idempotency-Key: 8f0c6c2e-1f5b-4b8e-9d0e-6a4f3c2b1a90
Content-Type: application/json

{ "orderId": "hirecrew-order-id", "brief": "Research brief supplied by the buyer" }
```

| Field | Rules |
| :--- | :--- |
| `orderId` | Required, 1–128 chars, `[A-Za-z0-9._:-]` |
| `brief` | Required, 5–50,000 chars (the agent's input limit) |

Response `200 OK` (for both new jobs and replays):

```json
{ "jobId": "veritas-job-3f9a0c1b2d4e4f60a7b8c9d0e1f2a3b4", "status": "queued" }
```

A replay returns the existing job and its current status (`queued`, `running`, `delivered` or `failed`). The research is never re-run. See [Idempotency](#idempotency).

| Status | Code | When |
| :--- | :--- | :--- |
| 400 | `INVALID_REQUEST` / `INVALID_JSON` | Missing/invalid fields or malformed JSON (message names the fields, never echoes values) |
| 400 | `IDEMPOTENCY_KEY_REQUIRED` / `INVALID_IDEMPOTENCY_KEY` | Header missing or invalid |
| 401 | `UNAUTHORIZED` | Missing or non-Bearer `Authorization` |
| 403 | `FORBIDDEN` | Wrong token |
| 409 | `IDEMPOTENCY_CONFLICT` | Key or `orderId` already used for a different request |
| 413 | `PAYLOAD_TOO_LARGE` | Body over `VERITAS_MAX_BODY_BYTES` (256 KiB default) |

## GET /jobs/{jobId} — job status

```json
{ "jobId": "veritas-job-…", "orderId": "hirecrew-order-id", "status": "queued" }
```
```json
{ "jobId": "veritas-job-…", "orderId": "hirecrew-order-id", "status": "running" }
```

Delivered:

```json
{
  "jobId": "veritas-job-…",
  "orderId": "hirecrew-order-id",
  "status": "delivered",
  "report": "# Research Report: …",
  "sources": [ { "title": "Self-hosted runners - GitHub Docs", "url": "https://docs.github.com/en/actions/hosting-your-own-runners" } ],
  "retrievedAt": "2026-10-31T00:00:00+00:00",
  "limitations": ["…evidence gaps reported by the agent…"],
  "agent": { "id": "veritas-research-agent", "version": "1.0.0" }
}
```

`sources` contains exactly `{title, url}` per entry, because HireCrew validates sources strictly. The agent's full source records (publisher, snippets, claims supported, …) are stored in the job database (`source_details_json`).

Failed:

```json
{
  "jobId": "veritas-job-…",
  "orderId": "hirecrew-order-id",
  "status": "failed",
  "error": { "code": "RESEARCH_EXECUTION_FAILED", "message": "The research job could not be completed." }
}
```

| `error.code` | Meaning | Retried automatically? |
| :--- | :--- | :--- |
| `RESEARCH_TIMEOUT` | Agent exceeded `VERITAS_AGENT_TIMEOUT_SECONDS` or a lease expired on every attempt | Yes, until `VERITAS_MAX_ATTEMPTS` |
| `RESEARCH_EXECUTION_FAILED` | Agent raised an exception (retried) or reported `status=failed` (not retried) | See left |
| `INVALID_AGENT_OUTPUT` | Agent output failed schema/URL validation | No |
| `NO_EVIDENCE_RETRIEVED` | Agent returned `success` but no sources; nothing is delivered as verified research | No |
| `CLARIFICATION_REQUIRED` | Agent returned `needs_clarification`; response adds `clarificationQuestions` (and `limitations`) | No (buyer resubmits a clarified brief) |

Unknown or malformed job IDs return `404 JOB_NOT_FOUND`. Responses carry `Cache-Control: no-store`.

## GET /health

Unauthenticated, no sensitive data. `200` when the database and worker are up, otherwise `503`:

```json
{ "status": "ok", "database": true, "worker": true, "agent": { "agent_id": "veritas-research-agent", "version": "1.0.0" } }
```

## Idempotency

- `Idempotency-Key` and `orderId` are each unique in the database. One paid order maps to exactly one research job.
- Same key or same `orderId` with the same `orderId` + brief returns the existing job, including after timeouts, client retries with a fresh key, and server restarts.
- Same key or same `orderId` with a different brief or order returns `409 IDEMPOTENCY_CONFLICT`.
- Concurrent duplicates are serialised with SQLite `BEGIN IMMEDIATE`. Tests submit 12 simultaneous duplicates and observe exactly one job.
