"""
VERITAS: Secure Web Content Scraper & Metadata Extractor
"""

import re
import urllib.parse
import httpx
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import Optional, Tuple
from pydantic import BaseModel

from agent.tools.security_barrier import ContentSecurityBarrier, SanitizedContent

MAX_REDIRECTS = 5
MAX_BODY_CHARS = 600_000
ALLOWED_CONTENT_HINTS = ("text/", "html", "xml", "json")


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

    def __init__(self, user_agent: str = "VeritasResearchAgent/1.1 (+https://github.com/Swapnil-Biswas/Veritas)", timeout: float = 12.0):
        self.user_agent = user_agent
        self.timeout = timeout

    async def fetch_raw(self, url: str) -> Tuple[str, int, str, str]:
        """
        GETs a public URL and returns (final_url, status, content_type, body).
        Redirects are followed manually so every hop passes the SSRF barrier again.
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.9"
        }
        current = url
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False, headers=headers) as client:
            for _ in range(MAX_REDIRECTS + 1):
                is_safe, err_msg = ContentSecurityBarrier.validate_url(current)
                if not is_safe:
                    raise PermissionError(f"Security Barrier Blocked URL: {err_msg}")
                resp = await client.get(current)
                if resp.is_redirect and resp.headers.get("location"):
                    current = urllib.parse.urljoin(current, resp.headers["location"])
                    continue
                ctype = resp.headers.get("content-type", "")
                return current, resp.status_code, ctype, resp.text[:MAX_BODY_CHARS]
        raise ConnectionError("Too many redirects")

    @staticmethod
    def _meta_refresh_target(body: str, base_url: str) -> Optional[str]:
        head = body[:4000]
        if "http-equiv" not in head.lower():
            return None
        soup = BeautifulSoup(head, "html.parser")
        meta = soup.find("meta", attrs={"http-equiv": lambda v: v and v.lower() == "refresh"})
        content = meta.get("content", "") if meta else ""
        match = re.search(r"url\s*=\s*['\"]?([^'\";]+)", content, re.I)
        return urllib.parse.urljoin(base_url, match.group(1).strip()) if match else None

    async def fetch_page(self, url: str) -> PageExtractionResult:
        retrieval_utc = datetime.now(timezone.utc).isoformat()

        def failure(title: str, status: int, error: str) -> PageExtractionResult:
            return PageExtractionResult(
                url=url,
                title=title,
                retrieved_at=retrieval_utc,
                sanitized_content=SanitizedContent(clean_text=""),
                status_code=status,
                is_accessible=False,
                error=error
            )

        try:
            final_url, status, ctype, body = await self.fetch_raw(url)
            # Documentation sites often relocate pages with an HTML meta refresh instead of an HTTP redirect.
            for _ in range(2):
                target = self._meta_refresh_target(body, final_url) if status == 200 and "html" in ctype else None
                if not target:
                    break
                final_url, status, ctype, body = await self.fetch_raw(target)
        except PermissionError as e:
            return failure("Blocked URL", 403, str(e))
        except Exception as e:
            return failure("Fetch Error", 500, f"Connection failure: {type(e).__name__}")

        if status != 200:
            return failure(f"HTTP {status}", status, f"Received non-200 HTTP status code: {status}")
        if ctype and not any(h in ctype for h in ALLOWED_CONTENT_HINTS):
            return failure("Unsupported content", 415, f"Unsupported content type: {ctype}")

        is_markup = "html" in ctype or "xml" in ctype or body.lstrip()[:1] == "<"
        title, publisher, pub_date = "", None, None
        if is_markup:
            soup = BeautifulSoup(body, "html.parser")

            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
            elif soup.title and soup.title.string:
                title = soup.title.string.strip()

            site_name = soup.find("meta", property="og:site_name")
            if site_name and site_name.get("content"):
                publisher = site_name["content"].strip()

            date_meta = (
                soup.find("meta", property="article:published_time")
                or soup.find("meta", attrs={"name": "date"})
                or soup.find("meta", attrs={"name": "pubdate"})
            )
            if date_meta and date_meta.get("content"):
                pub_date = date_meta["content"].strip()

            # Main content first, so navigation chrome does not crowd out evidence.
            main = soup.find("main") or soup.find("article")
            if main is not None:
                body = str(main)
            sanitized = ContentSecurityBarrier.sanitize_untrusted_html(body)
        else:
            # Plain text / JSON: escape so the HTML parser keeps it verbatim.
            sanitized = ContentSecurityBarrier.sanitize_untrusted_html(
                "<pre>" + body.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
            )

        if not title:
            title = final_url

        return PageExtractionResult(
            url=final_url,
            title=title[:300],
            publisher=publisher,
            published_at=pub_date,
            retrieved_at=retrieval_utc,
            sanitized_content=sanitized,
            status_code=status,
            is_accessible=True
        )
