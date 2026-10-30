"""
VERITAS: Output Contract Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from agent.schemas.source import SourceRecord


class ResearchStatus(str, Enum):
    SUCCESS = "success"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


class ResearchReportOutput(BaseModel):
    """Stable, structured output contract produced by the VERITAS research agent."""
    status: ResearchStatus = Field(..., description="Overall execution status: success, needs_clarification, or failed.")
    report: Optional[str] = Field(None, description="Complete Markdown research report when successful.")
    sources: List[SourceRecord] = Field(default_factory=list, description="Structured list of inspected sources.")
    retrievedAt: str = Field(..., description="UTC ISO timestamp of report completion.")
    clarificationQuestions: List[str] = Field(default_factory=list, description="Targeted clarification questions if ambiguous.")
    limitations: List[str] = Field(default_factory=list, description="Documented evidence gaps, conflicting claims, or uncertainties.")
    error: Optional[str] = Field(None, description="Detailed error description when status is failed.")
