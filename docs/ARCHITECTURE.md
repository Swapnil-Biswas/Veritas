# VERITAS System Architecture

The research agent's internal workflow (Phase 1, Antigravity) is documented in [`architecture/RESEARCH_WORKFLOW.md`](architecture/RESEARCH_WORKFLOW.md) and [`architecture/EVIDENCE_MODEL.md`](architecture/EVIDENCE_MODEL.md). This document covers the Phase 2 seller backend that wraps it.

```
HireCrew ──HTTPS──▶ reverse proxy / tunnel ──▶ FastAPI (backend/app/main.py)
                                                 │  POST /jobs ──▶ JobStore.create_or_get   (idempotent insert)
                                                 │  GET  /jobs/:id ◀── JobStore.get
                                                 ▼
                                      SQLite (WAL) jobs table  ◀──────────────┐
                                                 │ claim_next (lease)          │ mark_delivered / mark_failed /
                                                 ▼                             │ schedule_retry (lease-guarded)
                                      JobWorker × N (asyncio, same process) ───┘
                                                 │
                                                 ▼
                                      VeritasAgentAdapter ──▶ agent.core.orchestrator.VeritasAgent.run()
                                                                (Antigravity's agent, in-process, unmodified)
```

## Components

| Module | Responsibility |
| :--- | :--- |
| `backend/app/api.py` | Seller endpoints, auth, validation, response shaping |
| `backend/app/store.py` | Durable job table, idempotency, leased queue, guarded transitions |
| `backend/app/worker.py` | Worker pool: claim → run adapter → deliver / retry / fail |
| `backend/app/adapter.py` | The only code that touches the agent: input mapping, timeout, output validation, outcome classification |
| `backend/app/main.py` | App wiring, lifespan, health, body limits, error envelopes |
| `backend/app/logging_setup.py` | Logging with credential redaction |
| `backend/app/config.py` | Environment configuration |

The backend contains **no research logic**. It never searches, fetches, evaluates sources or writes report text. All of that is the agent's.

## Agent invocation

Verified against `docs/AGENT_HANDOFF.md` §2.1 and the code. The agent is a Python package imported in-process: `await VeritasAgent().run(ResearchBriefInput(brief, depth, max_sources))` returns `ResearchReportOutput`. There is no remote endpoint and no credential. It runs wherever the backend runs, and needs outbound HTTPS to fetch sources. Agent identity (`veritas-research-agent` / `1.0.0`) is read from `agent/agent_manifest.json` and stored on every job.

## Job lifecycle

```
queued ──claim──▶ running ──▶ delivered
   ▲                │  └────▶ failed
   └──retry/backoff─┘  (retryable error and attempts < max_attempts)
```

- **Claim:** one `BEGIN IMMEDIATE` transaction selects the oldest runnable job (`queued` and due, or `running` with an expired lease), increments `attempts`, and sets a random `lease_token` and `lease_expires_at`.
- **Finish:** every update out of `running` is `WHERE status='running' AND lease_token=?`. A worker whose lease expired gets `LeaseLost`, and its result is discarded, so a job is delivered at most once.
- **Recovery:** after a crash or restart, jobs left `running` become claimable when their lease expires (`VERITAS_LEASE_SECONDS`, longer than the agent timeout). Jobs out of attempts are failed with `RESEARCH_TIMEOUT`.
- **Retries:** timeouts and unexpected agent exceptions are re-queued with linear backoff (`VERITAS_RETRY_BACKOFF_SECONDS × attempt`). Clarification requests, agent-reported failures and invalid output fail immediately.
- A `CHECK` constraint restricts `status` to the four contract values.

## Database

Single SQLite file in WAL mode (`VERITAS_DB_PATH`). Table `jobs`:

| Column | Purpose |
| :--- | :--- |
| `job_id` (PK) | `veritas-job-<uuid4 hex>` |
| `order_id` (UNIQUE), `idempotency_key` (UNIQUE), `request_hash` | Order safety and idempotency |
| `brief` | Buyer brief (never logged) |
| `status`, `attempts`, `max_attempts`, `available_at` | Queue state |
| `lease_token`, `lease_expires_at` | Crash-safe ownership |
| `outcome`, `report`, `sources_json`, `source_details_json`, `limitations_json`, `clarification_json`, `retrieved_at` | Agent result |
| `error_code`, `error_message` | Public failure info only |
| `agent_id`, `agent_version`, timestamps | Traceability |

**Why SQLite:** one durable file with transactional claims is enough for a single-host deployment, and it matches the repository's existing plan (handoff §6). The store is the only module that touches SQL. A multi-host deployment would swap it for Postgres (`SELECT … FOR UPDATE SKIP LOCKED`) with the same interface.

## needs_clarification

HireCrew's contract has no clarification state, so an agent result of `needs_clarification` becomes a `failed` job with code `CLARIFICATION_REQUIRED`. The agent's `clarificationQuestions` and `limitations` are included in the response. The buyer isn't charged for research that did not happen and can resubmit a clarified brief. The job is never presented as delivered.
