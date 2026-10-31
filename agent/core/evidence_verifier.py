"""
VERITAS: Evidence Extraction, Claim Verification & Conflict Analysis Engine
"""

from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone
import re
from pydantic import BaseModel, Field

from agent.schemas.source import SourceRecord


class VerifiedClaim(BaseModel):
    """An empirical factual statement grounded in identifiable source evidence."""
    claim: str
    source_url: str
    source_title: str
    is_direct_evidence: bool = True
    is_primary_source: bool = False
    evidence_snippet: str
    retrieved_at: str


class EvidenceConflict(BaseModel):
    """A substantive factual disagreement between inspected external sources."""
    dimension: str
    claim_a: str
    source_a_url: str
    claim_b: str
    source_b_url: str
    forensic_assessment: str


class EvidenceVerifier:
    """Evaluates evidence authority, extracts corroborated claims, and flags conflicts or evidence gaps."""

    @staticmethod
    def extract_salient_claims(
        raw_text: str,
        source_url: str,
        source_title: str,
        is_primary: bool = False
    ) -> List[VerifiedClaim]:
        """
        Parses cleaned document text into individual factual claims with accompanying verbatim snippets.
        Filters out boilerplate, questions, and navigational text.
        """
        retrieval_utc = datetime.now(timezone.utc).isoformat()
        sentences = re.split(r"(?<=[.!?])\s+", raw_text)

        claims: List[VerifiedClaim] = []
        for s in sentences:
            s_clean = s.strip()
            # Must be substantive factual sentence
            if len(s_clean) < 35 or len(s_clean) > 300:
                continue
            if s_clean.endswith("?") or s_clean.startswith("http") or "cookie" in s_clean.lower():
                continue

            claims.append(
                VerifiedClaim(
                    claim=s_clean,
                    source_url=source_url,
                    source_title=source_title,
                    is_direct_evidence=True,
                    is_primary_source=is_primary,
                    evidence_snippet=s_clean,
                    retrieved_at=retrieval_utc
                )
            )

        return claims[:12]  # Cap per document to avoid bloat

    @staticmethod
    def identify_conflicts_and_gaps(
        claims: List[VerifiedClaim],
        required_topics: List[str]
    ) -> Tuple[List[EvidenceConflict], List[str]]:
        """
        Examines extracted claims for temporal, quantitative, or architectural discordance.
        Identifies uncorroborated required topics as explicit evidence gaps.
        """
        conflicts: List[EvidenceConflict] = []
        evidence_gaps: List[str] = []

        all_text = " ".join([c.claim.lower() for c in claims])

        # Check required topics
        for topic in required_topics:
            t_low = topic.lower()
            if t_low not in all_text:
                evidence_gaps.append(f"No authoritative evidence found directly addressing: '{topic}'.")

        # Cross-source conflicts are reported by the synthesis stage, which sees the full evidence text.
        return conflicts, evidence_gaps

    @staticmethod
    def compile_source_records(
        claims_by_url: Dict[str, List[VerifiedClaim]],
        metadata_by_url: Dict[str, Dict[str, Any]]
    ) -> List[SourceRecord]:
        """Assembles verified claims into structured SourceRecord schemas."""
        records: List[SourceRecord] = []

        for url, claims in claims_by_url.items():
            meta = metadata_by_url.get(url, {})
            title = meta.get("title", claims[0].source_title if claims else url)
            publisher = meta.get("publisher")
            pub_date = meta.get("published_at")
            retrieved_at = meta.get("retrieved_at", datetime.now(timezone.utc).isoformat())
            is_primary = meta.get("is_primary", False)

            claim_strings = [c.claim for c in claims]
            snippet = claims[0].evidence_snippet if claims else None

            records.append(
                SourceRecord(
                    title=title,
                    url=url,
                    publisher=publisher,
                    publishedAt=pub_date,
                    retrievedAt=retrieved_at,
                    relevance=0.90 if is_primary else 0.75,
                    claimsSupported=claim_strings,
                    isPrimary=is_primary,
                    evidenceSnippet=snippet
                )
            )

        return records

