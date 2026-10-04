"""
Investigation Models & Enumerations
Phase 8 — Investigation Workspace

Provides domain models for investigations, attached sources, tracked concepts,
recorded evidence, research notes, open questions, findings, and activity logging.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import json

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel, _new_uuid, _now_iso


# ---------------------------------------------------------------------------
# Status & Type Enumerations
# ---------------------------------------------------------------------------

class InvestigationStatus(str, Enum):
    """Lifecycle statuses for an investigation."""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"

    @classmethod
    def from_str(cls, val: str | InvestigationStatus) -> InvestigationStatus:
        if isinstance(val, InvestigationStatus):
            return val
        s = str(val).strip().lower()
        for member in cls:
            if member.value == s:
                return member
        raise ValidationError(
            f"Invalid investigation status '{val}'. Must be one of {[m.value for m in cls]}.",
            field="status",
        )


VALID_STATUS_TRANSITIONS: dict[InvestigationStatus, set[InvestigationStatus]] = {
    InvestigationStatus.DRAFT: {InvestigationStatus.ACTIVE, InvestigationStatus.ARCHIVED},
    InvestigationStatus.ACTIVE: {InvestigationStatus.PAUSED, InvestigationStatus.COMPLETED, InvestigationStatus.ARCHIVED},
    InvestigationStatus.PAUSED: {InvestigationStatus.ACTIVE, InvestigationStatus.COMPLETED, InvestigationStatus.ARCHIVED},
    InvestigationStatus.COMPLETED: {InvestigationStatus.ARCHIVED, InvestigationStatus.ACTIVE},
    InvestigationStatus.ARCHIVED: {InvestigationStatus.ACTIVE, InvestigationStatus.PAUSED},
}


class SourceRelationshipType(str, Enum):
    """Categorisation of how an attached source relates to the investigation."""
    RELEVANT = "RELEVANT"
    PRIMARY_EVIDENCE = "PRIMARY_EVIDENCE"
    BACKGROUND = "BACKGROUND"
    CONTRADICTORY = "CONTRADICTORY"
    REFERENCE = "REFERENCE"

    @classmethod
    def from_str(cls, val: str | SourceRelationshipType) -> SourceRelationshipType:
        if isinstance(val, SourceRelationshipType):
            return val
        s = str(val).strip().upper()
        for member in cls:
            if member.value == s:
                return member
        return cls.RELEVANT


class ConceptRole(str, Enum):
    """Research role assigned to a tracked concept within an investigation."""
    KEY_CONCEPT = "KEY_CONCEPT"
    SUPPORTING_CONCEPT = "SUPPORTING_CONCEPT"
    EMERGING_CONCEPT = "EMERGING_CONCEPT"
    OPEN_CONCEPT = "OPEN_CONCEPT"

    @classmethod
    def from_str(cls, val: str | ConceptRole) -> ConceptRole:
        if isinstance(val, ConceptRole):
            return val
        s = str(val).strip().upper()
        for member in cls:
            if member.value == s:
                return member
        return cls.KEY_CONCEPT


class EvidenceType(str, Enum):
    """Classification of an empirical statement extracted from a source."""
    OBSERVATION = "OBSERVATION"
    FACT = "FACT"
    CLAIM = "CLAIM"
    STATISTIC = "STATISTIC"
    DEFINITION = "DEFINITION"
    EXAMPLE = "EXAMPLE"
    CONTRAST = "CONTRAST"

    @classmethod
    def from_str(cls, val: str | EvidenceType) -> EvidenceType:
        if isinstance(val, EvidenceType):
            return val
        s = str(val).strip().upper()
        for member in cls:
            if member.value == s:
                return member
        return cls.OBSERVATION


class QuestionStatus(str, Enum):
    """Lifecycle status for an open research question."""
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"

    @classmethod
    def from_str(cls, val: str | QuestionStatus) -> QuestionStatus:
        if isinstance(val, QuestionStatus):
            return val
        s = str(val).strip().upper()
        for member in cls:
            if member.value == s:
                return member
        return cls.OPEN


class FindingStatus(str, Enum):
    """Validation status for a researcher-recorded finding."""
    DRAFT = "DRAFT"
    SUPPORTED = "SUPPORTED"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    REVISED = "REVISED"

    @classmethod
    def from_str(cls, val: str | FindingStatus) -> FindingStatus:
        if isinstance(val, FindingStatus):
            return val
        s = str(val).strip().upper()
        for member in cls:
            if member.value == s:
                return member
        return cls.DRAFT


class NoteType(str, Enum):
    """Editorial intent of a research note."""
    GENERAL = "GENERAL"
    OBSERVATION = "OBSERVATION"
    HYPOTHESIS = "HYPOTHESIS"
    QUESTION = "QUESTION"
    INTERPRETATION = "INTERPRETATION"
    NEXT_STEP = "NEXT_STEP"

    @classmethod
    def from_str(cls, val: str | NoteType) -> NoteType:
        if isinstance(val, NoteType):
            return val
        s = str(val).strip().upper()
        for member in cls:
            if member.value == s:
                return member
        return cls.GENERAL


class ActivityType(str, Enum):
    """Verifiable user actions in an investigation."""
    INVESTIGATION_CREATED = "INVESTIGATION_CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    SOURCE_ATTACHED = "SOURCE_ATTACHED"
    SOURCE_REMOVED = "SOURCE_REMOVED"
    CONCEPT_ATTACHED = "CONCEPT_ATTACHED"
    CONCEPT_REMOVED = "CONCEPT_REMOVED"
    EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
    EVIDENCE_UPDATED = "EVIDENCE_UPDATED"
    EVIDENCE_DELETED = "EVIDENCE_DELETED"
    NOTE_ADDED = "NOTE_ADDED"
    QUESTION_CREATED = "QUESTION_CREATED"
    QUESTION_UPDATED = "QUESTION_UPDATED"
    QUESTION_RESOLVED = "QUESTION_RESOLVED"
    FINDING_CREATED = "FINDING_CREATED"
    FINDING_UPDATED = "FINDING_UPDATED"
    FINDING_EVIDENCE_LINKED = "FINDING_EVIDENCE_LINKED"
    FINDING_EVIDENCE_UNLINKED = "FINDING_EVIDENCE_UNLINKED"
    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    INVESTIGATION_ARCHIVED = "INVESTIGATION_ARCHIVED"


# ---------------------------------------------------------------------------
# Domain Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InvestigationSource:
    """Represents a source explicitly attached to an investigation."""
    investigation_id: str
    source_id: str
    relationship_type: str = SourceRelationshipType.RELEVANT.value
    added_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    notes: Optional[str] = None

    # Joined fields for presentation
    source_title: str = ""
    source_file_type: str = ""
    source_word_count: int = 0
    evidence_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "source_id": self.source_id,
            "relationship_type": self.relationship_type,
            "added_at": self.added_at.isoformat() if isinstance(self.added_at, datetime) else str(self.added_at),
            "notes": self.notes,
            "source_title": self.source_title,
            "source_file_type": self.source_file_type,
            "source_word_count": self.source_word_count,
            "evidence_count": self.evidence_count,
        }


@dataclass
class InvestigationConcept:
    """Represents a concept tracked within an investigation."""
    investigation_id: str
    concept_id: str
    role: str = ConceptRole.KEY_CONCEPT.value
    added_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    notes: Optional[str] = None

    # Joined fields for presentation
    concept_name: str = ""
    concept_frequency: int = 0
    concept_source_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "concept_id": self.concept_id,
            "role": self.role,
            "added_at": self.added_at.isoformat() if isinstance(self.added_at, datetime) else str(self.added_at),
            "notes": self.notes,
            "concept_name": self.concept_name,
            "concept_frequency": self.concept_frequency,
            "concept_source_count": self.concept_source_count,
        }


@dataclass
class InvestigationEvidence(BaseModel):
    """
    A concrete empirical observation recorded by the user from a source.
    Always maintains unambiguous provenance back to source_id.
    """
    investigation_id: str = ""
    source_id: str = ""
    title: str = ""
    statement: str = ""
    excerpt: str = ""
    location: str = ""
    evidence_type: str = EvidenceType.OBSERVATION.value
    confidence: float = 1.0
    notes: Optional[str] = None

    # Joined fields for presentation
    source_title: str = ""
    source_file_type: str = ""
    linked_finding_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.statement or not self.statement.strip():
            raise ValidationError("Evidence statement must not be empty.", field="statement")
        if not self.investigation_id or not self.investigation_id.strip():
            raise ValidationError("investigation_id must not be empty.", field="investigation_id")
        if not self.source_id or not self.source_id.strip():
            raise ValidationError("source_id must not be empty.", field="source_id")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValidationError("confidence must be between 0.0 and 1.0.", field="confidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "source_id": self.source_id,
            "title": self.title,
            "statement": self.statement,
            "excerpt": self.excerpt,
            "location": self.location,
            "evidence_type": self.evidence_type,
            "confidence": self.confidence,
            "notes": self.notes,
            "source_title": self.source_title,
            "source_file_type": self.source_file_type,
            "linked_finding_ids": self.linked_finding_ids,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvestigationEvidence:
        processed = dict(data)
        for dt in ("created_at", "updated_at"):
            if dt in processed and isinstance(processed[dt], str):
                processed[dt] = datetime.fromisoformat(processed[dt])
        # Discard non-model keys if present
        valid_fields = {
            "id", "investigation_id", "source_id", "title", "statement",
            "excerpt", "location", "evidence_type", "confidence", "notes",
            "source_title", "source_file_type", "linked_finding_ids",
            "created_at", "updated_at"
        }
        filtered = {k: v for k, v in processed.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class InvestigationNote(BaseModel):
    """A lightweight research note within an investigation."""
    investigation_id: str = ""
    title: str = ""
    content: str = ""
    note_type: str = NoteType.GENERAL.value

    def validate(self) -> None:
        if not self.content or not self.content.strip():
            raise ValidationError("Note content must not be empty.", field="content")
        if not self.investigation_id:
            raise ValidationError("investigation_id must not be empty.", field="investigation_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "title": self.title,
            "content": self.content,
            "note_type": self.note_type,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvestigationNote:
        processed = dict(data)
        for dt in ("created_at", "updated_at"):
            if dt in processed and isinstance(processed[dt], str):
                processed[dt] = datetime.fromisoformat(processed[dt])
        return cls(**processed)


@dataclass
class InvestigationQuestion(BaseModel):
    """An open or resolved research question."""
    investigation_id: str = ""
    question: str = ""
    status: str = QuestionStatus.OPEN.value
    resolution_note: Optional[str] = None
    resolved_at: Optional[datetime] = None

    # Joined
    linked_evidence_count: int = 0

    def validate(self) -> None:
        if not self.question or not self.question.strip():
            raise ValidationError("Research question must not be empty.", field="question")
        if not self.investigation_id:
            raise ValidationError("investigation_id must not be empty.", field="investigation_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "question": self.question,
            "status": self.status,
            "resolution_note": self.resolution_note,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "linked_evidence_count": self.linked_evidence_count,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvestigationQuestion:
        processed = dict(data)
        for dt in ("created_at", "updated_at", "resolved_at"):
            if dt in processed and isinstance(processed[dt], str):
                processed[dt] = datetime.fromisoformat(processed[dt])
        valid_fields = {
            "id", "investigation_id", "question", "status", "resolution_note",
            "resolved_at", "linked_evidence_count", "created_at", "updated_at"
        }
        filtered = {k: v for k, v in processed.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class InvestigationFinding(BaseModel):
    """
    A conclusion recorded by the researcher based on gathered evidence.
    Tracks provenance through linked evidence back to primary sources.
    """
    investigation_id: str = ""
    title: str = ""
    statement: str = ""
    status: str = FindingStatus.DRAFT.value
    supporting_evidence_count: int = 0
    supporting_sources_count: int = 0

    # Joined supporting evidence items
    supporting_evidence: list[InvestigationEvidence] = field(default_factory=list)

    def validate(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError("Finding title must not be empty.", field="title")
        if not self.statement or not self.statement.strip():
            raise ValidationError("Finding statement must not be empty.", field="statement")
        if not self.investigation_id:
            raise ValidationError("investigation_id must not be empty.", field="investigation_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "title": self.title,
            "statement": self.statement,
            "status": self.status,
            "supporting_evidence_count": self.supporting_evidence_count,
            "supporting_sources_count": self.supporting_sources_count,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvestigationFinding:
        processed = dict(data)
        for dt in ("created_at", "updated_at"):
            if dt in processed and isinstance(processed[dt], str):
                processed[dt] = datetime.fromisoformat(processed[dt])
        evs = processed.get("supporting_evidence", [])
        if evs and isinstance(evs[0], dict):
            processed["supporting_evidence"] = [InvestigationEvidence.from_dict(e) for e in evs]
        valid_fields = {
            "id", "investigation_id", "title", "statement", "status",
            "supporting_evidence_count", "supporting_sources_count",
            "supporting_evidence", "created_at", "updated_at"
        }
        filtered = {k: v for k, v in processed.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class InvestigationActivity(BaseModel):
    """An immutable audit record of a verifiable user action."""
    investigation_id: str = ""
    activity_type: str = ActivityType.INVESTIGATION_CREATED.value
    description: str = ""
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "activity_type": self.activity_type,
            "description": self.description,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvestigationActivity:
        processed = dict(data)
        if "created_at" in processed and isinstance(processed["created_at"], str):
            processed["created_at"] = datetime.fromisoformat(processed["created_at"])
        if "updated_at" in processed and isinstance(processed["updated_at"], str):
            processed["updated_at"] = datetime.fromisoformat(processed["updated_at"])
        return cls(**processed)


@dataclass
class InvestigationStats:
    """Measurable activity metrics for an investigation workspace."""
    source_count: int = 0
    concept_count: int = 0
    evidence_count: int = 0
    open_questions_count: int = 0
    resolved_questions_count: int = 0
    findings_count: int = 0
    supported_findings_count: int = 0
    notes_count: int = 0
    activity_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": self.source_count,
            "concept_count": self.concept_count,
            "evidence_count": self.evidence_count,
            "open_questions_count": self.open_questions_count,
            "resolved_questions_count": self.resolved_questions_count,
            "findings_count": self.findings_count,
            "supported_findings_count": self.supported_findings_count,
            "notes_count": self.notes_count,
            "activity_count": self.activity_count,
        }
