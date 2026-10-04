"""
Deterministic Report Quality and Research Gap Analyzer for Phase 10.

Computes objective, empirical quality indicators and surfaces research gaps
in calm, rigorous scientific language. Never uses opaque "AI scores".
"""

from __future__ import annotations

from typing import Any, Optional
from orvia.app.reports.models import ReportQualityMetrics


class ReportQualityAnalyzer:
    """
    Analyzes completeness, evidence coverage, citation integrity,
    and unaddressed research gaps for a research report.
    """

    @staticmethod
    def analyze(
        sources: list[Any],
        evidence_list: list[Any],
        findings_list: list[Any],
        finding_evidence_map: dict[str, list[str]],  # finding_id -> list[evidence_id]
        questions: list[Any],
        concepts: list[Any],
        concept_source_counts: dict[str, int],  # concept_id -> count of sources
        insufficient_history_concepts: int = 0,
    ) -> ReportQualityMetrics:
        """
        Calculate structured research metrics and identify empirical gaps.
        """
        total_sources = len(sources)
        total_evidence = len(evidence_list)
        total_findings = len(findings_list)
        total_questions = len(questions)

        # 1. Evidence coverage: % of findings supported by >= 1 evidence
        if total_findings > 0:
            supported_findings_count = sum(
                1 for f in findings_list
                if len(finding_evidence_map.get(getattr(f, "id", None) or f.get("id"), [])) > 0
            )
            evidence_cov_pct = (supported_findings_count / total_findings) * 100.0
            unsupported_findings_count = total_findings - supported_findings_count
        else:
            evidence_cov_pct = 100.0 if total_evidence > 0 else 0.0
            unsupported_findings_count = 0

        # 2. Source coverage: % of attached sources cited by at least one evidence item
        cited_source_ids = {
            getattr(e, "source_id", None) or e.get("source_id")
            for e in evidence_list
            if getattr(e, "source_id", None) or (isinstance(e, dict) and e.get("source_id"))
        }
        attached_source_ids = {
            getattr(s, "id", None) or s.get("id")
            for s in sources
            if getattr(s, "id", None) or (isinstance(s, dict) and s.get("id"))
        }
        if total_sources > 0:
            cited_attached = len(cited_source_ids.intersection(attached_source_ids))
            source_cov_pct = (cited_attached / total_sources) * 100.0
            uncited_sources_count = total_sources - cited_attached
        else:
            source_cov_pct = 0.0
            uncited_sources_count = 0

        # 3. Finding coverage: % of findings with status 'SUPPORTED'
        if total_findings > 0:
            status_supported = sum(
                1 for f in findings_list
                if (getattr(f, "status", None) or f.get("status", "")).upper() == "SUPPORTED"
            )
            finding_cov_pct = (status_supported / total_findings) * 100.0
        else:
            finding_cov_pct = 0.0

        # 4. Citation completeness: % of evidence records with an attached valid source
        if total_evidence > 0:
            valid_citations = sum(
                1 for e in evidence_list
                if (getattr(e, "source_id", None) or e.get("source_id"))
            )
            citation_comp_pct = (valid_citations / total_evidence) * 100.0
        else:
            citation_comp_pct = 100.0

        # 5. Open questions count
        open_questions_count = sum(
            1 for q in questions
            if (getattr(q, "status", None) or q.get("status", "OPEN")).upper() != "RESOLVED"
        )

        # 6. Single-source concepts
        single_source_concepts_count = sum(
            1 for c_id, count in concept_source_counts.items()
            if count == 1
        )

        # 7. Identify empirical gaps
        gaps: list[str] = []
        if unsupported_findings_count > 0:
            gaps.append(
                f"{unsupported_findings_count} finding(s) currently have no linked evidence."
            )
        if uncited_sources_count > 0:
            gaps.append(
                f"{uncited_sources_count} attached source(s) have no direct evidence cited in this report."
            )
        if open_questions_count > 0:
            gaps.append(
                f"{open_questions_count} investigation question(s) remain unresolved."
            )
        if single_source_concepts_count > 0:
            gaps.append(
                f"{single_source_concepts_count} concept(s) occur in only one source."
            )
        if insufficient_history_concepts > 0:
            gaps.append(
                f"{insufficient_history_concepts} concept(s) have insufficient temporal history for trend evaluation."
            )
        if total_sources == 0:
            gaps.append("No sources are currently attached to this investigation.")
        if total_evidence == 0:
            gaps.append("No empirical evidence has been recorded for this investigation.")

        return ReportQualityMetrics(
            evidence_coverage_pct=evidence_cov_pct,
            source_coverage_pct=source_cov_pct,
            finding_coverage_pct=finding_cov_pct,
            citation_completeness_pct=citation_comp_pct,
            open_questions_count=open_questions_count,
            unsupported_findings_count=unsupported_findings_count,
            insufficient_history_concepts_count=insufficient_history_concepts,
            single_source_concepts_count=single_source_concepts_count,
            gaps=gaps,
        )
