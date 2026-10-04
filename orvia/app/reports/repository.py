"""
ReportRepository — persistence and relational access layer for Phase 10 Research Reports.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import DatabaseError, ValidationError
from orvia.app.models.base import _now_iso, _new_uuid
from orvia.app.reports.models import (
    Report,
    ReportSection,
    ReportSource,
    ReportEvidence,
    ReportFinding,
    ReportStatus,
)

logger = logging.getLogger(__name__)


class ReportRepository:
    """
    Handles SQLite CRUD operations for Reports, ReportSections,
    and associated provenance link records (ReportSource, ReportEvidence, ReportFinding).
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # =========================================================================
    # Report CRUD
    # =========================================================================

    def create(self, report: Report) -> Report:
        """Insert a new report record into the database."""
        report.validate()
        now = datetime.now(timezone.utc)
        report.created_at = now
        report.updated_at = now
        report.generated_at = now

        sql = """
        INSERT INTO reports (
            id, investigation_id, title, subtitle, summary,
            status, version, parent_report_id, metadata,
            created_at, updated_at, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            report.id,
            report.investigation_id,
            report.title,
            report.subtitle,
            report.summary,
            report.status,
            report.version,
            report.parent_report_id,
            json.dumps(report.metadata) if isinstance(report.metadata, dict) else "{}",
            report.created_at.isoformat(),
            report.updated_at.isoformat(),
            report.generated_at.isoformat(),
        )
        self._db.execute(sql, params)
        logger.debug("Created report: %s (v%d)", report.id, report.version)
        return report

    def get_by_id(self, report_id: str) -> Optional[Report]:
        """Fetch a single report by its ID."""
        sql = "SELECT * FROM reports WHERE id = ?;"
        row = self._db.fetchone(sql, (report_id,))
        if not row:
            return None
        return Report.from_dict(dict(row))

    def get_by_investigation(self, investigation_id: str) -> list[Report]:
        """Return all reports associated with an investigation ordered by version desc."""
        sql = """
        SELECT * FROM reports
        WHERE investigation_id = ?
        ORDER BY version DESC, updated_at DESC;
        """
        rows = self._db.fetchall(sql, (investigation_id,))
        return [Report.from_dict(dict(r)) for r in rows]

    def list(
        self,
        status: Optional[str] = None,
        search_query: Optional[str] = None,
        investigation_id: Optional[str] = None,
        sort_by: str = "updated_at",
        order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> list[Report]:
        """List reports with optional filtering, search, and sorting."""
        conditions: list[str] = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status.upper())

        if investigation_id:
            conditions.append("investigation_id = ?")
            params.append(investigation_id)

        if search_query and search_query.strip():
            q_clean = f"%{search_query.strip()}%"
            conditions.append("(title LIKE ? OR subtitle LIKE ? OR summary LIKE ?)")
            params.extend([q_clean, q_clean, q_clean])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Whitelist sort column to prevent SQL injection
        allowed_sorts = {"created_at", "updated_at", "title", "version", "status"}
        col = sort_by if sort_by in allowed_sorts else "updated_at"
        direction = "ASC" if order.lower() == "asc" else "DESC"

        sql = f"""
        SELECT * FROM reports
        {where_clause}
        ORDER BY {col} {direction}
        LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])

        rows = self._db.fetchall(sql, tuple(params))
        return [Report.from_dict(dict(r)) for r in rows]

    def update(self, report: Report) -> Report:
        """Update mutable fields of an existing report."""
        report.validate()
        report.updated_at = datetime.now(timezone.utc)

        sql = """
        UPDATE reports
        SET title = ?, subtitle = ?, summary = ?,
            status = ?, version = ?, parent_report_id = ?,
            metadata = ?, updated_at = ?
        WHERE id = ?;
        """
        params = (
            report.title,
            report.subtitle,
            report.summary,
            report.status,
            report.version,
            report.parent_report_id,
            json.dumps(report.metadata) if isinstance(report.metadata, dict) else "{}",
            report.updated_at.isoformat(),
            report.id,
        )
        self._db.execute(sql, params)
        logger.debug("Updated report: %s", report.id)
        return report

    def delete(self, report_id: str) -> bool:
        """Delete a report and all its cascade-linked sections and join rows."""
        sql = "DELETE FROM reports WHERE id = ?;"
        cursor = self._db.execute(sql, (report_id,))
        return cursor.rowcount > 0

    def count(self, status: Optional[str] = None) -> int:
        """Return total reports count, optionally filtered by status."""
        if status:
            sql = "SELECT COUNT(*) as cnt FROM reports WHERE status = ?;"
            row = self._db.fetchone(sql, (status.upper(),))
        else:
            sql = "SELECT COUNT(*) as cnt FROM reports;"
            row = self._db.fetchone(sql)
        return int(row["cnt"]) if row else 0

    # =========================================================================
    # Versioning
    # =========================================================================

    def create_version(self, report_id: str, new_status: str = "DRAFT") -> Report:
        """
        Create a new report version as a deep snapshot clone of an existing report,
        preserving all sections and provenance links, but incrementing version number.
        """
        original = self.get_by_id(report_id)
        if not original:
            raise ValidationError(f"Report '{report_id}' not found.", field="report_id")

        # Determine next version number for this investigation lineage
        sql_ver = """
        SELECT MAX(version) as max_v FROM reports
        WHERE investigation_id = ?;
        """
        row = self._db.fetchone(sql_ver, (original.investigation_id,))
        max_v = int(row["max_v"]) if row and row["max_v"] is not None else original.version
        next_version = max_v + 1

        new_report = Report(
            id=_new_uuid(),
            investigation_id=original.investigation_id,
            title=original.title,
            subtitle=original.subtitle,
            summary=original.summary,
            status=new_status.upper(),
            version=next_version,
            parent_report_id=original.id,
            metadata=dict(original.metadata),
        )
        self.create(new_report)

        # Clone sections with ID mapping
        old_sections = self.get_sections(original.id)
        sec_id_map: dict[str, str] = {}
        for old_sec in old_sections:
            new_sec_id = _new_uuid()
            sec_id_map[old_sec.id] = new_sec_id
            new_sec = ReportSection(
                id=new_sec_id,
                report_id=new_report.id,
                section_type=old_sec.section_type,
                title=old_sec.title,
                position=old_sec.position,
                content=old_sec.content,
                metadata=dict(old_sec.metadata),
            )
            self.add_section(new_sec)

        # Clone report sources
        old_sources = self.get_sources(original.id)
        for s in old_sources:
            self.link_source(
                ReportSource(
                    report_id=new_report.id,
                    source_id=s.source_id,
                    citation_label=s.citation_label,
                    position=s.position,
                )
            )

        # Clone report evidence
        old_evidence = self.get_evidence(original.id)
        for e in old_evidence:
            mapped_sec_id = sec_id_map.get(e.section_id) if e.section_id else None
            self.link_evidence(
                ReportEvidence(
                    report_id=new_report.id,
                    evidence_id=e.evidence_id,
                    citation_label=e.citation_label,
                    section_id=mapped_sec_id,
                    position=e.position,
                )
            )

        # Clone report findings
        old_findings = self.get_findings(original.id)
        for f in old_findings:
            mapped_sec_id = sec_id_map.get(f.section_id) if f.section_id else None
            self.link_finding(
                ReportFinding(
                    report_id=new_report.id,
                    finding_id=f.finding_id,
                    section_id=mapped_sec_id,
                    position=f.position,
                )
            )

        logger.info(
            "Created report version %d (id: %s) from %s",
            next_version,
            new_report.id,
            original.id,
        )
        return new_report

    def get_versions(self, report_id: str) -> list[Report]:
        """
        Return all versions belonging to the investigation of this report,
        ordered by version ascending.
        """
        report = self.get_by_id(report_id)
        if not report:
            return []
        sql = """
        SELECT * FROM reports
        WHERE investigation_id = ?
        ORDER BY version ASC;
        """
        rows = self._db.fetchall(sql, (report.investigation_id,))
        return [Report.from_dict(dict(r)) for r in rows]

    # =========================================================================
    # Report Sections CRUD
    # =========================================================================

    def add_section(self, section: ReportSection) -> ReportSection:
        """Add a section to a report."""
        section.validate()
        now = datetime.now(timezone.utc)
        section.created_at = now
        section.updated_at = now

        sql = """
        INSERT INTO report_sections (
            id, report_id, section_type, title, position,
            content, metadata, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            section.id,
            section.report_id,
            section.section_type.upper(),
            section.title,
            section.position,
            section.content,
            json.dumps(section.metadata) if isinstance(section.metadata, dict) else "{}",
            section.created_at.isoformat(),
            section.updated_at.isoformat(),
        )
        self._db.execute(sql, params)
        return section

    def get_sections(self, report_id: str) -> list[ReportSection]:
        """Fetch all sections for a report ordered by position ascending."""
        sql = """
        SELECT * FROM report_sections
        WHERE report_id = ?
        ORDER BY position ASC, created_at ASC;
        """
        rows = self._db.fetchall(sql, (report_id,))
        return [ReportSection.from_dict(dict(r)) for r in rows]

    def get_section_by_id(self, section_id: str) -> Optional[ReportSection]:
        """Fetch a specific section by its ID."""
        sql = "SELECT * FROM report_sections WHERE id = ?;"
        row = self._db.fetchone(sql, (section_id,))
        if not row:
            return None
        return ReportSection.from_dict(dict(row))

    def update_section(self, section: ReportSection) -> ReportSection:
        """Update an existing report section's title, content, or position."""
        section.validate()
        section.updated_at = datetime.now(timezone.utc)

        sql = """
        UPDATE report_sections
        SET title = ?, content = ?, position = ?,
            section_type = ?, metadata = ?, updated_at = ?
        WHERE id = ?;
        """
        params = (
            section.title,
            section.content,
            section.position,
            section.section_type.upper(),
            json.dumps(section.metadata) if isinstance(section.metadata, dict) else "{}",
            section.updated_at.isoformat(),
            section.id,
        )
        self._db.execute(sql, params)
        return section

    def delete_section(self, section_id: str) -> bool:
        """Delete a report section."""
        sql = "DELETE FROM report_sections WHERE id = ?;"
        cursor = self._db.execute(sql, (section_id,))
        return cursor.rowcount > 0

    def reorder_sections(self, report_id: str, section_ids: list[str]) -> bool:
        """Update position indexes for an ordered list of section IDs."""
        for pos, sec_id in enumerate(section_ids):
            self._db.execute(
                "UPDATE report_sections SET position = ? WHERE id = ? AND report_id = ?;",
                (pos, sec_id, report_id),
            )
        return True

    # =========================================================================
    # Report Provenance Links (Sources, Evidence, Findings)
    # =========================================================================

    def link_source(self, report_source: ReportSource) -> None:
        """Link a source to a report with citation label."""
        sql = """
        INSERT OR REPLACE INTO report_sources (report_id, source_id, citation_label, position)
        VALUES (?, ?, ?, ?);
        """
        self._db.execute(
            sql,
            (
                report_source.report_id,
                report_source.source_id,
                report_source.citation_label,
                report_source.position,
            ),
        )

    def get_sources(self, report_id: str) -> list[ReportSource]:
        """Fetch all linked sources for a report ordered by position."""
        sql = "SELECT * FROM report_sources WHERE report_id = ? ORDER BY position ASC;"
        rows = self._db.fetchall(sql, (report_id,))
        return [ReportSource.from_dict(dict(r)) for r in rows]

    def link_evidence(self, report_evidence: ReportEvidence) -> None:
        """Link an evidence item to a report with citation label."""
        sql = """
        INSERT OR REPLACE INTO report_evidence (report_id, evidence_id, citation_label, section_id, position)
        VALUES (?, ?, ?, ?, ?);
        """
        self._db.execute(
            sql,
            (
                report_evidence.report_id,
                report_evidence.evidence_id,
                report_evidence.citation_label,
                report_evidence.section_id,
                report_evidence.position,
            ),
        )

    def get_evidence(self, report_id: str) -> list[ReportEvidence]:
        """Fetch all linked evidence for a report ordered by position."""
        sql = "SELECT * FROM report_evidence WHERE report_id = ? ORDER BY position ASC;"
        rows = self._db.fetchall(sql, (report_id,))
        return [ReportEvidence.from_dict(dict(r)) for r in rows]

    def link_finding(self, report_finding: ReportFinding) -> None:
        """Link a finding to a report."""
        sql = """
        INSERT OR REPLACE INTO report_findings (report_id, finding_id, section_id, position)
        VALUES (?, ?, ?, ?);
        """
        self._db.execute(
            sql,
            (
                report_finding.report_id,
                report_finding.finding_id,
                report_finding.section_id,
                report_finding.position,
            ),
        )

    def get_findings(self, report_id: str) -> list[ReportFinding]:
        """Fetch all linked findings for a report ordered by position."""
        sql = "SELECT * FROM report_findings WHERE report_id = ? ORDER BY position ASC;"
        rows = self._db.fetchall(sql, (report_id,))
        return [ReportFinding.from_dict(dict(r)) for r in rows]

    # =========================================================================
    # Cross-Reference Count Queries (Integration points)
    # =========================================================================

    def count_reports_using_finding(self, finding_id: str) -> int:
        """Return the number of reports that link to this finding."""
        sql = "SELECT COUNT(DISTINCT report_id) as cnt FROM report_findings WHERE finding_id = ?;"
        row = self._db.fetchone(sql, (finding_id,))
        return int(row["cnt"]) if row else 0

    def count_reports_using_evidence(self, evidence_id: str) -> int:
        """Return the number of reports that cite this evidence."""
        sql = "SELECT COUNT(DISTINCT report_id) as cnt FROM report_evidence WHERE evidence_id = ?;"
        row = self._db.fetchone(sql, (evidence_id,))
        return int(row["cnt"]) if row else 0

    def count_reports_using_source(self, source_id: str) -> int:
        """Return the number of reports that cite this source."""
        sql = "SELECT COUNT(DISTINCT report_id) as cnt FROM report_sources WHERE source_id = ?;"
        row = self._db.fetchone(sql, (source_id,))
        return int(row["cnt"]) if row else 0
