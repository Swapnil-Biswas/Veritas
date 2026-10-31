"""
VERITAS: Functional & Citation Verification Test Suite
"""

import unittest
import asyncio
from agent.schemas.input import ResearchBriefInput
from agent.schemas.output import ResearchStatus
from agent.core.orchestrator import VeritasAgent
from agent.tools.search_engine import WebSearchEngine
from tests.agent_tests.fakes import FakeLLM, FakeScraper, FakeSearchEngine, page_text


def build_agent(pages, **llm_kwargs):
    llm = FakeLLM(**llm_kwargs)
    scraper = FakeScraper(pages)
    return VeritasAgent(scraper=scraper, search_engine=FakeSearchEngine(llm), llm=llm), scraper, llm


class TestVeritasFunctional(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.loop.close()

    def run_agent(self, agent, brief):
        return self.loop.run_until_complete(agent.run(ResearchBriefInput(brief=brief)))

    def test_report_is_built_only_from_retrieved_pages(self):
        pages = {"https://docs.alpha.example/runners": page_text("Alpha runners"),
                 "https://docs.beta.example/runners": page_text("Beta runners")}
        agent, _, _ = build_agent(pages, official_urls=list(pages) + ["https://docs.dead.example/missing"])
        result = self.run_agent(agent, "Explain how self-hosted runners work in Alpha CI and Beta CI pipelines.")

        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        self.assertEqual({s.url for s in result.sources}, set(pages))
        self.assertIn("Retrieval date (UTC)", result.report)
        self.assertIn("## Sources", result.report)
        for src in result.sources:
            self.assertIn(src.url, result.report)

    def test_comparison_plans_official_pages_per_named_option(self):
        pages = {"https://docs.alpha.example/": page_text("Alpha"), "https://docs.beta.example/": page_text("Beta")}
        agent, _, llm = build_agent(pages, entities=["Alpha CI", "Beta Pipelines"], official_urls=list(pages))
        self.run_agent(agent, "Compare Alpha CI and Beta Pipelines for a private repository.")
        focus_prompts = [c["user"] for c in llm.calls if "Focus only on official pages for:" in c["user"]]
        self.assertTrue(any("Alpha CI" in u for u in focus_prompts))
        self.assertTrue(any("Beta Pipelines" in u for u in focus_prompts))

    def test_compared_options_are_parsed_without_the_model(self):
        parse = VeritasAgent._compared_options
        self.assertEqual(parse("Compare Alpha CI, Beta/CD, and Gamma for a small repo."), ["Alpha CI", "Beta/CD", "Gamma"])
        self.assertEqual(parse("Postgres vs MySQL for analytics"), ["Postgres", "MySQL"])
        self.assertEqual(parse("Recommend the best cloud database for our startup."), [])

    def test_brief_urls_are_fetched_and_only_evidence_is_respected(self):
        fixture = "https://fixtures.example/evidence.txt"
        pages = {fixture: page_text("Fixture product"), "https://docs.other.example/": page_text("Other")}
        agent, scraper, _ = build_agent(pages, official_urls=["https://docs.other.example/"])
        result = self.run_agent(agent, f"Using {fixture} as the only evidence, report the product status. Cite that exact URL.")

        self.assertEqual(scraper.fetched, [fixture])
        self.assertEqual([s.url for s in result.sources], [fixture])
        self.assertTrue(any("restricted evidence" in lim for lim in result.limitations))

    def test_evidence_references_are_rewritten_to_urls(self):
        pages = {"https://docs.alpha.example/a": page_text("Alpha")}
        agent, _, _ = build_agent(pages, official_urls=list(pages), cite_style="ref")
        result = self.run_agent(agent, "Describe the Alpha product configuration options in detail.")
        self.assertNotIn("EVIDENCE 1", result.report)
        self.assertIn("(https://docs.alpha.example/a)", result.report)

    def test_unspecified_recommendation_gets_constraints_and_questions(self):
        pages = {"https://docs.db.example/": page_text("Database service")}
        agent, _, llm = build_agent(pages, official_urls=list(pages))
        result = self.run_agent(agent, "Recommend the best cloud database for our startup.")

        self.assertEqual(result.status, ResearchStatus.SUCCESS)
        self.assertGreaterEqual(len(result.clarificationQuestions), 3)
        self.assertIn("Questions That Would Sharpen This Answer", result.report)
        self.assertTrue(any("narrow" in c["system"] for c in llm.calls if "VERITAS" in c["system"]))

    def test_fundamentally_ambiguous_brief_needs_clarification(self):
        agent, _, _ = build_agent({})
        result = self.run_agent(agent, "Compare it.")
        self.assertEqual(result.status, ResearchStatus.NEEDS_CLARIFICATION)
        self.assertIsNone(result.report)
        self.assertGreaterEqual(len(result.clarificationQuestions), 1)

    def test_search_results_pages_are_never_evidence(self):
        self.assertTrue(WebSearchEngine.is_search_results_page("https://www.google.com/search?q=x"))
        self.assertTrue(WebSearchEngine.is_search_results_page("https://duckduckgo.com/?q=x"))
        self.assertFalse(WebSearchEngine.is_search_results_page("https://docs.github.com/en/actions"))

    def test_title_keeps_urls_intact(self):
        agent, _, _ = build_agent({})
        title = agent._derive_topic_title("Summarise https://example.com/a.txt for me.")
        self.assertIn("https://example.com/a.txt", title)


if __name__ == "__main__":
    unittest.main()
