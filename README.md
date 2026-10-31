# VERITAS
## Verified Web Research Agent (Phase 1)
### Source-Grounded Intelligence for the HireCrew Marketplace

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)
[![Status](https://img.shields.io/badge/Status-Handoff%20Ready-success.svg)](#claude-phase-2-handoff)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)

VERITAS is an autonomous research agent engineered for the **HireCrew Marketplace** (`https://hirecrew.si`). It accepts a buyer's research brief, investigates the subject using publicly verifiable web evidence, rigorously assesses the reliability and provenance of information, and synthesizes a concise, source-grounded research report.

---

## The Central Axiom

> **EVERY MATERIAL FACTUAL CLAIM MUST BE SUPPORTED BY IDENTIFIABLE EVIDENCE.**  
> **VERITAS MUST NEVER INVENT FACTS, SOURCES, QUOTATIONS, STATISTICS, DATES, OR URLS.**

---

## Research Workflow Architecture

VERITAS executes a structured 8-stage research process:

1. **Stage 1 — Brief Interpretation & Ambiguity Audit**:
   - Parses the request, extracting entities, technical requirements, and constraints.
   - Detects ambiguous briefs (e.g. *"Compare it"*) and halts with `status="needs_clarification"` rather than guessing.
2. **Stage 2 — Research Planning**:
   - Decomposes the research request into targeted sub-inquiries.
   - Targets primary vendor docs, peer-reviewed ArXiv papers, and official specifications.
3. **Stage 3 — Source Discovery**:
   - Queries web search engines, filtering out link farms and SEO blogs.
   - Flags primary authority domains (`arxiv.org`, `openai.com`, `docs.github.com`, `nodejs.org`).
4. **Stage 4 — Secure Evidence Extraction**:
   - Fetches full webpage text while rejecting private subnets / cloud metadata (SSRF defense).
   - Excises HTML comments and neutralizes indirect prompt injections (e.g. `SYSTEM OVERRIDE`).
   - Wraps external content in defensive `[UNTRUSTED DATA]` containers.
5. **Stage 5 — Verification & Conflict Analysis**:
   - Cross-checks factual claims across independent sources.
   - Flags discrepancies, explains what each source asserts, and explicitly logs evidence gaps.
6. **Stage 6 — Report Synthesis**:
   - Formulates the mandatory 6-section report structure with Markdown comparison tables.
7. **Stage 7 — Quality Assurance & Citation Audit**:
   - Verifies that every citation URL appears in inspected source records with exact links.
8. **Stage 8 — Structured Output Delivery**:
   - Emits a typed `ResearchReportOutput` JSON schema.

---

## Mandatory Report Format

Every completed research report conforms to the following standardized structure:

```markdown
# Research Report: [Topic]

**Research date:** [UTC timestamp]
**Research scope:** [Brief description]

## 1. Executive Summary
A concise direct answer to the buyer's request.

## 2. Key Findings
Evidence-backed findings, with exact source URLs beside material claims.

## 3. Detailed Analysis
Relevant explanation, comparisons, supporting evidence, and trade-offs.

## 4. Comparison
(Structured Markdown table when comparing options or systems).

## 5. Limitations and Uncertainties
Clearly identifies missing, conflicting, outdated, or inconclusive evidence.

## 6. Conclusion
A direct conclusion based on the available evidence.

## Sources
Numbered list of verified sources with Title, Publisher, Exact URL, and UTC Retrieval Date.
```

---

## Quickstart & Invocation

### 1. Installation
```bash
git clone https://github.com/Swapnil-Biswas/Veritas.git
cd Veritas
pip install -r requirements.txt
```

### 2. Python Invocation Example
```python
import asyncio
from agent.schemas.input import ResearchBriefInput, ResearchDepth
from agent.core.orchestrator import VeritasAgent

async def main():
    agent = VeritasAgent()
    brief_input = ResearchBriefInput(
        brief="Compare GitHub Actions, GitLab CI/CD, and CircleCI for self-hosted runners.",
        depth=ResearchDepth.STANDARD
    )
    result = await agent.run(brief_input)

    print("Execution Status:", result.status)
    print("\nReport Markdown:\n", result.report)
    print("\nInspected Sources:", len(result.sources))

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Running Verification Tests

The agent tests run offline: the network and the language model are replaced by deterministic fakes, so they exercise the real orchestration (planning, fetching, citation handling, failure paths).

```bash
# Agent: 22 tests
python -m unittest discover tests

# Seller backend
cd backend && python -m unittest discover -s tests -t .
```

### Test Coverage Highlights
- Reports are built only from pages actually retrieved for the brief; every listed source is cited.
- Comparisons plan official pages per named option; brief URLs are fetched and "only evidence" restrictions are honoured.
- Unspecified recommendations list the missing constraints and clarification questions; empty briefs get `needs_clarification`.
- Zero retrieved evidence returns `failed` (`NO_EVIDENCE_RETRIEVED`), never a verified-looking report.
- The SSRF barrier blocks private, CGNAT, link-local and IPv4-mapped addresses and re-checks every redirect hop.
- Injection text (hidden comments, task overrides, marker/secret requests) is flagged and never followed.

---

## Repository Structure

```
veritas/
├── agent/
│   ├── core/
│   │   ├── orchestrator.py        # VeritasAgent multi-stage research coordinator
│   │   ├── evidence_verifier.py   # Claim extraction, conflict analysis, and evidence gap tracker
│   │   └── report_builder.py      # Mandatory 6-section report assembler & citation auditor
│   ├── prompts/
│   │   ├── system.py              # Master VERITAS system prompt & non-negotiable rules
│   │   └── workflow_prompts.py    # Brief interpretation, planning, and evaluation templates
│   ├── schemas/
│   │   ├── input.py               # ResearchBriefInput schema
│   │   ├── output.py              # ResearchReportOutput schema
│   │   ├── source.py              # SourceRecord & citation schema
│   │   ├── input_schema.json      # Machine-readable JSON input schema
│   │   └── output_schema.json     # Machine-readable JSON output schema
│   ├── tools/
│   │   ├── security_barrier.py    # SSRF validator & prompt injection sanitizer
│   │   ├── web_scraper.py         # Async HTTP scraper with reader extraction
│   │   └── search_engine.py       # Source discovery engine targeting primary authority domains
│   ├── workflows/
│   │   └── state.py               # ResearchState telemetry ledger and state machine
│   └── agent_manifest.json        # Subagent registration & capability manifest
├── tests/
│   └── agent/
│       ├── test_functional.py     # Multi-source, temporal, and citation tests
│       ├── test_security.py       # SSRF, HTML comment, and indirect prompt injection tests
│       └── test_reliability.py    # Inaccessible URLs and sparse evidence tests
├── docs/
│   ├── AGENT_HANDOFF.md           # Comprehensive Claude Phase 2 handoff specification
│   ├── architecture/
│   │   ├── RESEARCH_WORKFLOW.md   # State machine, pipeline diagram, and stages
│   │   └── EVIDENCE_MODEL.md      # Authority hierarchy and conflict handling protocols
├── .env.example                   # Environment configuration template
├── .gitignore                     # Git ignore rules
└── requirements.txt               # Production Python dependencies
```

---

## Claude Phase 2 Handoff

Phase 1 construction, testing, and GitHub synchronization are complete. Complete handoff details for building the HireCrew seller API, job database, and deployment manifest are documented in:

👉 [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md)


---

## Phase 2 — Seller Backend (HireCrew)

A HireCrew `seller-hosted-api-v1` backend wraps the agent above. It runs the agent unmodified, in-process, through `backend/app/adapter.py`.

> **Status:** the backend is complete and tested. HireCrew benchmarking and listing are **paused** because of agent defects found in Phase 2 (search not implemented, pre-written answers). See [`docs/PHASE2_AGENT_DEFECTS.md`](docs/PHASE2_AGENT_DEFECTS.md).

```bash
pip install -r backend/requirements.txt
python backend/run_server.py            # http://127.0.0.1:8020  (POST /jobs, GET /jobs/{id}, GET /health)

cd backend
cd backend && python -m unittest discover -s tests -t .           # 56 tests (unit, integration, reliability, security)
VERITAS_LIVE_E2E=1 python -m unittest tests.test_e2e_live        # real agent, real network, no mocks
```

| Document | Contents |
| :--- | :--- |
| [docs/API.md](docs/API.md) | Endpoints, payloads, error codes, idempotency |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, job lifecycle, database, agent invocation |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Tailscale Funnel and container deployment, operations |
| [docs/SECURITY.md](docs/SECURITY.md) | Auth, validation, logging, secret handling |
| [docs/HIRECREW_INTEGRATION.md](docs/HIRECREW_INTEGRATION.md) | Contract, seller MCP workflow, current status |
