"""
VERITAS: Reliability, Sparse Evidence & Error Recovery Test Suite
"""

import unittest
import asyncio
from agent.schemas.input import ResearchBriefInput
from agent.schemas.output import ResearchStatus
from agent.core.orchestrator import VeritasAgent
from agent.tools.llm_client import LLMUnavailable
from agent.tools.search_engine import SearchResultItem
from tests.agent_tests.fakes import FakeLLM, FakeScraper, FakeSearchEngine, page_text


class DownLLM(FakeLLM):
    async def chat(self, system, user, max_tokens=3000):
        raise LLMUnavailable("down")

    async def chat_list(self, system, user, max_tokens=2000):
        raise LLMUnavailable("down")


class TestVeritasReliability(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.loop.close()

    def run_agent(self, agent, brief):
        return self.loop.run_until_complete(agent.run(ResearchBriefInput(brief=brief)))

    def test_inaccessible_page_recovery(self):
        good = "https://docs.alpha.example/"
        llm = FakeLLM(official_urls=["https://failing-domain.example/", good])
        agent = VeritasAgent(scraper=FakeScraper({good: page_text("Alpha")}), search_engine=FakeSearchEngine(llm), llm=llm)
        result = self.run_agent(agent, "Describe the Alpha runner tools and their limits.")

        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        self.assertFalse(any("failing-domain" in s.url for s in result.sources))
        self.assertEqual([s.url for s in result.sources], [good])

    def test_zero_evidence_never_claims_success(self):
        llm = FakeLLM(official_urls=["https://nothing.example/"], queries=["obscure framework"])
        agent = VeritasAgent(scraper=FakeScraper({}), search_engine=FakeSearchEngine(llm), llm=llm)
        result = self.run_agent(agent, "Analyze architecture of obscure-nonexistent-framework-xyz.")

        self.assertEqual(result.status, ResearchStatus.FAILED)
        self.assertEqual(result.sources, [])
        self.assertIsNone(result.report)
        self.assertEqual(result.error, "NO_EVIDENCE_RETRIEVED")

    def test_news_results_supplement_thin_evidence(self):
        llm = FakeLLM(official_urls=[], queries=["topic news"])
        news = SearchResultItem(title="Headline", url="https://news.example/item", provider="news",
                                snippet="News headline: Headline\nPublisher: Example\nPublished: today\nSummary text.")
        agent = VeritasAgent(scraper=FakeScraper({}), search_engine=FakeSearchEngine(llm, [news]), llm=llm)
        result = self.run_agent(agent, "What happened with the topic in the news this week?")

        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        self.assertEqual([s.url for s in result.sources], ["https://news.example/item"])

    def test_uncited_synthesis_still_lists_every_source(self):
        url = "https://docs.alpha.example/"
        llm = FakeLLM(official_urls=[url], cite=False)
        agent = VeritasAgent(scraper=FakeScraper({url: page_text("Alpha")}), search_engine=FakeSearchEngine(llm), llm=llm)
        result = self.run_agent(agent, "Describe the Alpha product configuration options in detail.")
        # The ignored page gets its own extraction, so it is cited rather than silently dropped.
        self.assertIn("## Supplementary Evidence", result.report)
        self.assertIn(f"Source: {url}", result.report)
        self.assertEqual([s.url for s in result.sources], [url])

    def test_language_model_outage_raises_for_retry(self):
        llm = DownLLM()
        agent = VeritasAgent(scraper=FakeScraper({}), search_engine=FakeSearchEngine(llm), llm=llm)
        with self.assertRaises(LLMUnavailable):
            self.run_agent(agent, "Describe the Alpha product configuration options in detail.")


if __name__ == "__main__":
    unittest.main()
