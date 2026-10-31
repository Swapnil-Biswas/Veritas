"""
Deterministic stand-ins for the network and the language model, so agent tests exercise the
real orchestration logic (planning, fetching, citation handling, failure paths) offline.
"""

import json
import re
from typing import Dict, List

from agent.tools.web_scraper import WebScraper, PageExtractionResult
from agent.tools.search_engine import WebSearchEngine, SearchResultItem
from agent.tools.security_barrier import ContentSecurityBarrier, SanitizedContent


class FakeLLM:
    """Answers planning prompts from fixed lists and writes report bodies that cite every evidence URL."""

    def __init__(self, official_urls: List[str] = None, entities: List[str] = None, queries: List[str] = None,
                 cite: bool = True, cite_style: str = "url"):
        self.official_urls = official_urls or []
        self.entities = entities or []
        self.queries = queries or []
        self.cite = cite
        self.cite_style = cite_style
        self.calls: List[Dict[str, str]] = []

    async def chat(self, system: str, user: str, max_tokens: int = 3000) -> str:
        self.calls.append({"system": system, "user": user})
        evidence_urls = re.findall(r"^URL: (\S+)$", user, re.M)
        if not self.cite or not evidence_urls:
            return "## Executive Summary\nThe retrieved evidence does not establish the requested value, so none is stated here."
        if self.cite_style == "ref":
            refs = ", ".join(f"EVIDENCE {i}" for i in range(1, len(evidence_urls) + 1))
            return f"## Executive Summary\nAll findings below are drawn from the retrieved pages ({refs}).\n\n## Conclusion\nDone."
        lines = [f"- A finding taken from this page ({u})." for u in evidence_urls]
        return "## Executive Summary\nFindings from retrieved evidence.\n\n## Key Findings\n" + "\n".join(lines)

    async def chat_list(self, system: str, user: str, max_tokens: int = 2000) -> List[str]:
        self.calls.append({"system": system, "user": user})
        if "products, services, organisations" in system:
            return list(self.entities)
        if "search queries" in system:
            return list(self.queries)
        return list(self.official_urls)


class FakeScraper(WebScraper):
    """Serves pages from a dict; any other URL behaves like an unreachable host."""

    def __init__(self, pages: Dict[str, str]):
        super().__init__()
        self.pages = pages
        self.fetched: List[str] = []

    async def fetch_page(self, url: str) -> PageExtractionResult:
        self.fetched.append(url)
        if url not in self.pages:
            return PageExtractionResult(url=url, title="Fetch Error", retrieved_at="2026-10-31T00:00:00+00:00",
                                        sanitized_content=SanitizedContent(clean_text=""), status_code=500,
                                        is_accessible=False, error="Connection failure")
        text = self.pages[url]
        return PageExtractionResult(url=url, title=f"Page {url}", retrieved_at="2026-10-31T00:00:00+00:00",
                                    sanitized_content=ContentSecurityBarrier.sanitize_untrusted_html(f"<p>{text}</p>"))


class FakeSearchEngine(WebSearchEngine):
    def __init__(self, llm: FakeLLM, results: List[SearchResultItem] = None):
        super().__init__(llm=llm)
        self.tavily_key = ""
        self.results = results or []

    async def search(self, query: str, limit: int = 5) -> List[SearchResultItem]:
        return self.results[:limit]


def page_text(topic: str) -> str:
    return (f"{topic} is documented on this page in enough detail to be used as evidence. "
            f"The documentation describes configuration, supported platforms and limits for {topic}. ") * 2


def as_json(items) -> str:
    return json.dumps(items)
