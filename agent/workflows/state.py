"""
VERITAS: Research Workflow State & Telemetry Ledger
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from agent.schemas.source import SourceRecord
from agent.core.evidence_verifier import VerifiedClaim, EvidenceConflict


class ResearchStage(str, Enum):
    INTERPRET = "interpret_brief"
    PLAN = "plan_research"
    DISCOVER = "discover_sources"
    EXTRACT = "extract_evidence"
    VERIFY = "verify_claims"
    SYNTHESIZE = "synthesize_report"
    QUALITY_AUDIT = "audit_citations"
    COMPLETE = "complete"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


class ResearchState(BaseModel):
    brief: str
    current_stage: ResearchStage = ResearchStage.INTERPRET
    extracted_entities: List[str] = Field(default_factory=list)
    research_questions: List[str] = Field(default_factory=list)
    search_queries: List[str] = Field(default_factory=list)
    inspected_urls: List[str] = Field(default_factory=list)
    raw_claims: List[VerifiedClaim] = Field(default_factory=list)
    conflicts: List[EvidenceConflict] = Field(default_factory=list)
    evidence_gaps: List[str] = Field(default_factory=list)
    sources: List[SourceRecord] = Field(default_factory=list)
    report_markdown: Optional[str] = None
    clarification_questions: List[str] = Field(default_factory=list)
    error: Optional[str] = None
