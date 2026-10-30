"""
VERITAS: Source & Evidence Record Schemas
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
from datetime import datetime


class SourceRecord(BaseModel):
    """Structured representation of an inspected web source and its verified claims."""
    title: str = Field(..., description="Document or webpage title.")
    url: str = Field(..., description="Exact verifiable URL inspected.")
    publisher: Optional[str] = Field(None, description="Publisher, corporate entity, or organization.")
    publishedAt: Optional[str] = Field(None, description="Reported publication or release timestamp.")
    retrievedAt: str = Field(..., description="UTC ISO timestamp of retrieval.")
    relevance: float = Field(..., ge=0.0, le=1.0, description="Estimated thematic relevance score.")
    claimsSupported: List[str] = Field(default_factory=list, description="List of factual claims directly backed by this source.")
    isPrimary: bool = Field(False, description="Whether this is a primary source (official doc, dataset, academic paper).")
    evidenceSnippet: Optional[str] = Field(None, description="Verbatim textual evidence extracted from the document.")
