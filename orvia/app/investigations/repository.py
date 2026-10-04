"""
InvestigationRepository — Persistence and relational queries for investigations.
Phase 8 — Investigation Workspace
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import RepositoryError, ValidationError
from orvia.app.investigations.models import (
    ActivityType,
    ConceptRole,
    EvidenceType,
    FindingStatus,
    InvestigationActivity,
    InvestigationConcept,
    InvestigationEvidence,
    InvestigationFinding,
    InvestigationNote,
    InvestigationQuestion,
    InvestigationSource,
    InvestigationStats,
    InvestigationStatus,
    NoteType,
    QuestionStatus,
    SourceRelationshipType,
    VALID_STATUS_TRANSITIONS,
)
from orvia.app.models.investigation import Investigation, VALID_STATUSES
from orvia.app.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class InvestigationRepository(BaseRepository[Investigation]):
    """
    Complete repository for investigations, attached research sources,
    tracked concepts, recorded evidence, questions, findings, notes,
    and verifiable activity logs.
    """

    TABLE = "investigations"

    def __init__(self, db: DatabaseManager) -> None:
        super().__init__(db)

    # ------------------------------------------------------------------
    # Base CRUD operations
    # ------------------------------------------------------------------

    def save(self, investigation: Investigation) -> Investigation:
        """Insert or update an investigation record."""
        investigation.validate()
        now = datetime.now(tz=timezone.utc).isoformat()
        metadata_str = (
            json.dumps(investigation.metadata)
            if investigation.metadata
            else "{}"
        )
        completed_at_str = (
            investigation.completed_at.isoformat()
            if isinstance(investigation.completed_at, datetime)
            else (investigation.completed_at or None)
        )
        norm_status = (
            investigation.status.lower()
            if isinstance(investigation.status, str)
            else str(investigation.status.value)
        )

        sql = """
            INSERT INTO investigations (
                id, title, research_question, description, status,
                notes, completed_at, metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                research_question = excluded.research_question,
                description = excluded.description,
                status = excluded.status,
                notes = excluded.notes,
                completed_at = excluded.completed_at,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at;
        """
        try:
            self._db.execute(
                sql,
                (
                    investigation.id,
                    investigation.title,
                    investigation.research_question,
                    investigation.description or "",
                    norm_status,
                    investigation.notes,
                    completed_at_str,
                    metadata_str,
                    investigation.created_at.isoformat(),
                    now,
                ),
            )
            logger.debug("Saved Investigation id=%s title=%s", investigation.id, investigation.title)
            return investigation
        except Exception as exc:
            raise RepositoryError(f"Failed to save Investigation: {exc}") from exc

    def find_by_id(self, id: str) -> Optional[Investigation]:
        """Fetch investigation by primary key."""
        row = self._db.fetchone("SELECT * FROM investigations WHERE id = ?;", (id,))
        if row is None:
            return None
        return Investigation.from_dict(row)

    def find_all(self, limit: int = 100, offset: int = 0) -> list[Investigation]:
        """Return paginated investigations ordered by updated_at descending."""
        rows = self._db.fetchall(
            "SELECT * FROM investigations ORDER BY updated_at DESC LIMIT ? OFFSET ?;",
            (limit, offset),
        )
        return [Investigation.from_dict(r) for r in rows]

    def delete(self, id: str) -> bool:
        """Permanently delete an investigation and all child relations via cascade."""
        try:
            cursor = self._db.execute("DELETE FROM investigations WHERE id = ?;", (id,))
            return cursor.rowcount > 0
        except Exception as exc:
            raise RepositoryError(f"Failed to delete Investigation id={id}: {exc}") from exc

    def count(self, status: Optional[str] = None) -> int:
        """Count investigations, optionally filtered by status."""
        if status:
            norm = status.lower()
            row = self._db.fetchone(
                "SELECT COUNT(*) AS cnt FROM investigations WHERE status = ?;",
                (norm,),
            )
        else:
            row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM investigations;")
        return int(row["cnt"]) if row else 0

    def find_by_status(self, status: str) -> list[Investigation]:
        """Return all investigations with matching status."""
        norm = status.lower()
        rows = self._db.fetchall(
            "SELECT * FROM investigations WHERE status = ? ORDER BY updated_at DESC;",
            (norm,),
        )
        return [Investigation.from_dict(r) for r in rows]

    def update_status(self, investigation_id: str, status: str) -> None:
        """Update status and refresh updated_at, recording completed_at if completed."""
        norm_status = status.lower()
        valid_lower = ("draft", "active", "paused", "completed", "archived")
        if norm_status not in valid_lower:
            raise RepositoryError(
                f"Invalid status {status!r}. Must be one of {VALID_STATUSES!r}."
            )
        now = datetime.now(tz=timezone.utc).isoformat()
        completed_at = now if norm_status == "completed" else None
        try:
            if norm_status == "completed":
                self._db.execute(
                    """
                    UPDATE investigations
                    SET status = ?, updated_at = ?, completed_at = COALESCE(completed_at, ?)
                    WHERE id = ?;
                    """,
                    (norm_status, now, completed_at, investigation_id),
                )
            else:
                self._db.execute(
                    "UPDATE investigations SET status = ?, updated_at = ? WHERE id = ?;",
                    (norm_status, now, investigation_id),
                )
        except Exception as exc:
            raise RepositoryError(f"Failed to update status for Investigation {investigation_id}: {exc}") from exc

    def search(
        self,
        query: str = "",
        status: Optional[str] = None,
        sort_by: str = "updated_at",
        order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> list[Investigation]:
        """
        Search and filter investigations by title, research question, description,
        and lifecycle status.
        """
        conditions = []
        params: list[Any] = []

        if status and status.lower() != "all":
            conditions.append("status = ?")
            params.append(status.lower())

        if query and query.strip():
            term = f"%{query.strip()}%"
            conditions.append(
                "(title LIKE ? OR research_question LIKE ? OR description LIKE ?)"
            )
            params.extend([term, term, term])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        valid_sort_cols = {"updated_at", "created_at", "title", "status"}
        col = sort_by if sort_by in valid_sort_cols else "updated_at"
        direction = "ASC" if order.lower() == "asc" else "DESC"

        sql = f"""
            SELECT * FROM investigations
            {where_clause}
            ORDER BY {col} {direction}
            LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])
        rows = self._db.fetchall(sql, params)
        return [Investigation.from_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Source Relationships
    # ------------------------------------------------------------------

    def add_source(
        self,
        investigation_id: str,
        source_id: str,
        relationship_type: str = SourceRelationshipType.RELEVANT.value,
        notes: Optional[str] = None,
    ) -> None:
        """Attach a research source to an investigation."""
        now = datetime.now(tz=timezone.utc).isoformat()
        rel_type = SourceRelationshipType.from_str(relationship_type).value
        sql = """
            INSERT INTO investigation_sources (
                investigation_id, source_id, relationship_type, notes, added_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id, source_id) DO UPDATE SET
                relationship_type = excluded.relationship_type,
                notes = excluded.notes;
        """
        try:
            self._db.execute(sql, (investigation_id, source_id, rel_type, notes, now))
            self._touch_investigation(investigation_id)
        except Exception as exc:
            raise RepositoryError(f"Failed to add source to investigation: {exc}") from exc

    def remove_source(self, investigation_id: str, source_id: str) -> bool:
        """Remove a research source from an investigation."""
        try:
            cursor = self._db.execute(
                "DELETE FROM investigation_sources WHERE investigation_id = ? AND source_id = ?;",
                (investigation_id, source_id),
            )
            if cursor.rowcount > 0:
                self._touch_investigation(investigation_id)
                return True
            return False
        except Exception as exc:
            raise RepositoryError(f"Failed to remove source from investigation: {exc}") from exc

    def get_sources(self, investigation_id: str) -> list[InvestigationSource]:
        """Return all sources attached to an investigation, joined with source metadata."""
        sql = """
            SELECT
                inv_s.investigation_id,
                inv_s.source_id,
                inv_s.relationship_type,
                inv_s.notes,
                inv_s.added_at,
                s.title AS source_title,
                COALESCE(s.file_type, s.source_type) AS source_file_type,
                COALESCE(s.word_count, 0) AS source_word_count,
                (
                    SELECT COUNT(*)
                    FROM investigation_evidence ie
                    WHERE ie.investigation_id = inv_s.investigation_id
                      AND ie.source_id = inv_s.source_id
                ) AS evidence_count
            FROM investigation_sources inv_s
            JOIN sources s ON s.id = inv_s.source_id
            WHERE inv_s.investigation_id = ?
            ORDER BY inv_s.added_at DESC;
        """
        rows = self._db.fetchall(sql, (investigation_id,))
        results = []
        for r in rows:
            results.append(
                InvestigationSource(
                    investigation_id=r["investigation_id"],
                    source_id=r["source_id"],
                    relationship_type=r["relationship_type"],
                    notes=r["notes"],
                    added_at=datetime.fromisoformat(r["added_at"]),
                    source_title=r["source_title"] or "Untitled Source",
                    source_file_type=r["source_file_type"] or "document",
                    source_word_count=int(r["source_word_count"]),
                    evidence_count=int(r["evidence_count"]),
                )
            )
        return results

    def has_source(self, investigation_id: str, source_id: str) -> bool:
        """Check if source is attached to investigation."""
        row = self._db.fetchone(
            "SELECT 1 FROM investigation_sources WHERE investigation_id = ? AND source_id = ?;",
            (investigation_id, source_id),
        )
        return row is not None

    # ------------------------------------------------------------------
    # Concept Relationships
    # ------------------------------------------------------------------

    def add_concept(
        self,
        investigation_id: str,
        concept_id: str,
        role: str = ConceptRole.KEY_CONCEPT.value,
        notes: Optional[str] = None,
    ) -> None:
        """Track a concept in an investigation."""
        now = datetime.now(tz=timezone.utc).isoformat()
        role_val = ConceptRole.from_str(role).value
        sql = """
            INSERT INTO investigation_concepts (
                investigation_id, concept_id, role, notes, added_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(investigation_id, concept_id) DO UPDATE SET
                role = excluded.role,
                notes = excluded.notes;
        """
        try:
            self._db.execute(sql, (investigation_id, concept_id, role_val, notes, now))
            self._touch_investigation(investigation_id)
        except Exception as exc:
            raise RepositoryError(f"Failed to add concept to investigation: {exc}") from exc

    def remove_concept(self, investigation_id: str, concept_id: str) -> bool:
        """Untrack a concept from an investigation."""
        try:
            cursor = self._db.execute(
                "DELETE FROM investigation_concepts WHERE investigation_id = ? AND concept_id = ?;",
                (investigation_id, concept_id),
            )
            if cursor.rowcount > 0:
                self._touch_investigation(investigation_id)
                return True
            return False
        except Exception as exc:
            raise RepositoryError(f"Failed to remove concept from investigation: {exc}") from exc

    def get_concepts(self, investigation_id: str) -> list[InvestigationConcept]:
        """Return all tracked concepts joined with concept metadata."""
        sql = """
            SELECT
                inv_c.investigation_id,
                inv_c.concept_id,
                inv_c.role,
                inv_c.notes,
                inv_c.added_at,
                c.name AS concept_name,
                c.frequency AS concept_frequency,
                COALESCE(csl_agg.src_count, 0) AS concept_source_count
            FROM investigation_concepts inv_c
            JOIN concepts c ON c.id = inv_c.concept_id
            LEFT JOIN (
                SELECT concept_id, COUNT(DISTINCT source_id) AS src_count
                FROM concept_source_links
                GROUP BY concept_id
            ) csl_agg ON csl_agg.concept_id = c.id
            WHERE inv_c.investigation_id = ?
            ORDER BY inv_c.added_at DESC;
        """
        rows = self._db.fetchall(sql, (investigation_id,))
        results = []
        for r in rows:
            results.append(
                InvestigationConcept(
                    investigation_id=r["investigation_id"],
                    concept_id=r["concept_id"],
                    role=r["role"],
                    notes=r["notes"],
                    added_at=datetime.fromisoformat(r["added_at"]),
                    concept_name=r["concept_name"],
                    concept_frequency=int(r["concept_frequency"] or 0),
                    concept_source_count=int(r["concept_source_count"] or 0),
                )
            )
        return results

    def has_concept(self, investigation_id: str, concept_id: str) -> bool:
        """Check if concept is tracked in investigation."""
        row = self._db.fetchone(
            "SELECT 1 FROM investigation_concepts WHERE investigation_id = ? AND concept_id = ?;",
            (investigation_id, concept_id),
        )
        return row is not None

    # ------------------------------------------------------------------
    # Evidence Operations
    # ------------------------------------------------------------------

    def save_evidence(self, evidence: InvestigationEvidence) -> InvestigationEvidence:
        """Insert or replace an evidence item."""
        evidence.validate()
        now = datetime.now(tz=timezone.utc).isoformat()
        sql = """
            INSERT INTO investigation_evidence (
                id, investigation_id, source_id, title, statement, excerpt,
                location, evidence_type, confidence, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                statement = excluded.statement,
                excerpt = excluded.excerpt,
                location = excluded.location,
                evidence_type = excluded.evidence_type,
                confidence = excluded.confidence,
                notes = excluded.notes,
                updated_at = excluded.updated_at;
        """
        try:
            self._db.execute(
                sql,
                (
                    evidence.id,
                    evidence.investigation_id,
                    evidence.source_id,
                    evidence.title or "",
                    evidence.statement,
                    evidence.excerpt or "",
                    evidence.location or "",
                    EvidenceType.from_str(evidence.evidence_type).value,
                    float(evidence.confidence),
                    evidence.notes,
                    evidence.created_at.isoformat(),
                    now,
                ),
            )
            self._touch_investigation(evidence.investigation_id)
            return evidence
        except Exception as exc:
            raise RepositoryError(f"Failed to save InvestigationEvidence: {exc}") from exc

    def get_evidence(self, evidence_id: str) -> Optional[InvestigationEvidence]:
        """Fetch single evidence item by ID with source metadata and linked findings."""
        sql = """
            SELECT
                ie.*,
                s.title AS source_title,
                COALESCE(s.file_type, s.source_type) AS source_file_type
            FROM investigation_evidence ie
            JOIN sources s ON s.id = ie.source_id
            WHERE ie.id = ?;
        """
        row = self._db.fetchone(sql, (evidence_id,))
        if row is None:
            return None
        ev = InvestigationEvidence.from_dict(row)
        ev.linked_finding_ids = self.get_findings_for_evidence(evidence_id)
        return ev

    def get_evidence_for_investigation(
        self,
        investigation_id: str,
        evidence_type: Optional[str] = None,
    ) -> list[InvestigationEvidence]:
        """Fetch all evidence items for an investigation with provenance details."""
        conditions = ["ie.investigation_id = ?"]
        params: list[Any] = [investigation_id]

        if evidence_type and evidence_type.upper() != "ALL":
            conditions.append("ie.evidence_type = ?")
            params.append(evidence_type.upper())

        sql = f"""
            SELECT
                ie.*,
                s.title AS source_title,
                COALESCE(s.file_type, s.source_type) AS source_file_type
            FROM investigation_evidence ie
            JOIN sources s ON s.id = ie.source_id
            WHERE {' AND '.join(conditions)}
            ORDER BY ie.created_at DESC;
        """
        rows = self._db.fetchall(sql, params)
        results = []
        for r in rows:
            ev = InvestigationEvidence.from_dict(r)
            ev.linked_finding_ids = self.get_findings_for_evidence(ev.id)
            results.append(ev)
        return results

    def delete_evidence(self, evidence_id: str) -> bool:
        """Delete an evidence item."""
        try:
            ev = self.get_evidence(evidence_id)
            inv_id = ev.investigation_id if ev else None
            cursor = self._db.execute(
                "DELETE FROM investigation_evidence WHERE id = ?;", (evidence_id,)
            )
            if cursor.rowcount > 0 and inv_id:
                self._touch_investigation(inv_id)
                return True
            return False
        except Exception as exc:
            raise RepositoryError(f"Failed to delete evidence {evidence_id}: {exc}") from exc

    def count_evidence(self, investigation_id: str) -> int:
        """Return total evidence count for investigation."""
        row = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_evidence WHERE investigation_id = ?;",
            (investigation_id,),
        )
        return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # Research Notes Operations
    # ------------------------------------------------------------------

    def save_note(self, note: InvestigationNote) -> InvestigationNote:
        """Save or update a research note."""
        note.validate()
        now = datetime.now(tz=timezone.utc).isoformat()
        sql = """
            INSERT INTO investigation_notes (
                id, investigation_id, title, content, note_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                note_type = excluded.note_type,
                updated_at = excluded.updated_at;
        """
        try:
            self._db.execute(
                sql,
                (
                    note.id,
                    note.investigation_id,
                    note.title or "",
                    note.content,
                    NoteType.from_str(note.note_type).value,
                    note.created_at.isoformat(),
                    now,
                ),
            )
            self._touch_investigation(note.investigation_id)
            return note
        except Exception as exc:
            raise RepositoryError(f"Failed to save InvestigationNote: {exc}") from exc

    def get_notes(self, investigation_id: str) -> list[InvestigationNote]:
        """Fetch all notes for an investigation ordered newest first."""
        rows = self._db.fetchall(
            "SELECT * FROM investigation_notes WHERE investigation_id = ? ORDER BY created_at DESC;",
            (investigation_id,),
        )
        return [InvestigationNote.from_dict(r) for r in rows]

    def delete_note(self, note_id: str) -> bool:
        """Delete a research note."""
        try:
            row = self._db.fetchone(
                "SELECT investigation_id FROM investigation_notes WHERE id = ?;", (note_id,)
            )
            inv_id = row["investigation_id"] if row else None
            cursor = self._db.execute(
                "DELETE FROM investigation_notes WHERE id = ?;", (note_id,)
            )
            if cursor.rowcount > 0 and inv_id:
                self._touch_investigation(inv_id)
                return True
            return False
        except Exception as exc:
            raise RepositoryError(f"Failed to delete note {note_id}: {exc}") from exc

    # ------------------------------------------------------------------
    # Open Questions Operations
    # ------------------------------------------------------------------

    def save_question(self, question: InvestigationQuestion) -> InvestigationQuestion:
        """Save or update an open research question."""
        question.validate()
        now = datetime.now(tz=timezone.utc).isoformat()
        res_at = question.resolved_at.isoformat() if question.resolved_at else None
        sql = """
            INSERT INTO investigation_questions (
                id, investigation_id, question, status, resolution_note,
                resolved_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                question = excluded.question,
                status = excluded.status,
                resolution_note = excluded.resolution_note,
                resolved_at = excluded.resolved_at,
                updated_at = excluded.updated_at;
        """
        try:
            self._db.execute(
                sql,
                (
                    question.id,
                    question.investigation_id,
                    question.question,
                    QuestionStatus.from_str(question.status).value,
                    question.resolution_note,
                    res_at,
                    question.created_at.isoformat(),
                    now,
                ),
            )
            self._touch_investigation(question.investigation_id)
            return question
        except Exception as exc:
            raise RepositoryError(f"Failed to save InvestigationQuestion: {exc}") from exc

    def get_question(self, question_id: str) -> Optional[InvestigationQuestion]:
        """Fetch question by ID."""
        row = self._db.fetchone(
            "SELECT * FROM investigation_questions WHERE id = ?;", (question_id,)
        )
        if row is None:
            return None
        return InvestigationQuestion.from_dict(row)

    def get_questions(
        self,
        investigation_id: str,
        status: Optional[str] = None,
    ) -> list[InvestigationQuestion]:
        """Return all questions for an investigation, optionally filtered by status."""
        conditions = ["investigation_id = ?"]
        params: list[Any] = [investigation_id]

        if status and status.upper() != "ALL":
            conditions.append("status = ?")
            params.append(status.upper())

        sql = f"""
            SELECT * FROM investigation_questions
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC;
        """
        rows = self._db.fetchall(sql, params)
        return [InvestigationQuestion.from_dict(r) for r in rows]

    def resolve_question(
        self,
        question_id: str,
        resolution_note: str,
    ) -> InvestigationQuestion:
        """Mark a question as RESOLVED with a resolution note."""
        now = datetime.now(tz=timezone.utc).isoformat()
        sql = """
            UPDATE investigation_questions
            SET status = 'RESOLVED', resolution_note = ?, resolved_at = ?, updated_at = ?
            WHERE id = ?;
        """
        try:
            self._db.execute(sql, (resolution_note, now, now, question_id))
            q = self.get_question(question_id)
            if q:
                self._touch_investigation(q.investigation_id)
                return q
            raise RepositoryError(f"Question {question_id} not found.")
        except Exception as exc:
            raise RepositoryError(f"Failed to resolve question {question_id}: {exc}") from exc

    def delete_question(self, question_id: str) -> bool:
        """Delete an open or resolved question."""
        try:
            q = self.get_question(question_id)
            inv_id = q.investigation_id if q else None
            cursor = self._db.execute(
                "DELETE FROM investigation_questions WHERE id = ?;", (question_id,)
            )
            if cursor.rowcount > 0 and inv_id:
                self._touch_investigation(inv_id)
                return True
            return False
        except Exception as exc:
            raise RepositoryError(f"Failed to delete question {question_id}: {exc}") from exc

    # ------------------------------------------------------------------
    # Research Findings Operations
    # ------------------------------------------------------------------

    def save_finding(self, finding: InvestigationFinding) -> InvestigationFinding:
        """Save or update a research finding."""
        finding.validate()
        now = datetime.now(tz=timezone.utc).isoformat()
        sql = """
            INSERT INTO investigation_findings (
                id, investigation_id, title, statement, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                statement = excluded.statement,
                status = excluded.status,
                updated_at = excluded.updated_at;
        """
        try:
            self._db.execute(
                sql,
                (
                    finding.id,
                    finding.investigation_id,
                    finding.title,
                    finding.statement,
                    FindingStatus.from_str(finding.status).value,
                    finding.created_at.isoformat(),
                    now,
                ),
            )
            self._touch_investigation(finding.investigation_id)
            return finding
        except Exception as exc:
            raise RepositoryError(f"Failed to save InvestigationFinding: {exc}") from exc

    def get_finding(self, finding_id: str) -> Optional[InvestigationFinding]:
        """Fetch finding by ID with supporting evidence items."""
        sql = "SELECT * FROM investigation_findings WHERE id = ?;"
        row = self._db.fetchone(sql, (finding_id,))
        if row is None:
            return None
        finding = InvestigationFinding.from_dict(row)
        finding.supporting_evidence = self.get_evidence_for_finding(finding_id)
        finding.supporting_evidence_count = len(finding.supporting_evidence)
        src_set = {e.source_id for e in finding.supporting_evidence}
        finding.supporting_sources_count = len(src_set)
        return finding

    def get_findings(
        self,
        investigation_id: str,
        status: Optional[str] = None,
    ) -> list[InvestigationFinding]:
        """Fetch all findings for an investigation with supporting counts and items."""
        conditions = ["investigation_id = ?"]
        params: list[Any] = [investigation_id]

        if status and status.upper() != "ALL":
            conditions.append("status = ?")
            params.append(status.upper())

        sql = f"""
            SELECT * FROM investigation_findings
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC;
        """
        rows = self._db.fetchall(sql, params)
        findings = []
        for r in rows:
            f = InvestigationFinding.from_dict(r)
            f.supporting_evidence = self.get_evidence_for_finding(f.id)
            f.supporting_evidence_count = len(f.supporting_evidence)
            f.supporting_sources_count = len({e.source_id for e in f.supporting_evidence})
            findings.append(f)
        return findings

    def delete_finding(self, finding_id: str) -> bool:
        """Delete a finding."""
        try:
            f = self.get_finding(finding_id)
            inv_id = f.investigation_id if f else None
            cursor = self._db.execute(
                "DELETE FROM investigation_findings WHERE id = ?;", (finding_id,)
            )
            if cursor.rowcount > 0 and inv_id:
                self._touch_investigation(inv_id)
                return True
            return False
        except Exception as exc:
            raise RepositoryError(f"Failed to delete finding {finding_id}: {exc}") from exc

    def link_finding_evidence(self, finding_id: str, evidence_id: str) -> bool:
        """Link an evidence item to a research finding to support provenance."""
        now = datetime.now(tz=timezone.utc).isoformat()
        sql = """
            INSERT OR IGNORE INTO investigation_finding_evidence (
                finding_id, evidence_id, added_at
            ) VALUES (?, ?, ?);
        """
        try:
            cursor = self._db.execute(sql, (finding_id, evidence_id, now))
            # Auto-update status to SUPPORTED if currently DRAFT/NEEDS_EVIDENCE
            self._db.execute(
                """
                UPDATE investigation_findings
                SET status = 'SUPPORTED', updated_at = ?
                WHERE id = ? AND status IN ('DRAFT', 'NEEDS_EVIDENCE');
                """,
                (now, finding_id),
            )
            return cursor.rowcount > 0
        except Exception as exc:
            raise RepositoryError(f"Failed to link evidence to finding: {exc}") from exc

    def unlink_finding_evidence(self, finding_id: str, evidence_id: str) -> bool:
        """Unlink an evidence item from a finding."""
        try:
            cursor = self._db.execute(
                "DELETE FROM investigation_finding_evidence WHERE finding_id = ? AND evidence_id = ?;",
                (finding_id, evidence_id),
            )
            # If no supporting evidence remains, mark as NEEDS_EVIDENCE
            remaining = self.get_evidence_for_finding(finding_id)
            if not remaining:
                now = datetime.now(tz=timezone.utc).isoformat()
                self._db.execute(
                    "UPDATE investigation_findings SET status = 'NEEDS_EVIDENCE', updated_at = ? WHERE id = ?;",
                    (now, finding_id),
                )
            return cursor.rowcount > 0
        except Exception as exc:
            raise RepositoryError(f"Failed to unlink evidence from finding: {exc}") from exc

    def get_evidence_for_finding(self, finding_id: str) -> list[InvestigationEvidence]:
        """Fetch all evidence items linked to a given finding."""
        sql = """
            SELECT
                ie.*,
                s.title AS source_title,
                COALESCE(s.file_type, s.source_type) AS source_file_type
            FROM investigation_finding_evidence ife
            JOIN investigation_evidence ie ON ie.id = ife.evidence_id
            JOIN sources s ON s.id = ie.source_id
            WHERE ife.finding_id = ?
            ORDER BY ife.added_at ASC;
        """
        rows = self._db.fetchall(sql, (finding_id,))
        return [InvestigationEvidence.from_dict(r) for r in rows]

    def get_findings_for_evidence(self, evidence_id: str) -> list[str]:
        """Return list of finding IDs linked to a given evidence item."""
        rows = self._db.fetchall(
            "SELECT finding_id FROM investigation_finding_evidence WHERE evidence_id = ?;",
            (evidence_id,),
        )
        return [r["finding_id"] for r in rows]

    # ------------------------------------------------------------------
    # Verifiable Activity Operations
    # ------------------------------------------------------------------

    def log_activity(
        self,
        investigation_id: str,
        activity_type: str,
        description: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> InvestigationActivity:
        """Log a real user action to the activity timeline."""
        act = InvestigationActivity(
            investigation_id=investigation_id,
            activity_type=activity_type,
            description=description,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        now = act.created_at.isoformat()
        sql = """
            INSERT INTO investigation_activities (
                id, investigation_id, activity_type, description,
                entity_type, entity_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        try:
            self._db.execute(
                sql,
                (
                    act.id,
                    act.investigation_id,
                    act.activity_type,
                    act.description,
                    act.entity_type,
                    act.entity_id,
                    now,
                ),
            )
            return act
        except Exception as exc:
            logger.warning("Failed to log investigation activity: %s", exc)
            return act

    def get_activities(
        self,
        investigation_id: str,
        limit: int = 50,
    ) -> list[InvestigationActivity]:
        """Fetch activity log for an investigation ordered newest first."""
        rows = self._db.fetchall(
            """
            SELECT * FROM investigation_activities
            WHERE investigation_id = ?
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (investigation_id, limit),
        )
        return [InvestigationActivity.from_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Workspace Activity Statistics
    # ------------------------------------------------------------------

    def get_stats(self, investigation_id: str) -> InvestigationStats:
        """Compute live activity counts across all investigation entities."""
        stats = InvestigationStats()

        r_src = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_sources WHERE investigation_id = ?;",
            (investigation_id,),
        )
        stats.source_count = int(r_src["cnt"]) if r_src else 0

        r_cpt = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_concepts WHERE investigation_id = ?;",
            (investigation_id,),
        )
        stats.concept_count = int(r_cpt["cnt"]) if r_cpt else 0

        r_ev = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_evidence WHERE investigation_id = ?;",
            (investigation_id,),
        )
        stats.evidence_count = int(r_ev["cnt"]) if r_ev else 0

        r_q_open = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_questions WHERE investigation_id = ? AND status != 'RESOLVED';",
            (investigation_id,),
        )
        stats.open_questions_count = int(r_q_open["cnt"]) if r_q_open else 0

        r_q_res = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_questions WHERE investigation_id = ? AND status = 'RESOLVED';",
            (investigation_id,),
        )
        stats.resolved_questions_count = int(r_q_res["cnt"]) if r_q_res else 0

        r_find = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_findings WHERE investigation_id = ?;",
            (investigation_id,),
        )
        stats.findings_count = int(r_find["cnt"]) if r_find else 0

        r_find_supp = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_findings WHERE investigation_id = ? AND status = 'SUPPORTED';",
            (investigation_id,),
        )
        stats.supported_findings_count = int(r_find_supp["cnt"]) if r_find_supp else 0

        r_notes = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_notes WHERE investigation_id = ?;",
            (investigation_id,),
        )
        stats.notes_count = int(r_notes["cnt"]) if r_notes else 0

        r_act = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM investigation_activities WHERE investigation_id = ?;",
            (investigation_id,),
        )
        stats.activity_count = int(r_act["cnt"]) if r_act else 0

        return stats

    # ------------------------------------------------------------------
    # Legacy Phase 1 Compatibility (investigation_documents)
    # ------------------------------------------------------------------

    def add_document(self, investigation_id: str, document_id: str) -> None:
        """Associate a Document with this Investigation (Phase 1)."""
        now = datetime.now(tz=timezone.utc).isoformat()
        try:
            self._db.execute(
                """
                INSERT OR IGNORE INTO investigation_documents
                    (investigation_id, document_id, added_at)
                VALUES (?, ?, ?);
                """,
                (investigation_id, document_id, now),
            )
        except Exception as exc:
            raise RepositoryError(f"Failed to add document to investigation: {exc}") from exc

    def remove_document(self, investigation_id: str, document_id: str) -> None:
        """Remove a Document association from this Investigation (Phase 1)."""
        try:
            self._db.execute(
                """
                DELETE FROM investigation_documents
                WHERE investigation_id = ? AND document_id = ?;
                """,
                (investigation_id, document_id),
            )
        except Exception as exc:
            raise RepositoryError(f"Failed to remove document from investigation: {exc}") from exc

    def get_documents(self, investigation_id: str) -> list[str]:
        """Return a list of document IDs linked to this Investigation (Phase 1)."""
        rows = self._db.fetchall(
            """
            SELECT document_id FROM investigation_documents
            WHERE investigation_id = ?
            ORDER BY added_at ASC;
            """,
            (investigation_id,),
        )
        return [r["document_id"] for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _touch_investigation(self, investigation_id: str) -> None:
        """Refresh updated_at timestamp on the parent investigation."""
        now = datetime.now(tz=timezone.utc).isoformat()
        try:
            self._db.execute(
                "UPDATE investigations SET updated_at = ? WHERE id = ?;",
                (now, investigation_id),
            )
        except Exception as exc:
            logger.warning("Could not touch investigation %s: %s", investigation_id, exc)
