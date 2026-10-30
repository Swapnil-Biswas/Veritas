"""
VERITAS: Input Contract Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum


class ResearchDepth(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    EXHAUSTIVE = "exhaustive"


class ResearchBriefInput(BaseModel):
    """Structured input contract accepted by the VERITAS research agent."""
    brief: str = Field(..., min_length=5, max_length=50000, description="The buyer's core research request or question.")
    context: Optional[str] = Field(None, max_length=20000, description="Optional background context or domain specifics.")
    constraints: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Geographic, temporal, or technological constraints.")
    depth: ResearchDepth = Field(ResearchDepth.STANDARD, description="Research depth profile: quick, standard, or exhaustive.")
    max_sources: int = Field(10, ge=1, le=50, description="Maximum number of authoritative sources to inspect.")
    preferred_domains: Optional[List[str]] = Field(default_factory=list, description="Optional list of authoritative domains to prioritize.")
