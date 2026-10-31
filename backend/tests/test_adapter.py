"""Agent adapter tests (fake runners) plus a real-agent invocation smoke test."""

import asyncio
import unittest

from agent.schemas.output import ResearchReportOutput, ResearchStatus
from app.adapter import (AgentInvocationError, AgentOutputInvalid, AgentReportedFailure, AgentTimeout,
                         ClarificationRequired, VeritasAgentAdapter)
from tests.helpers import runner_raising, runner_returning, runner_sleeping, source, success_output


def run(adapter, brief="Compare two products with citations."):
    return asyncio.run(adapter.run(brief))


class TestAdapter(unittest.TestCase):
    def adapter(self, runner, timeout=5):
        return VeritasAgentAdapter(timeout_seconds=timeout, runner=runner)

    def test_successful_invocation_preserves_report_and_sources(self):
        out = success_output(sources=[source("https://a.example/x", "A"), source("https://b.example/y", "B")])
        r = run(self.adapter(runner_returning(out)))
        self.assertEqual(r.outcome, "success")
        self.assertEqual(r.report, out.report)
        self.assertEqual(r.sources, [{"title": "A", "url": "https://a.example/x"},
                                     {"title": "B", "url": "https://b.example/y"}])
        self.assertEqual(r.source_details[0]["evidenceSnippet"], "snippet")
        self.assertEqual(r.limitations, ["gap A"])
        self.assertEqual(r.retrieved_at, out.retrievedAt)
        self.assertEqual((r.agent_id, r.agent_version), ("veritas-research-agent", "1.1.0"))

    def test_input_mapping_uses_agent_schema(self):
        seen = {}

        async def capture(payload):
            seen["payload"] = payload
            return success_output()

        run(VeritasAgentAdapter(timeout_seconds=5, depth="quick", max_sources=4, runner=capture), "Brief goes here")
        p = seen["payload"]
        self.assertEqual((p.brief, p.depth.value, p.max_sources), ("Brief goes here", "quick", 4))

    def test_clarification_required(self):
        out = ResearchReportOutput(status=ResearchStatus.NEEDS_CLARIFICATION, retrievedAt="t",
                                   clarificationQuestions=["Which workload?"], limitations=["ambiguous"])
        with self.assertRaises(ClarificationRequired) as ctx:
            run(self.adapter(runner_returning(out)))
        self.assertEqual(ctx.exception.questions, ["Which workload?"])
        self.assertFalse(ctx.exception.retryable)

    def test_agent_reported_failure(self):
        out = ResearchReportOutput(status=ResearchStatus.FAILED, retrievedAt="t", error="internal detail")
        with self.assertRaises(AgentReportedFailure) as ctx:
            run(self.adapter(runner_returning(out)))
        self.assertNotIn("internal detail", ctx.exception.public_message)

    def test_timeout_is_retryable(self):
        with self.assertRaises(AgentTimeout) as ctx:
            run(self.adapter(runner_sleeping(2), timeout=0.05))
        self.assertTrue(ctx.exception.retryable)

    def test_agent_exception_is_wrapped_without_details(self):
        with self.assertRaises(AgentInvocationError) as ctx:
            run(self.adapter(runner_raising(RuntimeError("secret=abc123 stack info"))))
        self.assertTrue(ctx.exception.retryable)
        self.assertNotIn("abc123", str(ctx.exception))

    def test_authentication_style_failure_from_agent_is_not_leaked(self):
        # The agent needs no credentials today; if a future provider rejects a key,
        # the error must surface only as a generic invocation failure.
        with self.assertRaises(AgentInvocationError) as ctx:
            run(self.adapter(runner_raising(PermissionError("401 invalid api key sk_live_123"))))
        self.assertNotIn("sk_live", ctx.exception.public_message + str(ctx.exception))

    def test_invalid_output_type(self):
        with self.assertRaises(AgentOutputInvalid):
            run(self.adapter(runner_returning({"status": "success"})))

    def test_success_without_report_is_invalid(self):
        with self.assertRaises(AgentOutputInvalid):
            run(self.adapter(runner_returning(success_output(report="  "))))

    def test_success_with_zero_sources_is_not_delivered(self):
        with self.assertRaises(AgentOutputInvalid) as ctx:
            run(self.adapter(runner_returning(success_output(sources=[]))))
        self.assertEqual(ctx.exception.code, "NO_EVIDENCE_RETRIEVED")

    def test_agent_no_evidence_failure_maps_to_no_evidence_code(self):
        out = ResearchReportOutput(status=ResearchStatus.FAILED, retrievedAt="t", error="NO_EVIDENCE_RETRIEVED")
        with self.assertRaises(AgentOutputInvalid) as ctx:
            run(self.adapter(runner_returning(out)))
        self.assertEqual(ctx.exception.code, "NO_EVIDENCE_RETRIEVED")
        self.assertFalse(ctx.exception.retryable)

    def test_non_http_source_url_is_invalid(self):
        with self.assertRaises(AgentOutputInvalid):
            run(self.adapter(runner_returning(success_output(sources=[source("javascript:alert(1)")]))))


class TestRealAgentInvocation(unittest.TestCase):
    def test_real_agent_returns_schema_valid_output(self):
        """Invokes the actual Antigravity agent (no fakes) and checks the contract round-trips."""
        adapter = VeritasAgentAdapter(timeout_seconds=120)
        output = asyncio.run(adapter.runner(adapter.build_input("Hello world research brief")))
        self.assertIsInstance(output, ResearchReportOutput)


if __name__ == "__main__":
    unittest.main()
