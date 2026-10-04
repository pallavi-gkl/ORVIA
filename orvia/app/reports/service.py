"""
ResearchReportService — orchestrates creation, editing, versioning, export,
quality analysis, and provenance management for ORVIA Research Reports.
Phase 10.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from orvia.app.reports.models import (
    Report, ReportSection, ReportSource, ReportEvidence, ReportFinding,
    ReportStatus, ReportQualityMetrics, ReportVersionDiff, VALID_REPORT_STATUSES,
)
from orvia.app.reports.repository import ReportRepository
from orvia.app.reports.synthesis import ReportSynthesisEngine
from orvia.app.reports.quality import ReportQualityAnalyzer
from orvia.app.reports.export import ReportExportService
from orvia.app.reports.comparison import ReportVersionComparator
from orvia.app.reports.citations import CitationManager
from orvia.app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class ResearchReportService:
    """Single-entry-point for all report business logic."""

    def __init__(
        self,
        db: Any,
        investigation_repo: Any,
        source_repo: Any,
        concept_repo: Any,
        analytics_service: Optional[Any] = None,
    ) -> None:
        self._db = db
        self._inv_repo = investigation_repo
        self._src_repo = source_repo
        self._concept_repo = concept_repo
        self._analytics_svc = analytics_service
        self._report_repo = ReportRepository(db)
        self._synthesis_engine = ReportSynthesisEngine(
            db=db,
            investigation_repo=investigation_repo,
            source_repo=source_repo,
            concept_repo=concept_repo,
            analytics_service=analytics_service,
        )
        self._export_svc = ReportExportService(
            repo=self._report_repo,
            investigation_repo=investigation_repo,
            source_repo=source_repo,
        )
        self._comparator = ReportVersionComparator(self._report_repo)

    # =========================================================================
    # Core Report Lifecycle
    # =========================================================================

    def create_report(
        self,
        investigation_id: str,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        selected_sections: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Synthesize and persist a full research report for an investigation.
        Returns a workspace dict with report + sections + provenance links.
        """
        report, sections, report_sources, report_evidence, report_findings = (
            self._synthesis_engine.synthesize(
                investigation_id=investigation_id,
                title=title,
                subtitle=subtitle,
                selected_sections=selected_sections,
            )
        )

        # Persist all in one logical transaction
        self._report_repo.create(report)
        for sec in sections:
            self._report_repo.add_section(sec)
        for rs in report_sources:
            self._report_repo.link_source(rs)
        for re_ in report_evidence:
            self._report_repo.link_evidence(re_)
        for rf in report_findings:
            self._report_repo.link_finding(rf)

        logger.info("Created report %s for investigation %s", report.id, investigation_id)
        return self._build_workspace(report)

    def get_report(self, report_id: str) -> dict[str, Any]:
        """Return full report workspace: report + sections + quality + provenance."""
        report = self._report_repo.get_by_id(report_id)
        if not report:
            raise ValueError(f"Report '{report_id}' not found.")
        return self._build_workspace(report)

    def get_reports_for_investigation(self, investigation_id: str) -> list[dict[str, Any]]:
        """Return all report summaries for an investigation."""
        reports = self._report_repo.get_by_investigation(investigation_id)
        return [r.to_dict() for r in reports]

    def list_reports(
        self,
        status: Optional[str] = None,
        search_query: Optional[str] = None,
        investigation_id: Optional[str] = None,
        sort_by: str = "updated_at",
        order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List reports with optional filters."""
        reports = self._report_repo.list(
            status=status,
            search_query=search_query,
            investigation_id=investigation_id,
            sort_by=sort_by,
            order=order,
            limit=limit,
            offset=offset,
        )
        result = []
        for r in reports:
            d = r.to_dict()
            d["section_count"] = len(self._report_repo.get_sections(r.id))
            d["source_count"] = len(self._report_repo.get_sources(r.id))
            d["evidence_count"] = len(self._report_repo.get_evidence(r.id))
            result.append(d)
        return result

    def update_report(
        self,
        report_id: str,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Report:
        """Update mutable report fields."""
        report = self._report_repo.get_by_id(report_id)
        if not report:
            raise ValueError(f"Report '{report_id}' not found.")
        if title and title.strip():
            report.title = title.strip()
        if subtitle is not None:
            report.subtitle = subtitle.strip()
        if summary is not None:
            report.summary = summary.strip()
        return self._report_repo.update(report)

    def update_report_status(self, report_id: str, new_status: str) -> Report:
        """Transition report to a new lifecycle status."""
        report = self._report_repo.get_by_id(report_id)
        if not report:
            raise ValueError(f"Report '{report_id}' not found.")
        norm = new_status.upper()
        if norm not in VALID_REPORT_STATUSES:
            raise ValidationError(f"Invalid status '{new_status}'.", field="status")
        report.status = norm
        return self._report_repo.update(report)

    def delete_report(self, report_id: str) -> bool:
        """Delete a report."""
        return self._report_repo.delete(report_id)

    # =========================================================================
    # Section Management
    # =========================================================================

    def update_section(
        self,
        section_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        position: Optional[int] = None,
    ) -> ReportSection:
        """Update a report section's title, content, or position."""
        section = self._report_repo.get_section_by_id(section_id)
        if not section:
            raise ValueError(f"Section '{section_id}' not found.")
        if title and title.strip():
            section.title = title.strip()
        if content is not None:
            section.content = content
        if position is not None:
            section.position = int(position)
        return self._report_repo.update_section(section)

    def add_custom_section(
        self,
        report_id: str,
        section_type: str,
        title: str,
        content: str = "",
        position: Optional[int] = None,
    ) -> ReportSection:
        """Add a custom section to an existing report."""
        report = self._report_repo.get_by_id(report_id)
        if not report:
            raise ValueError(f"Report '{report_id}' not found.")
        if position is None:
            existing = self._report_repo.get_sections(report_id)
            position = len(existing)
        sec = ReportSection(
            report_id=report_id,
            section_type=section_type.upper(),
            title=title,
            position=position,
            content=content,
        )
        return self._report_repo.add_section(sec)

    def delete_section(self, section_id: str) -> bool:
        """Delete a section from a report."""
        return self._report_repo.delete_section(section_id)

    def reorder_sections(self, report_id: str, section_ids: list[str]) -> bool:
        """Reorder sections."""
        return self._report_repo.reorder_sections(report_id, section_ids)

    # =========================================================================
    # Versioning
    # =========================================================================

    def create_version(self, report_id: str, new_status: str = "DRAFT") -> Report:
        """Create a new version of an existing report."""
        return self._report_repo.create_version(report_id, new_status)

    def get_versions(self, report_id: str) -> list[Report]:
        """Return all report versions for the same investigation lineage."""
        return self._report_repo.get_versions(report_id)

    def compare_versions(self, report_a_id: str, report_b_id: str) -> ReportVersionDiff:
        """Compute deterministic diff between two report versions."""
        return self._comparator.compare(report_a_id, report_b_id)

    # =========================================================================
    # Quality & Provenance
    # =========================================================================

    def get_quality_metrics(self, report_id: str) -> ReportQualityMetrics:
        """Calculate deterministic quality indicators for a report."""
        report = self._report_repo.get_by_id(report_id)
        if not report:
            raise ValueError(f"Report '{report_id}' not found.")
        inv_id = report.investigation_id
        sources_linked = []
        for rs in self._report_repo.get_sources(report_id):
            s = self._src_repo.find_by_id(rs.source_id)
            if s:
                sources_linked.append(s)
        evidence_list = self._inv_repo.get_evidence_for_investigation(inv_id)
        findings_list = self._inv_repo.get_findings(inv_id)
        questions_list = self._inv_repo.get_questions(inv_id)
        concepts = []
        for ic in self._inv_repo.get_concepts(inv_id):
            c = self._concept_repo.find_by_id(ic.concept_id)
            if c:
                concepts.append(c)
        finding_evidence_map: dict[str, list[str]] = {}
        for f in findings_list:
            evs = self._inv_repo.get_evidence_for_finding(f.id)
            finding_evidence_map[f.id] = [e.id for e in evs]
        cpt_counts = {c.id: 1 for c in concepts}
        return ReportQualityAnalyzer.analyze(
            sources=sources_linked,
            evidence_list=evidence_list,
            findings_list=findings_list,
            finding_evidence_map=finding_evidence_map,
            questions=questions_list,
            concepts=concepts,
            concept_source_counts=cpt_counts,
        )

    def get_provenance_chain(self, report_id: str, finding_id: str) -> dict[str, Any]:
        """Build a traceable provenance chain: finding -> evidence -> source."""
        finding = self._inv_repo.get_finding(finding_id)
        if not finding:
            raise ValueError(f"Finding '{finding_id}' not found.")
        evidence_chain = []
        for ev in finding.supporting_evidence:
            src = self._src_repo.find_by_id(ev.source_id)
            evidence_chain.append({
                "evidence": ev.to_dict(),
                "source": src.to_dict() if src else None,
            })
        report = self._report_repo.get_by_id(report_id)
        return {
            "report": report.to_dict() if report else None,
            "finding": finding.to_dict(),
            "evidence_chain": evidence_chain,
        }

    # =========================================================================
    # Export
    # =========================================================================

    def export_markdown(self, report_id: str) -> str:
        """Export report as clean Markdown preserving all provenance."""
        return self._export_svc.export_markdown(report_id)

    # =========================================================================
    # Cross-Reference Counts
    # =========================================================================

    def count_reports_using_source(self, source_id: str) -> int:
        return self._report_repo.count_reports_using_source(source_id)

    def count_reports_using_evidence(self, evidence_id: str) -> int:
        return self._report_repo.count_reports_using_evidence(evidence_id)

    def count_reports_using_finding(self, finding_id: str) -> int:
        return self._report_repo.count_reports_using_finding(finding_id)

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _build_workspace(self, report: Report) -> dict[str, Any]:
        """Assemble a full workspace dict for the UI layer."""
        sections = self._report_repo.get_sections(report.id)
        sources = self._report_repo.get_sources(report.id)
        evidence = self._report_repo.get_evidence(report.id)
        findings = self._report_repo.get_findings(report.id)
        # Enrich sources with actual source model data
        enriched_sources = []
        source_citation_map: dict[str, str] = {}
        for rs in sources:
            s = self._src_repo.find_by_id(rs.source_id)
            enriched_sources.append({
                "citation_label": rs.citation_label,
                "position": rs.position,
                "source": s.to_dict() if s else {"id": rs.source_id, "title": "[Deleted Source]"},
            })
            source_citation_map[rs.source_id] = rs.citation_label
        # Enrich evidence
        enriched_evidence = []
        inv_evidence_map = {}
        for ie in self._inv_repo.get_evidence_for_investigation(report.investigation_id):
            inv_evidence_map[ie.id] = ie
        for re_ in evidence:
            ev = inv_evidence_map.get(re_.evidence_id)
            enriched_evidence.append({
                "citation_label": re_.citation_label,
                "position": re_.position,
                "section_id": re_.section_id,
                "evidence": ev.to_dict() if ev else {"id": re_.evidence_id, "statement": "[Deleted]"},
            })
        # Enrich findings
        enriched_findings = []
        for rf in findings:
            f = self._inv_repo.get_finding(rf.finding_id)
            enriched_findings.append({
                "position": rf.position,
                "section_id": rf.section_id,
                "finding": f.to_dict() if f else {"id": rf.finding_id, "title": "[Deleted]"},
            })
        return {
            "report": report.to_dict(),
            "sections": [s.to_dict() for s in sections],
            "sources": enriched_sources,
            "evidence": enriched_evidence,
            "findings": enriched_findings,
            "source_citation_map": source_citation_map,
        }
