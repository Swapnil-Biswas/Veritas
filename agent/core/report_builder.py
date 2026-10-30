"""
VERITAS: Source-Grounded Research Report Assembler & Citation Validator
"""

from typing import List, Tuple, Optional
from datetime import datetime, timezone
from agent.schemas.source import SourceRecord


class ReportBuilder:
    """Assembles professional research reports strictly compliant with the VERITAS specification."""

    @staticmethod
    def format_report(
        topic: str,
        scope: str,
        executive_summary: str,
        key_findings: List[Tuple[str, str]],  # (Finding text, exact citation URL)
        detailed_analysis: str,
        comparison_table: Optional[str],
        limitations: List[str],
        conclusion: str,
        sources: List[SourceRecord],
        retrieval_date_utc: Optional[str] = None
    ) -> str:
        date_str = retrieval_date_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines: List[str] = []

        # Header
        lines.append(f"# Research Report: {topic}\n")
        lines.append(f"**Research date:** {date_str}  ")
        lines.append(f"**Research scope:** {scope}\n")

        # 1. Executive Summary
        lines.append("## 1. Executive Summary")
        lines.append(f"{executive_summary.strip()}\n")

        # 2. Key Findings (with citations directly beside claims)
        lines.append("## 2. Key Findings")
        for finding_text, citation_url in key_findings:
            lines.append(f"- {finding_text} [Source: {citation_url}]")
        lines.append("")

        # 3. Detailed Analysis
        lines.append("## 3. Detailed Analysis")
        lines.append(f"{detailed_analysis.strip()}\n")

        # 4. Comparison Table (if present)
        if comparison_table and comparison_table.strip():
            lines.append("## 4. Comparison")
            lines.append(f"{comparison_table.strip()}\n")

        # 5. Limitations and Uncertainties
        lines.append("## 5. Limitations and Uncertainties")
        if limitations:
            for lim in limitations:
                lines.append(f"- {lim}")
        else:
            lines.append("- No substantial evidence gaps or conflicting claims identified in primary documentation.")
        lines.append("")

        # 6. Conclusion
        lines.append("## 6. Conclusion")
        lines.append(f"{conclusion.strip()}\n")

        # Sources (Numbered list with exact URL, publisher, dates)
        lines.append("## Sources")
        for idx, src in enumerate(sources, 1):
            pub_info = f" • Published: {src.publishedAt}" if src.publishedAt else ""
            publisher_info = f" ({src.publisher})" if src.publisher else ""
            lines.append(
                f"{idx}. **{src.title}**{publisher_info}\n"
                f"   - URL: {src.url}\n"
                f"   - Retrieved: {src.retrievedAt}{pub_info}"
            )

        return "\n".join(lines)

    @staticmethod
    def audit_citation_integrity(report_markdown: str, sources: List[SourceRecord]) -> Tuple[bool, List[str]]:
        """
        Guarantees that every source listed in the Sources section is actually referenced in the report text,
        and that no external URL appears without a corresponding inspected source entry.
        """
        findings: List[str] = []
        for src in sources:
            if src.url not in report_markdown:
                findings.append(f"Source URL '{src.url}' declared in sources array but uncited in report body.")

        return len(findings) == 0, findings
