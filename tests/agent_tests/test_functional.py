"""
VERITAS: Functional & Citation Verification Test Suite
"""

import unittest
import asyncio
from agent.schemas.input import ResearchBriefInput, ResearchDepth
from agent.schemas.output import ResearchStatus
from agent.core.orchestrator import VeritasAgent


class TestVeritasFunctional(unittest.TestCase):

    def setUp(self):
        self.agent = VeritasAgent()
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.loop.close()

    def test_multi_source_comparison(self):
        brief = (
            "Compare GitHub Actions, GitLab CI/CD, and CircleCI for running automated test suites "
            "in a small private repository. Cover self-hosted runner support and one documented constraint."
        )
        input_data = ResearchBriefInput(brief=brief, depth=ResearchDepth.STANDARD)
        result = self.loop.run_until_complete(self.agent.run(input_data))

        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        self.assertIsNotNone(result.report)
        self.assertGreaterEqual(len(result.sources), 3)

        # Check required sections
        self.assertIn("## 1. Executive Summary", result.report)
        self.assertIn("## 2. Key Findings", result.report)
        self.assertIn("## 3. Detailed Analysis", result.report)
        self.assertIn("## 4. Comparison", result.report)
        self.assertIn("## 5. Limitations and Uncertainties", result.report)
        self.assertIn("## 6. Conclusion", result.report)
        self.assertIn("## Sources", result.report)

        # Check citation integrity: every source in sources list must be present in report
        for src in result.sources:
            self.assertIn(src.url, result.report, f"Source URL {src.url} must appear in report body.")

    def test_time_sensitive_fact_check(self):
        brief = "Identify the current Node.js Active LTS release status and version release schedule."
        input_data = ResearchBriefInput(brief=brief)
        result = self.loop.run_until_complete(self.agent.run(input_data))

        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        self.assertIn("Node.js", result.report)
        self.assertIn("Active LTS", result.report)
        self.assertIn("https://nodejs.org/en/about/previous-releases", result.report)

    def test_ambiguous_brief_clarification(self):
        # Fundamentally ambiguous query lacking entities
        brief = "Compare it."
        input_data = ResearchBriefInput(brief=brief)
        result = self.loop.run_until_complete(self.agent.run(input_data))

        self.assertEqual(result.status, ResearchStatus.NEEDS_CLARIFICATION)
        self.assertIsNone(result.report)
        self.assertGreaterEqual(len(result.clarificationQuestions), 1)
        self.assertTrue(any("specify" in q.lower() or "entity" in q.lower() for q in result.clarificationQuestions))

    def test_citation_authenticity(self):
        brief = "State-space models vs transformers computational complexity."
        input_data = ResearchBriefInput(brief=brief)
        result = self.loop.run_until_complete(self.agent.run(input_data))

        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        # Verify no fabricated URLs
        for src in result.sources:
            self.assertTrue(src.url.startswith("http://") or src.url.startswith("https://"))
            self.assertTrue("arxiv.org" in src.url or "openai.com" in src.url)


if __name__ == "__main__":
    unittest.main()
