"""
Adapter between the seller backend and the Antigravity-built VERITAS agent.

Invocation is the agent's documented in-process Python contract
(docs/AGENT_HANDOFF.md section 2.1):

    result = await VeritasAgent().run(ResearchBriefInput(brief=..., depth=..., max_sources=...))

The adapter does no research of its own. It maps the seller brief onto the agent's
input schema, enforces a timeout, validates the agent's output, and classifies the
outcome for the worker:

  success + report + >=1 source  -> AdapterResult(outcome="success")
  needs_clarification            -> ClarificationRequired (job fails with CLARIFICATION_REQUIRED;
                                    questions are returned to the buyer, nothing is charged as delivered)
  success with no sources        -> AgentOutputInvalid(NO_EVIDENCE_RETRIEVED)
  failed                         -> AgentReportedFailure (not retried)
  timeout / unexpected exception -> AgentTimeout / AgentInvocationError (retried by the worker)
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    # Appended (not prepended) so the repo-root `tests/` package never shadows backend modules.
    sys.path.append(_REPO_ROOT)

from agent.core.orchestrator import VeritasAgent  # noqa: E402
from agent.schemas.input import ResearchBriefInput, ResearchDepth  # noqa: E402
from agent.schemas.output import ResearchReportOutput, ResearchStatus  # noqa: E402

_MANIFEST_PATH = os.path.join(_REPO_ROOT, "agent", "agent_manifest.json")


def load_agent_identity() -> Dict[str, str]:
    with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return {"agent_id": manifest["agent_id"], "version": manifest["version"]}


# ----------------------------------------------------------------- outcomes


class AdapterError(Exception):
    code = "RESEARCH_EXECUTION_FAILED"
    retryable = False
    public_message = "The research job could not be completed."


class AgentTimeout(AdapterError):
    code = "RESEARCH_TIMEOUT"
    retryable = True
    public_message = "The research agent did not finish within the time limit."


class AgentInvocationError(AdapterError):
    code = "RESEARCH_EXECUTION_FAILED"
    retryable = True


class AgentReportedFailure(AdapterError):
    code = "RESEARCH_EXECUTION_FAILED"
    retryable = False


class AgentOutputInvalid(AdapterError):
    code = "INVALID_AGENT_OUTPUT"
    retryable = False
    public_message = "The research agent returned an unusable result."

    def __init__(self, detail: str, code: Optional[str] = None, public_message: Optional[str] = None):
        super().__init__(detail)
        if code:
            self.code = code
        if public_message:
            self.public_message = public_message


class ClarificationRequired(AdapterError):
    code = "CLARIFICATION_REQUIRED"
    retryable = False
    public_message = "The brief is too ambiguous to research reliably. Please resubmit with the details requested."

    def __init__(self, questions: List[str], limitations: List[str]):
        super().__init__("needs_clarification")
        self.questions = questions
        self.limitations = limitations


@dataclass
class AdapterResult:
    outcome: str
    report: str
    sources: List[Dict[str, Any]]
    limitations: List[str]
    clarification_questions: List[str]
    retrieved_at: str
    agent_id: str
    agent_version: str
    source_details: List[Dict[str, Any]] = field(default_factory=list)


AgentRunner = Callable[[ResearchBriefInput], Awaitable[ResearchReportOutput]]


async def _default_runner(payload: ResearchBriefInput) -> ResearchReportOutput:
    return await VeritasAgent().run(payload)


class VeritasAgentAdapter:
    def __init__(
        self,
        timeout_seconds: float,
        depth: str = "standard",
        max_sources: int = 10,
        runner: Optional[AgentRunner] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.depth = ResearchDepth(depth)
        self.max_sources = max_sources
        self.runner = runner or _default_runner
        self.identity = load_agent_identity()

    def build_input(self, brief: str) -> ResearchBriefInput:
        return ResearchBriefInput(brief=brief, depth=self.depth, max_sources=self.max_sources)

    async def run(self, brief: str) -> AdapterResult:
        payload = self.build_input(brief)
        try:
            output = await asyncio.wait_for(self.runner(payload), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as e:
            raise AgentTimeout("agent timed out") from e
        except AdapterError:
            raise
        except Exception as e:  # the agent raised; keep only the type for logs
            raise AgentInvocationError(f"agent raised {type(e).__name__}") from e
        return self._validate(output)

    def _validate(self, output: Any) -> AdapterResult:
        if not isinstance(output, ResearchReportOutput):
            try:
                output = ResearchReportOutput.model_validate(output)
            except Exception as e:
                raise AgentOutputInvalid(f"output failed schema validation: {type(e).__name__}") from e

        if output.status == ResearchStatus.NEEDS_CLARIFICATION:
            questions = [q for q in output.clarificationQuestions if isinstance(q, str) and q.strip()]
            raise ClarificationRequired(questions, list(output.limitations))

        if output.status == ResearchStatus.FAILED:
            if output.error == "NO_EVIDENCE_RETRIEVED":
                raise AgentOutputInvalid(
                    "agent retrieved no evidence",
                    code="NO_EVIDENCE_RETRIEVED",
                    public_message="No public evidence could be retrieved for this brief, so no report was delivered.",
                )
            raise AgentReportedFailure("agent reported status=failed")

        if not output.report or not output.report.strip():
            raise AgentOutputInvalid("success without a report")

        details, sources = [], []
        for s in output.sources:
            parsed = urlparse(s.url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise AgentOutputInvalid("source with a non-HTTP(S) URL")
            details.append(s.model_dump(mode="json"))
            # HireCrew validates sources strictly as {title, url}.
            sources.append({"title": (s.title or s.url)[:500], "url": s.url[:2048]})

        if not sources:
            raise AgentOutputInvalid(
                "success with zero sources",
                code="NO_EVIDENCE_RETRIEVED",
                public_message="No public evidence could be retrieved for this brief, so no report was delivered.",
            )

        return AdapterResult(
            outcome="success",
            report=output.report,
            sources=sources,
            source_details=details,
            limitations=list(output.limitations),
            clarification_questions=[],
            retrieved_at=output.retrievedAt,
            agent_id=self.identity["agent_id"],
            agent_version=self.identity["version"],
        )
