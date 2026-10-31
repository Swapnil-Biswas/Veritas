"""
VERITAS: Reliability, Sparse Evidence & Error Recovery Test Suite
"""

import unittest
import asyncio
from agent.schemas.input import ResearchBriefInput
from agent.schemas.output import ResearchStatus
from agent.core.orchestrator import VeritasAgent
from agent.tools.web_scraper import WebScraper, PageExtractionResult
from agent.tools.search_engine import WebSearchEngine, SearchResultItem
from agent.tools.security_barrier import SanitizedContent


class MockFailingScraper(WebScraper):
    """Scraper that simulates intermittent network failures and 404/500 errors."""
    async def fetch_page(self, url: str) -> PageExtractionResult:
        if "failing-domain.com" in url:
            return PageExtractionResult(
                url=url,
                title="Internal Server Error",
                retrieved_at="2026-10-31T00:00:00Z",
                sanitized_content=SanitizedContent(clean_text=""),
                status_code=500,
                is_accessible=False,
                error="HTTP 500 Internal Server Error"
            )
        return await super().fetch_page(url)


class MockSparseSearchEngine(WebSearchEngine):
    """Search engine simulating sparse or empty search results."""
    async def search(self, query: str, limit: int = 8):
        if "obscure-nonexistent-framework-xyz" in query:
            return []
        return await super().search(query, limit)


class TestVeritasReliability(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.loop.close()

    def test_inaccessible_page_recovery(self):
        scraper = MockFailingScraper()
        agent = VeritasAgent(scraper=scraper)

        brief = "Compare GitHub Actions and failing-domain.com runner tools."
        input_data = ResearchBriefInput(brief=brief)
        result = self.loop.run_until_complete(agent.run(input_data))

        # Must not crash; must complete successfully with accessible sources
        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        self.assertIsNotNone(result.report)
        # The failing domain must not be listed as an inspected source
        self.assertFalse(any("failing-domain.com" in s.url for s in result.sources))

    def test_sparse_evidence_reporting(self):
        engine = MockSparseSearchEngine()
        agent = VeritasAgent(search_engine=engine)

        brief = "Analyze architecture of obscure-nonexistent-framework-xyz."
        input_data = ResearchBriefInput(brief=brief)
        result = self.loop.run_until_complete(agent.run(input_data))

        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        # Limitations section must explicitly communicate sparse or missing evidence
        self.assertIn("## 5. Limitations and Uncertainties", result.report)


if __name__ == "__main__":
    unittest.main()
