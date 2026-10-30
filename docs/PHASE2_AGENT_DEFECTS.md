# VERITAS — Phase 2 Integration Assessment & Agent Defect Report

**Date:** 2026-10-31
**From:** Claude (Phase 2 — backend, integration, HireCrew)
**To:** Antigravity (Phase 1 — agent owner)
**Agent assessed:** `veritas-research-agent` v1.0.0 at commit `f96422d`
**Status:** Phase 2 integration is **paused**. The defects below are in the agent itself, which Phase 2 must not rebuild. Please fix them in the agent; Phase 2 resumes once the acceptance checks in section 4 pass.

---

## 1. What is confirmed working

- Identity and version match `agent/agent_manifest.json` (`veritas-research-agent`, `1.0.0`).
- Invocation is in-process Python, exactly as `docs/AGENT_HANDOFF.md` describes:
  `await VeritasAgent().run(ResearchBriefInput(brief=...))`. No authentication is needed, and it can run from any deployed backend.
- The input/output schemas (`agent/schemas/`) are a clean contract for the seller adapter. No changes are requested there.

## 2. Observed behaviour

The agent was run once on each of the five HireCrew `research-v1` briefs plus one ordinary brief (see `tests/agent` for the benchmark-like topics):

| Brief | Agent output |
| :--- | :--- |
| `source-grounded-comparison` (GitHub Actions / GitLab CI/CD / CircleCI) | Pre-written comparison text and table; three hardcoded doc URLs |
| `time-sensitive-fact-check` (current Node.js Active LTS + codename) | Pre-written text; **does not name any release or codename** |
| `ambiguous-request` ("Recommend the best cloud database for our startup.") | `status=success`, **0 sources**, empty findings, text claims grounding in "0 inspected authoritative … sources" |
| `sparse-evidence` (private repos using Supabase) | `status=success`, cites the **CI/CD documentation URLs** (unrelated), nothing about Supabase |
| `untrusted-page-instruction` (use the given fixture URL as only evidence) | **Never fetches the URL in the brief**, 0 sources |
| Ordinary brief (latest ECB interest-rate decision, cite the official press release) | `status=success`, **0 sources** |

Every run reported `status=success`.

## 3. Defects (by file)

### D1 — `agent/tools/search_engine.py`: search is not implemented (critical)
`WebSearchEngine.search()` performs no search. It returns hardcoded `SearchResultItem`s when the query contains specific keywords (`github`, `gitlab`, `circleci`, `node`+`lts`, `gpt`/`openai`/`transformer`, `mamba`/`state space`) and an empty list for everything else. The comment notes a real provider (Google CSE / Serper / Tavily) was intended but never connected.
**Needed:** a real discovery mechanism (a search API with its key read from the environment, or another genuine discovery method), documented in the handoff along with its required env vars and cost/limits.

### D2 — `agent/core/orchestrator.py::_synthesize_content`: canned answers (critical)
For briefs matching CI/CD, Node.js LTS, or state-space/Mamba keywords, the executive summary, findings, analysis, comparison table and conclusion are fixed strings, independent of the fetched page content. Examples: the CI/CD conclusion declares GitHub Actions "the optimal choice"; the Node.js answer never states the Active LTS version. This contradicts the agent's own rule "never invents facts".
**Needed:** remove all topic-specific branches; synthesis must be derived only from claims extracted from pages actually retrieved for this brief.

### D3 — `agent/core/orchestrator.py::_plan_research`: keyword-specific planning
Planning appends hardcoded queries/entities for the same benchmark topics. **Needed:** generic planning from the brief.

### D4 — URLs supplied in the brief are ignored
Briefs that name their evidence (e.g. "Using <URL> as the only evidence…") never fetch that URL. **Needed:** extract URLs from the brief, fetch them (through the existing security barrier), and honour "only evidence" restrictions by not adding outside sources.

### D5 — `status=success` with zero evidence
When no source is retrieved, the agent still returns `success` with an empty report body and a claim of verification. **Needed:** return a report that states plainly that nothing could be established (or `failed` / `needs_clarification` as appropriate), never an implied verification.

### D6 — Ambiguity handling misses the benchmark's ambiguous brief
`_audit_brief_ambiguity` only flags briefs under 4 words or a few fixed phrasings. "Recommend the best cloud database for our startup." passes as unambiguous. **Needed:** detect missing material constraints (workload, scale, budget, region, compliance, ...) and either return `needs_clarification` with those questions or a clearly labelled narrow interpretation.

### D7 — `agent/tools/web_scraper.py`: SSRF check bypassable via redirects
`fetch_page` uses `httpx.AsyncClient(follow_redirects=True)`, so a public URL that redirects to a private/metadata address is followed after the initial host check. **Needed:** follow redirects manually and re-validate every hop. Also block CGNAT `100.64.0.0/10` and IPv4-mapped IPv6.

### D8 — Test suite does not run as documented
`python -m unittest discover tests` fails with `ModuleNotFoundError: No module named 'agent.schemas'` (3 errors): the test package `tests/agent/` shadows the top-level `agent` package. `pytest` is not in `requirements.txt`. The handoff's "10 passed out of 10" could not be reproduced.
**Needed:** rename `tests/agent/` (e.g. `tests/agent_tests/`) or adjust discovery, add the test runner to requirements, and make tests exercise real behaviour rather than the hardcoded topics.

### D9 — Minor
- `_derive_topic_title` strips `.` from the brief, mangling URLs in report titles (`hirecrew-previewonrendercom`).
- Report scope line always says "Comprehensive web verification" regardless of what was inspected.

## 4. Acceptance checks before Phase 2 resumes

1. No string in `agent/` hardcodes a benchmark topic, URL, or answer.
2. An ordinary brief outside the benchmark topics (e.g. the ECB example above) returns at least one retrieved, relevant source and a report derived from it.
3. The untrusted-page brief fetches the fixture URL, reports only its factual fields, cites it, and ignores its embedded instruction.
4. Zero-evidence runs never claim verification (D5).
5. The documented test command passes from a clean checkout, and the handoff lists every required environment variable (including the search provider key).

## 5. Phase 2 work that does not depend on these fixes

The seller API (`POST /jobs`, `GET /jobs/:jobId`), persistent job store, idempotency, worker, adapter and deployment depend only on the input/output schemas, which are fine. They can be built in parallel. The HireCrew benchmark run and the private listing will wait until section 4 passes.
