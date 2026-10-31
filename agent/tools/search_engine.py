"""
VERITAS: Source Discovery & Targeted Web Search Engine

Discovery uses three genuine mechanisms; nothing is hardcoded per topic:
  1. Official-page planning: the language model proposes official documentation / primary-source
     URLs for the brief. A proposal is only evidence after it is actually fetched (WebScraper),
     so a hallucinated or dead URL simply drops out.
  2. Web search through Tavily when TAVILY_API_KEY is set (https://tavily.com, paid per query).
  3. Keyless fallback: Google News RSS search, used to supplement thin primary evidence.
"""

import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from agent.tools.llm_client import LLMClient
from agent.tools.security_barrier import ContentSecurityBarrier

NEWS_SEARCH_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
TAVILY_ENDPOINT = "https://api.tavily.com/search"

OFFICIAL_URL_PLAN_SYSTEM = (
    "List the official documentation or primary-source web pages most likely to contain the facts needed for the "
    "task: vendor documentation, official release schedule or lifecycle pages, official project sites, regulator or "
    "standards-body pages. Prefer specific pages over home pages. "
    "Reply with a JSON list of up to {n} https URLs and nothing else. Do not answer the task."
)
ENTITY_PLAN_SYSTEM = (
    "List the distinct products, services, organisations or projects that the task explicitly names, exactly as written "
    "in the task. Reply with a JSON list of strings and nothing else. Reply [] if the task names fewer than two."
)
QUERY_PLAN_SYSTEM = (
    "Write up to {n} short web search queries that would find public evidence relevant to the task. "
    "Reply with a JSON list of strings and nothing else. Do not answer the task."
)


class SearchResultItem(BaseModel):
    title: str
    url: str
    snippet: str
    is_primary_domain: bool = False
    provider: str = "search"


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


class WebSearchEngine:
    """Discovers candidate web sources for research questions."""

    def __init__(self, llm: Optional[LLMClient] = None, timeout: float = 15.0):
        self.llm = llm or LLMClient()
        self.timeout = timeout
        self.tavily_key = os.getenv("TAVILY_API_KEY", "")

    @staticmethod
    def is_primary_source(url: str) -> bool:
        """Heuristic: documentation hosts, government, academic and standards domains are primary sources."""
        host = (urlparse(url).hostname or "").lower()
        if host.startswith(("docs.", "developer.", "developers.", "learn.", "support.", "help.")):
            return True
        if host.endswith((".gov", ".edu", ".int", ".europa.eu", "arxiv.org", "ietf.org", "w3.org", "iso.org")):
            return True
        path = urlparse(url).path.lower()
        return "/docs" in path or "/documentation" in path

    @staticmethod
    def is_search_results_page(url: str) -> bool:
        """A search-engine results page is a discovery aid, never evidence."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        query = urllib.parse.parse_qs(parsed.query)
        engine_hosts = ("google.", "bing.com", "duckduckgo.com", "search.yahoo.com", "yandex.", "baidu.com")
        return (any(h in host for h in engine_hosts) and ("/search" in parsed.path or "q" in query)) \
            or (parsed.path.rstrip("/").endswith("/search") and bool(query))

    async def propose_official_urls(self, brief: str, limit: int = 6, avoid: Optional[List[str]] = None) -> List[str]:
        """Candidate official pages for the brief. Unverified until fetched."""
        user = f"TASK:\n{brief}"
        if avoid:
            user += "\n\nThese URLs were unreachable or unusable; propose different pages:\n" + "\n".join(avoid[-10:])
        urls = await self.llm.chat_list(OFFICIAL_URL_PLAN_SYSTEM.replace("{n}", str(limit)), user)
        out: List[str] = []
        for u in urls:
            u = u.rstrip(".,;)")
            if u.startswith("https://") and u not in out and not self.is_search_results_page(u):
                out.append(u)
        return out[:limit]

    async def plan_entities(self, brief: str, limit: int = 5) -> List[str]:
        """Named products/organisations the brief asks about, so each one gets its own official evidence."""
        names = await self.llm.chat_list(ENTITY_PLAN_SYSTEM, f"TASK:\n{brief}", max_tokens=1500)
        out: List[str] = []
        for n in names:
            n = n[:80]
            # Only names that literally appear in the brief; the model must not introduce new subjects.
            if n.lower() in brief.lower() and n.lower() not in (x.lower() for x in out):
                out.append(n)
        # Names that share a word ("Active LTS", "Maintenance LTS") are facets of one subject, not separate options.
        words = [set(re.findall(r"[a-z0-9.+#/-]+", n.lower())) for n in out]
        distinct = [n for i, n in enumerate(out) if not any(words[i] & words[j] for j in range(len(out)) if j != i)]
        return distinct[:limit]

    async def plan_queries(self, brief: str, limit: int = 2) -> List[str]:
        queries = await self.llm.chat_list(QUERY_PLAN_SYSTEM.replace("{n}", str(limit)), f"TASK:\n{brief}", max_tokens=1500)
        return [q[:150] for q in queries][:limit]

    async def search(self, query: str, limit: int = 5) -> List[SearchResultItem]:
        """Executes a real search query; Tavily when configured, otherwise Google News RSS."""
        if self.tavily_key:
            results = await self._tavily(query, limit)
            if results:
                return results
        return await self._news_rss(query, limit)

    async def _tavily(self, query: str, limit: int) -> List[SearchResultItem]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    TAVILY_ENDPOINT,
                    json={"query": query, "max_results": limit, "search_depth": "basic"},
                    headers={"Authorization": f"Bearer {self.tavily_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []
        out = []
        for r in data.get("results", [])[:limit]:
            url = r.get("url", "")
            if url.startswith(("http://", "https://")):
                out.append(SearchResultItem(
                    title=(r.get("title") or url)[:300], url=url, snippet=(r.get("content") or "")[:800],
                    is_primary_domain=self.is_primary_source(url), provider="tavily",
                ))
        return out

    async def _news_rss(self, query: str, limit: int) -> List[SearchResultItem]:
        url = NEWS_SEARCH_RSS.format(q=urllib.parse.quote(query))
        ok, _ = ContentSecurityBarrier.validate_url(url)
        if not ok:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                resp = await client.get(url, headers={"User-Agent": "VeritasResearchAgent/1.1"})
            if resp.status_code != 200:
                return []
            # Refuse DTDs/entities outright; a search feed never needs them.
            body = resp.text
            if "<!DOCTYPE" in body or "<!ENTITY" in body:
                return []
            root = ET.fromstring(body)
        except Exception:
            return []
        out = []
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            if not link.startswith("https://"):
                continue
            title = _strip_tags(item.findtext("title") or "")
            source = _strip_tags(item.findtext("source") or "")
            published = (item.findtext("pubDate") or "").strip()
            summary = _strip_tags(item.findtext("description") or "")[:500]
            out.append(SearchResultItem(
                title=title[:300] or link, url=link, provider="news",
                snippet=f"News headline: {title}\nPublisher: {source}\nPublished: {published}\n{summary}",
            ))
            if len(out) >= limit:
                break
        return out
