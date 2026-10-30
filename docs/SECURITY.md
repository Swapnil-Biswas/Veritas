# VERITAS Seller Backend — Security

Agent-level protections (SSRF barrier, prompt-injection neutralisation) belong to the Phase 1 agent. Known agent gaps are listed in [`PHASE2_AGENT_DEFECTS.md`](PHASE2_AGENT_DEFECTS.md) (D7: redirects bypass the agent's SSRF check). This document covers the backend.

| Control | Implementation |
| :--- | :--- |
| Authentication | `Authorization: Bearer` on every `/jobs` route, constant-time comparison (`secrets.compare_digest`). Tokens in query strings are ignored. |
| Secret handling | Token only from `HIRECREW_SELLER_TOKEN`. No default. Production refuses to start without it; dev/test use a random per-process token. `.env` is git-ignored and `.env.example` holds placeholders only. |
| Job access | Only the HireCrew-held token can read jobs. Job IDs are 128-bit random (`uuid4`). Unknown and malformed IDs both return 404. The API has a single tenant (HireCrew), so buyers never call it directly. |
| Input validation | Pydantic models; `orderId` charset and length limits; brief length capped at the agent's 50k limit; JSON object required; body size limit (256 KiB) enforced before parsing, including chunked bodies. |
| Error hygiene | Uniform `{"error": {code, message}}` envelope. Validation errors name fields but never echo values. Unhandled exceptions return a generic 500. Agent exception text and `ResearchReportOutput.error` are never exposed. |
| Logging | Briefs, reports and headers are not logged. A redaction filter masks Bearer tokens, the configured seller token, `key=/token=/secret=` values and prefixed API keys (`sk_…`, `ghp_…`, `hf_…`). `httpx` request logs are suppressed below WARNING. |
| Replay / duplicate execution | Persistent unique `Idempotency-Key` and `orderId`; conflicting reuse → 409; lease-guarded transitions prevent double delivery. |
| Transport | Served over HTTPS via the deployment's TLS terminator (see DEPLOYMENT.md). The app binds to `127.0.0.1` by default; `proxy_headers` trust only `VERITAS_FORWARDED_ALLOW_IPS`. |
| CORS | Disabled unless `VERITAS_CORS_ORIGINS` is set (HireCrew calls server-to-server). |
| Headers | `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on job responses. |
| Surface | `/docs` and `/openapi.json` are disabled in production. Only `/jobs` (and optionally `/health`) should be published through the tunnel or proxy. |
| Container | Non-root user (uid 10001), data on a dedicated volume. |

## Tested

`backend/tests/test_api.py::TestSecurity` and `TestAuth` cover: unauthorized and wrong-token access to submit and poll; query-string tokens rejected; the seller token never appearing in any response; no stack traces on malformed input; no CORS by default; log redaction of tokens and keys.

## Not covered

- Rate limiting is not implemented in-app. Rely on the edge (HireCrew is the only caller), or add a proxy limit if exposed more broadly.
- There is no token rotation endpoint. Rotate by changing `HIRECREW_SELLER_TOKEN` and restarting.
