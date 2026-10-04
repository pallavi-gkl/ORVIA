"""
InvestigationService — Business logic and research workflow orchestration.
Phase 8 — Investigation Workspace
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import NotFoundError, ValidationError
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
from orvia.app.investigations.repository import InvestigationRepository
from orvia.app.models.investigation import Investigation
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.source_repository import SourceRepository

logger = logging.getLogger(__name__)


class InvestigationService:
    """
    Coordinates research investigation workflows:
    defining questions, attaching sources/concepts, recording empirical evidence,
    tracking open questions and findings, computing deterministic research gaps,
    and maintaining verifiable audit activity.
    """

    def __init__(
        self,
        db: DatabaseManager,
        investigation_repo: Optional[InvestigationRepository] = None,
        source_repo: Optional[SourceRepository] = None,
        concept_repo: Optional[ConceptRepository] = None,
    ) -> None:
        self._db = db
        self._inv_repo = investigation_repo or InvestigationRepository(db)
        self._source_repo = source_repo or SourceRepository(db)
        self._concept_repo = concept_repo or ConceptRepository(db)

    # ------------------------------------------------------------------
    # Lifecycle & Core Operations
    # ------------------------------------------------------------------

    def create_investigation(
        self,
        title: str,
        research_question: str,
        description: str = "",
        initial_status: str = "active",
        initial_source_ids: Optional[list[str]] = None,
        initial_concept_ids: Optional[list[str]] = None,
    ) -> Investigation:
        """Create and persist a new investigation."""
        norm_status = InvestigationStatus.from_str(initial_status).value
        inv = Investigation(
            title=title.strip(),
            research_question=research_question.strip(),
            description=description.strip() if description else "",
            status=norm_status,
        )
        inv.validate()
        saved = self._inv_repo.save(inv)

        # Log creation activity
        self._inv_repo.log_activity(
            investigation_id=saved.id,
            activity_type=ActivityType.INVESTIGATION_CREATED.value,
            description=f"Created investigation: {saved.title}",
            entity_type="investigation",
            entity_id=saved.id,
        )

        # Attach initial sources if supplied
        if initial_source_ids:
            for s_id in initial_source_ids:
                try:
                    self.attach_source(saved.id, s_id, SourceRelationshipType.RELEVANT.value)
                except Exception as e:
                    logger.warning("Could not attach initial source %s: %s", s_id, e)

        # Attach initial concepts if supplied
        if initial_concept_ids:
            for c_id in initial_concept_ids:
                try:
                    self.track_concept(saved.id, c_id, ConceptRole.KEY_CONCEPT.value)
                except Exception as e:
                    logger.warning("Could not track initial concept %s: %s", c_id, e)

        return saved

    def get_investigation(self, investigation_id: str) -> Investigation:
        """Fetch investigation or raise NotFoundError."""
        inv = self._inv_repo.find_by_id(investigation_id)
        if not inv:
            raise NotFoundError(entity="Investigation", id=investigation_id)
        return inv

    def update_investigation(
        self,
        investigation_id: str,
        title: Optional[str] = None,
        research_question: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Investigation:
        """Update investigation title, question, or description."""
        inv = self.get_investigation(investigation_id)
        changed = False

        if title is not None and title.strip() and title.strip() != inv.title:
            inv.title = title.strip()
            changed = True
        if research_question is not None and research_question.strip() and research_question.strip() != inv.research_question:
            inv.research_question = research_question.strip()
            changed = True
        if description is not None and description.strip() != inv.description:
            inv.description = description.strip()
            changed = True

        if changed:
            inv.validate()
            self._inv_repo.save(inv)
            self._inv_repo.log_activity(
                investigation_id=inv.id,
                activity_type=ActivityType.INVESTIGATION_CREATED.value,
                description="Updated investigation details",
                entity_type="investigation",
                entity_id=inv.id,
            )

        return inv

    def transition_status(
        self,
        investigation_id: str,
        new_status: str | InvestigationStatus,
    ) -> tuple[Investigation, Optional[str]]:
        """
        Transition investigation lifecycle status following valid state transitions.
        Returns (investigation, optional_warning_message).
        """
        inv = self.get_investigation(investigation_id)
        current_status_enum = InvestigationStatus.from_str(inv.status)
        new_status_enum = InvestigationStatus.from_str(new_status)

        if current_status_enum == new_status_enum:
            return inv, None

        allowed = VALID_STATUS_TRANSITIONS.get(current_status_enum, set())
        if new_status_enum not in allowed:
            raise ValidationError(
                f"Invalid status transition from '{current_status_enum.value.upper()}' to '{new_status_enum.value.upper()}'.",
                field="status",
            )

        warning_message = None
        if new_status_enum == InvestigationStatus.COMPLETED:
            open_q_count = len(self._inv_repo.get_questions(investigation_id, status="OPEN"))
            if open_q_count > 0:
                warning_message = (
                    f"{open_q_count} research question{'s remain' if open_q_count > 1 else ' remains'} open."
                )

        self._inv_repo.update_status(investigation_id, new_status_enum.value)
        inv = self.get_investigation(investigation_id)

        act_type = (
            ActivityType.INVESTIGATION_COMPLETED.value
            if new_status_enum == InvestigationStatus.COMPLETED
            else (
                ActivityType.INVESTIGATION_ARCHIVED.value
                if new_status_enum == InvestigationStatus.ARCHIVED
                else ActivityType.STATUS_CHANGED.value
            )
        )
        self._inv_repo.log_activity(
            investigation_id=investigation_id,
            activity_type=act_type,
            description=f"Status changed to {new_status_enum.value.upper()}",
            entity_type="investigation",
            entity_id=investigation_id,
        )

        return inv, warning_message

    def delete_investigation(self, investigation_id: str) -> bool:
        """Delete an investigation and its associated relationships."""
        inv = self.get_investigation(investigation_id)
        return self._inv_repo.delete(inv.id)

    # ------------------------------------------------------------------
    # Full Workspace Context & Aggregations
    # ------------------------------------------------------------------

    def get_workspace(self, investigation_id: str) -> dict[str, Any]:
        """
        Assemble the complete research desk context:
        investigation header, sources, concepts, evidence, questions, findings,
        notes, activity timeline, statistics, and deterministic research gaps.
        """
        inv = self.get_investigation(investigation_id)
        sources = self._inv_repo.get_sources(investigation_id)
        concepts = self._inv_repo.get_concepts(investigation_id)
        evidence_list = self._inv_repo.get_evidence_for_investigation(investigation_id)
        questions = self._inv_repo.get_questions(investigation_id)
        findings = self._inv_repo.get_findings(investigation_id)
        notes = self._inv_repo.get_notes(investigation_id)
        activities = self._inv_repo.get_activities(investigation_id, limit=50)
        stats = self._inv_repo.get_stats(investigation_id)
        gaps = self.calculate_research_gaps(investigation_id)

        open_questions = [q for q in questions if q.status != QuestionStatus.RESOLVED.value]
        resolved_questions = [q for q in questions if q.status == QuestionStatus.RESOLVED.value]

        return {
            "investigation": inv,
            "sources": sources,
            "concepts": concepts,
            "evidence": evidence_list,
            "questions": questions,
            "open_questions": open_questions,
            "resolved_questions": resolved_questions,
            "findings": findings,
            "notes": notes,
            "activities": activities,
            "stats": stats,
            "gaps": gaps,
        }

    # ------------------------------------------------------------------
    # Source Management
    # ------------------------------------------------------------------

    def attach_source(
        self,
        investigation_id: str,
        source_id: str,
        relationship_type: str = SourceRelationshipType.RELEVANT.value,
        notes: Optional[str] = None,
    ) -> InvestigationSource:
        """Attach a source to the investigation and log activity."""
        source = self._source_repo.find_by_id(source_id)
        if not source:
            raise NotFoundError(entity="Source", id=source_id)

        self._inv_repo.add_source(investigation_id, source_id, relationship_type, notes)

        rel_label = SourceRelationshipType.from_str(relationship_type).value
        self._inv_repo.log_activity(
            investigation_id=investigation_id,
            activity_type=ActivityType.SOURCE_ATTACHED.value,
            description=f"Attached source '{source.title}' as {rel_label}",
            entity_type="source",
            entity_id=source_id,
        )

        sources = self._inv_repo.get_sources(investigation_id)
        for s in sources:
            if s.source_id == source_id:
                return s
        return InvestigationSource(investigation_id=investigation_id, source_id=source_id)

    def detach_source(self, investigation_id: str, source_id: str) -> bool:
        """Detach a source from the investigation."""
        source = self._source_repo.find_by_id(source_id)
        title = source.title if source else source_id
        removed = self._inv_repo.remove_source(investigation_id, source_id)
        if removed:
            self._inv_repo.log_activity(
                investigation_id=investigation_id,
                activity_type=ActivityType.SOURCE_REMOVED.value,
                description=f"Removed source '{title}' from investigation",
                entity_type="source",
                entity_id=source_id,
            )
        return removed

    # ------------------------------------------------------------------
    # Concept Management
    # ------------------------------------------------------------------

    def track_concept(
        self,
        investigation_id: str,
        concept_id: str,
        role: str = ConceptRole.KEY_CONCEPT.value,
        notes: Optional[str] = None,
    ) -> InvestigationConcept:
        """Track a concept in the investigation."""
        concept = self._concept_repo.find_by_id(concept_id)
        if not concept:
            raise NotFoundError(entity="Concept", id=concept_id)

        self._inv_repo.add_concept(investigation_id, concept_id, role, notes)

        role_label = ConceptRole.from_str(role).value
        self._inv_repo.log_activity(
            investigation_id=investigation_id,
            activity_type=ActivityType.CONCEPT_ATTACHED.value,
            description=f"Tracked concept '{concept.name}' as {role_label}",
            entity_type="concept",
            entity_id=concept_id,
        )

        concepts = self._inv_repo.get_concepts(investigation_id)
        for c in concepts:
            if c.concept_id == concept_id:
                return c
        return InvestigationConcept(investigation_id=investigation_id, concept_id=concept_id)

    def untrack_concept(self, investigation_id: str, concept_id: str) -> bool:
        """Untrack a concept from the investigation."""
        concept = self._concept_repo.find_by_id(concept_id)
        name = concept.name if concept else concept_id
        removed = self._inv_repo.remove_concept(investigation_id, concept_id)
        if removed:
            self._inv_repo.log_activity(
                investigation_id=investigation_id,
                activity_type=ActivityType.CONCEPT_REMOVED.value,
                description=f"Removed concept '{name}' from investigation",
                entity_type="concept",
                entity_id=concept_id,
            )
        return removed

    # ------------------------------------------------------------------
    # Evidence Management & Provenance
    # ------------------------------------------------------------------

    def record_evidence(
        self,
        investigation_id: str,
        source_id: str,
        statement: str,
        excerpt: str = "",
        location: str = "",
        evidence_type: str = EvidenceType.OBSERVATION.value,
        confidence: float = 1.0,
        notes: Optional[str] = None,
        title: str = "",
    ) -> InvestigationEvidence:
        """Record an empirical observation extracted from a source."""
        source = self._source_repo.find_by_id(source_id)
        if not source:
            raise NotFoundError(entity="Source", id=source_id)

        # Auto-attach source if not already attached
        if not self._inv_repo.has_source(investigation_id, source_id):
            self.attach_source(investigation_id, source_id, SourceRelationshipType.PRIMARY_EVIDENCE.value)

        ev = InvestigationEvidence(
            investigation_id=investigation_id,
            source_id=source_id,
            title=title.strip() if title else "",
            statement=statement.strip(),
            excerpt=excerpt.strip() if excerpt else "",
            location=location.strip() if location else "",
            evidence_type=EvidenceType.from_str(evidence_type).value,
            confidence=float(confidence),
            notes=notes.strip() if notes else None,
            source_title=source.title,
            source_file_type=source.file_type or source.source_type,
        )
        saved = self._inv_repo.save_evidence(ev)

        self._inv_repo.log_activity(
            investigation_id=investigation_id,
            activity_type=ActivityType.EVIDENCE_RECORDED.value,
            description=f"Recorded {ev.evidence_type} from '{source.title}'",
            entity_type="evidence",
            entity_id=saved.id,
        )

        return saved

    def update_evidence(
        self,
        evidence_id: str,
        statement: Optional[str] = None,
        excerpt: Optional[str] = None,
        location: Optional[str] = None,
        evidence_type: Optional[str] = None,
        confidence: Optional[float] = None,
        notes: Optional[str] = None,
        title: Optional[str] = None,
    ) -> InvestigationEvidence:
        """Update an existing evidence item."""
        ev = self._inv_repo.get_evidence(evidence_id)
        if not ev:
            raise NotFoundError(entity="InvestigationEvidence", id=evidence_id)

        if statement is not None and statement.strip():
            ev.statement = statement.strip()
        if excerpt is not None:
            ev.excerpt = excerpt.strip()
        if location is not None:
            ev.location = location.strip()
        if evidence_type is not None:
            ev.evidence_type = EvidenceType.from_str(evidence_type).value
        if confidence is not None:
            ev.confidence = float(confidence)
        if notes is not None:
            ev.notes = notes.strip() or None
        if title is not None:
            ev.title = title.strip()

        saved = self._inv_repo.save_evidence(ev)

        self._inv_repo.log_activity(
            investigation_id=ev.investigation_id,
            activity_type=ActivityType.EVIDENCE_UPDATED.value,
            description=f"Updated evidence '{ev.statement[:40]}...'",
            entity_type="evidence",
            entity_id=ev.id,
        )

        return saved

    def delete_evidence(self, evidence_id: str) -> bool:
        """Delete an evidence record and log activity."""
        ev = self._inv_repo.get_evidence(evidence_id)
        if not ev:
            return False

        inv_id = ev.investigation_id
        statement_preview = ev.statement[:40]
        deleted = self._inv_repo.delete_evidence(evidence_id)
        if deleted:
            self._inv_repo.log_activity(
                investigation_id=inv_id,
                activity_type=ActivityType.EVIDENCE_DELETED.value,
                description=f"Deleted evidence statement: '{statement_preview}...'",
                entity_type="evidence",
                entity_id=evidence_id,
            )
        return deleted

    # ------------------------------------------------------------------
    # Questions Management
    # ------------------------------------------------------------------

    def add_question(
        self,
        investigation_id: str,
        question: str,
        status: str = QuestionStatus.OPEN.value,
    ) -> InvestigationQuestion:
        """Add an open research question."""
        q = InvestigationQuestion(
            investigation_id=investigation_id,
            question=question.strip(),
            status=QuestionStatus.from_str(status).value,
        )
        saved = self._inv_repo.save_question(q)

        self._inv_repo.log_activity(
            investigation_id=investigation_id,
            activity_type=ActivityType.QUESTION_CREATED.value,
            description=f"Created open question: '{q.question[:50]}...'",
            entity_type="question",
            entity_id=saved.id,
        )

        return saved

    def update_question_status(
        self,
        question_id: str,
        status: str,
        resolution_note: Optional[str] = None,
    ) -> InvestigationQuestion:
        """Update question status or resolve it with a note."""
        q = self._inv_repo.get_question(question_id)
        if not q:
            raise NotFoundError(entity="InvestigationQuestion", id=question_id)

        norm_status = QuestionStatus.from_str(status).value
        if norm_status == QuestionStatus.RESOLVED.value:
            resolved = self._inv_repo.resolve_question(
                question_id,
                resolution_note=resolution_note or "Marked as resolved.",
            )
            self._inv_repo.log_activity(
                investigation_id=q.investigation_id,
                activity_type=ActivityType.QUESTION_RESOLVED.value,
                description=f"Resolved research question: '{q.question[:40]}...'",
                entity_type="question",
                entity_id=q.id,
            )
            return resolved

        q.status = norm_status
        q.resolution_note = resolution_note
        saved = self._inv_repo.save_question(q)
        self._inv_repo.log_activity(
            investigation_id=q.investigation_id,
            activity_type=ActivityType.QUESTION_UPDATED.value,
            description=f"Updated question status to {norm_status}",
            entity_type="question",
            entity_id=q.id,
        )
        return saved

    def delete_question(self, question_id: str) -> bool:
        """Delete a research question."""
        return self._inv_repo.delete_question(question_id)

    # ------------------------------------------------------------------
    # Findings & Provenance Linking
    # ------------------------------------------------------------------

    def record_finding(
        self,
        investigation_id: str,
        title: str,
        statement: str,
        status: str = FindingStatus.DRAFT.value,
        evidence_ids: Optional[list[str]] = None,
    ) -> InvestigationFinding:
        """Record a research finding and link initial supporting evidence."""
        norm_status = FindingStatus.from_str(status).value
        finding = InvestigationFinding(
            investigation_id=investigation_id,
            title=title.strip(),
            statement=statement.strip(),
            status=norm_status,
        )
        saved = self._inv_repo.save_finding(finding)

        if evidence_ids:
            for ev_id in evidence_ids:
                try:
                    self._inv_repo.link_finding_evidence(saved.id, ev_id)
                except Exception as e:
                    logger.warning("Could not link evidence %s to finding %s: %s", ev_id, saved.id, e)

        self._inv_repo.log_activity(
            investigation_id=investigation_id,
            activity_type=ActivityType.FINDING_CREATED.value,
            description=f"Recorded research finding: '{saved.title}'",
            entity_type="finding",
            entity_id=saved.id,
        )

        refreshed = self._inv_repo.get_finding(saved.id)
        return refreshed or saved

    def update_finding(
        self,
        finding_id: str,
        title: Optional[str] = None,
        statement: Optional[str] = None,
        status: Optional[str] = None,
    ) -> InvestigationFinding:
        """Update finding content or status."""
        finding = self._inv_repo.get_finding(finding_id)
        if not finding:
            raise NotFoundError(entity="InvestigationFinding", id=finding_id)

        if title is not None and title.strip():
            finding.title = title.strip()
        if statement is not None and statement.strip():
            finding.statement = statement.strip()
        if status is not None:
            finding.status = FindingStatus.from_str(status).value

        saved = self._inv_repo.save_finding(finding)
        self._inv_repo.log_activity(
            investigation_id=finding.investigation_id,
            activity_type=ActivityType.FINDING_UPDATED.value,
            description=f"Updated finding: '{saved.title}'",
            entity_type="finding",
            entity_id=saved.id,
        )
        return self._inv_repo.get_finding(saved.id) or saved

    def link_evidence_to_finding(self, finding_id: str, evidence_id: str) -> bool:
        """Link evidence item to finding to support provenance."""
        finding = self._inv_repo.get_finding(finding_id)
        if not finding:
            raise NotFoundError(entity="InvestigationFinding", id=finding_id)
        linked = self._inv_repo.link_finding_evidence(finding_id, evidence_id)
        if linked:
            self._inv_repo.log_activity(
                investigation_id=finding.investigation_id,
                activity_type=ActivityType.FINDING_EVIDENCE_LINKED.value,
                description=f"Linked supporting evidence to finding '{finding.title}'",
                entity_type="finding",
                entity_id=finding_id,
            )
        return linked

    def unlink_evidence_from_finding(self, finding_id: str, evidence_id: str) -> bool:
        """Unlink evidence item from finding."""
        finding = self._inv_repo.get_finding(finding_id)
        if not finding:
            raise NotFoundError(entity="InvestigationFinding", id=finding_id)
        unlinked = self._inv_repo.unlink_finding_evidence(finding_id, evidence_id)
        if unlinked:
            self._inv_repo.log_activity(
                investigation_id=finding.investigation_id,
                activity_type=ActivityType.FINDING_EVIDENCE_UNLINKED.value,
                description=f"Unlinked evidence from finding '{finding.title}'",
                entity_type="finding",
                entity_id=finding_id,
            )
        return unlinked

    def delete_finding(self, finding_id: str) -> bool:
        """Delete a finding."""
        return self._inv_repo.delete_finding(finding_id)

    # ------------------------------------------------------------------
    # Research Notes Management
    # ------------------------------------------------------------------

    def add_note(
        self,
        investigation_id: str,
        title: str,
        content: str,
        note_type: str = NoteType.GENERAL.value,
    ) -> InvestigationNote:
        """Add a lightweight research note."""
        note = InvestigationNote(
            investigation_id=investigation_id,
            title=title.strip() if title else "",
            content=content.strip(),
            note_type=NoteType.from_str(note_type).value,
        )
        saved = self._inv_repo.save_note(note)

        self._inv_repo.log_activity(
            investigation_id=investigation_id,
            activity_type=ActivityType.NOTE_ADDED.value,
            description=f"Added {saved.note_type} note: '{saved.title or saved.content[:30]}...'",
            entity_type="note",
            entity_id=saved.id,
        )

        return saved

    def delete_note(self, note_id: str) -> bool:
        """Delete a research note."""
        return self._inv_repo.delete_note(note_id)

    # ------------------------------------------------------------------
    # Deterministic Research Gaps Detection
    # ------------------------------------------------------------------

    def calculate_research_gaps(self, investigation_id: str) -> list[dict[str, Any]]:
        """
        Compute observable gaps in the current research state using deterministic signals.
        Strict neutral wording: 'Potential gap', 'Limited evidence recorded', 'Question remains open'.
        """
        gaps: list[dict[str, Any]] = []

        # 1. Unanswered open questions
        questions = self._inv_repo.get_questions(investigation_id)
        open_questions = [q for q in questions if q.status != QuestionStatus.RESOLVED.value]
        for q in open_questions:
            gaps.append(
                {
                    "type": "unanswered_question",
                    "severity": "medium",
                    "title": "Question remains open",
                    "description": f"Research question '{q.question}' remains open and has not been resolved with recorded evidence.",
                    "target_id": q.id,
                    "target_type": "question",
                    "action_label": "Resolve Question",
                }
            )

        # 2. Tracked concepts not detected in any attached source
        tracked_concepts = self._inv_repo.get_concepts(investigation_id)
        attached_sources = self._inv_repo.get_sources(investigation_id)
        attached_source_ids = {s.source_id for s in attached_sources}

        if tracked_concepts:
            for tc in tracked_concepts:
                # Check if this concept appears in ANY attached source
                row = self._db.fetchone(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM concept_source_links
                    WHERE concept_id = ? AND source_id IN (
                        SELECT source_id FROM investigation_sources WHERE investigation_id = ?
                    );
                    """,
                    (tc.concept_id, investigation_id),
                )
                detected_in_attached = int(row["cnt"]) if row else 0
                if detected_in_attached == 0:
                    gaps.append(
                        {
                            "type": "ungrounded_concept",
                            "severity": "low",
                            "title": "Concept not observed in attached sources",
                            "description": f"Tracked concept '{tc.concept_name}' has not been detected in any currently attached research source.",
                            "target_id": tc.concept_id,
                            "target_type": "concept",
                            "action_label": "Search for Sources",
                        }
                    )

        # 3. Attached sources with no recorded evidence
        for s in attached_sources:
            if s.evidence_count == 0:
                gaps.append(
                    {
                        "type": "unextracted_source",
                        "severity": "low",
                        "title": "Limited evidence recorded",
                        "description": f"Source '{s.source_title}' is attached as {s.relationship_type}, but no specific evidence statements have been recorded from it.",
                        "target_id": s.source_id,
                        "target_type": "source",
                        "action_label": "Record Evidence",
                    }
                )

        # 4. Findings with no supporting evidence
        findings = self._inv_repo.get_findings(investigation_id)
        for f in findings:
            if f.supporting_evidence_count == 0 or f.status in (FindingStatus.DRAFT.value, FindingStatus.NEEDS_EVIDENCE.value):
                gaps.append(
                    {
                        "type": "unsupported_finding",
                        "severity": "high",
                        "title": "Finding has no supporting evidence",
                        "description": f"Finding '{f.title}' currently has no supporting evidence linked from research sources.",
                        "target_id": f.id,
                        "target_type": "finding",
                        "action_label": "Link Evidence",
                    }
                )

        # 5. Empty investigation initial state
        if not attached_sources:
            gaps.append(
                {
                    "type": "empty_sources",
                    "severity": "high",
                    "title": "No research sources attached",
                    "description": "This investigation has no sources attached yet. Search your collection to attach relevant literature.",
                    "target_id": investigation_id,
                    "target_type": "investigation",
                    "action_label": "Search Collection",
                }
            )

        return gaps
