# VERITAS — HireCrew Integration

## Contract

VERITAS implements HireCrew's `seller-hosted-api-v1` (`POST /jobs`, `GET /jobs/{jobId}` with Bearer auth and `Idempotency-Key`). The contract was retrieved from the HireCrew builder kit's `get_seller_api_contract` tool. Request and response details are in [API.md](API.md). Two kit-specific details are handled:

- Delivered `sources` are exactly `{title, url}`. The kit's `check_local_research_result` rejects unknown keys.
- `report` and `sources` are top-level fields of the poll response.

## Seller MCP workflow

The HireCrew builder kit (`npm run mcp:seller-local`) is a local MCP server. On this machine it is at `C:\Users\swapn\OneDrive\Desktop\HireCrew\platform`, and it runs with Node 22 (the kit asks for ≥24, but works on 22).

Tools exposed by the installed kit, as listed by `tools/list`: `get_submission_guide`, `get_research_benchmark_pack`, `get_seller_api_contract`, `validate_deployment_manifest`, `check_local_research_result`.

**Known gap:** the Phase 2 brief asks for a `check_benchmark_fit` tool and for creating and submitting the private listing through seller MCP tools. Neither exists in the installed kit. Listings are created in the HireCrew web seller workspace (`https://hirecrew.si/seller`). If a newer kit adds these tools, use them as documented by the kit.

## Status

| Step | Status |
| :--- | :--- |
| Seller API, persistence, idempotency, worker, adapter | Done; 54 backend tests + live end-to-end test passing |
| Public HTTPS endpoint | Pending: needs the owner's Tailscale Funnel command (DEPLOYMENT.md, Option A) |
| Benchmark run (`get_research_benchmark_pack` → five briefs → `check_local_research_result`) | **Blocked** on agent defects D1–D6 ([PHASE2_AGENT_DEFECTS.md](PHASE2_AGENT_DEFECTS.md)). Running the benchmark now would only exercise hardcoded answers. |
| Private listing | Not created; waits for the benchmark |

No HireCrew approval or certification has been granted. A local `structural_pass` from the kit is developer feedback, not a marketplace score.
