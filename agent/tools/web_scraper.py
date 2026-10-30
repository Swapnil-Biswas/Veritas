"""
VERITAS: Secure Web Content Scraper & Metadata Extractor
"""

import httpx
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from agent.tools.security_barrier import ContentSecurityBarrier, SanitizedContent


class PageExtractionResult(BaseModel):
    url: str
    title: str
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: str
    sanitized_content: SanitizedContent
    status_code: int = 200
    is_accessible: bool = True
    error: Optional[str] = None


class WebScraper:
    """Safely retrieves public web pages, extracts structured metadata, and sanitizes untrusted markup."""

    def __init__(self, user_agent: str = "VeritasResearchAgent/1.0 (+https://github.com/Swapnil-Biswas/Veritas)", timeout: float = 12.0):
        self.user_agent = user_agent
        self.timeout = timeout

    async def fetch_page(self, url: str) -> PageExtractionResult:
        retrieval_utc = datetime.now(timezone.utc).isoformat()

        # 1. SSRF and Domain Pre-Flight Check
        is_safe, err_msg = ContentSecurityBarrier.validate_url(url)
        if not is_safe:
            return PageExtractionResult(
                url=url,
                title="Blocked URL",
                retrieved_at=retrieval_utc,
                sanitized_content=SanitizedContent(clean_text=""),
                status_code=403,
                is_accessible=False,
                error=f"Security Barrier Blocked URL: {err_msg}"
            )

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                return PageExtractionResult(
                    url=url,
                    title=f"HTTP {resp.status_code}",
                    retrieved_at=retrieval_utc,
                    sanitized_content=SanitizedContent(clean_text=""),
                    status_code=resp.status_code,
                    is_accessible=False,
                    error=f"Received non-200 HTTP status code: {resp.status_code}"
                )

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract Title
            title = ""
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
            elif soup.title and soup.title.string:
                title = soup.title.string.strip()
            if not title:
                title = url

            # Extract Publisher
            publisher = None
            site_name = soup.find("meta", property="og:site_name")
            if site_name and site_name.get("content"):
                publisher = site_name["content"].strip()

            # Extract Publication Date
            pub_date = None
            date_meta = (
                soup.find("meta", property="article:published_time")
                or soup.find("meta", attrs={"name": "date"})
                or soup.find("meta", attrs={"name": "pubdate"})
            )
            if date_meta and date_meta.get("content"):
                pub_date = date_meta["content"].strip()

            # Sanitize content
            sanitized = ContentSecurityBarrier.sanitize_untrusted_html(resp.text)

            return PageExtractionResult(
                url=str(resp.url),
                title=title,
                publisher=publisher,
                published_at=pub_date,
                retrieved_at=retrieval_utc,
                sanitized_content=sanitized,
                status_code=resp.status_code,
                is_accessible=True
            )

        except Exception as e:
            return PageExtractionResult(
                url=url,
                title="Fetch Error",
                retrieved_at=retrieval_utc,
                sanitized_content=SanitizedContent(clean_text=""),
                status_code=500,
                is_accessible=False,
                error=f"Connection failure: {str(e)}"
            )
