"""
Domain models for ORVIA Phase 10: Research Reports & Evidence Synthesis System.

Includes:
- Report entity (with versioning and lifecycle status)
- ReportSection entity (reorderable structured report components)
- ReportSource, ReportEvidence, ReportFinding provenance join models
- ReportQualityMetrics and ReportVersionDiff value objects
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel, _new_uuid, _now_iso


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    FINAL = "FINAL"
    ARCHIVED = "ARCHIVED"


VALID_REPORT_STATUSES: tuple[str, ...] = tuple(s.value for s in ReportStatus)


class ReportSectionType(str, Enum):
    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"
    RESEARCH_QUESTION = "RESEARCH_QUESTION"
    SCOPE = "SCOPE"
    SOURCES = "SOURCES"
    KEY_CONCEPTS = "KEY_CONCEPTS"
    EVIDENCE = "EVIDENCE"
    FINDINGS = "FINDINGS"
    COMPARISON = "COMPARISON"
    PATTERNS = "PATTERNS"
    RELATIONSHIPS = "RELATIONSHIPS"
    OPEN_QUESTIONS = "OPEN_QUESTIONS"
    LIMITATIONS = "LIMITATIONS"
    CONCLUSION = "CONCLUSION"
    REFERENCES = "REFERENCES"


VALID_SECTION_TYPES: tuple[str, ...] = tuple(t.value for t in ReportSectionType)


@dataclass
class Report(BaseModel):
    """
    Research Report model representing a synthesized, traceable research document
    tied to an investigation. Supports versioning and lifecycle states.
    """

    investigation_id: str = ""
    title: str = ""
    subtitle: str = ""
    summary: str = ""
    status: str = "DRAFT"
    version: int = 1
    parent_report_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=_now_iso)

    def validate(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError("Report title must not be empty.", field="title")
        if not self.investigation_id or not self.investigation_id.strip():
            raise ValidationError("investigation_id must not be empty.", field="investigation_id")
        norm_status = self.status.upper() if isinstance(self.status, str) else str(self.status)
        if norm_status not in VALID_REPORT_STATUSES:
            raise ValidationError(
                f"status must be one of {VALID_REPORT_STATUSES!r}; got {self.status!r}.",
                field="status",
            )
        if self.version < 1:
            raise ValidationError("version must be a positive integer.", field="version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "investigation_id": self.investigation_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "summary": self.summary,
            "status": self.status.upper() if isinstance(self.status, str) else str(self.status),
            "version": self.version,
            "parent_report_id": self.parent_report_id,
            "metadata": self.metadata if isinstance(self.metadata, dict) else {},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "generated_at": self.generated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Report":
        processed = dict(data)
        for dt_field in ("created_at", "updated_at", "generated_at"):
            if dt_field in processed and isinstance(processed[dt_field], str):
                processed[dt_field] = datetime.fromisoformat(processed[dt_field])
        if "metadata" in processed and isinstance(processed["metadata"], str):
            try:
                processed["metadata"] = json.loads(processed["metadata"])
            except Exception:
                processed["metadata"] = {}
        if "version" in processed and isinstance(processed["version"], (str, float)):
            processed["version"] = int(processed["version"])

        valid_fields = {
            "id", "investigation_id", "title", "subtitle", "summary",
            "status", "version", "parent_report_id", "metadata",
            "created_at", "updated_at", "generated_at",
        }
        filtered = {k: v for k, v in processed.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class ReportSection(BaseModel):
    """
    Structured section within a report. Can be ordered, added, modified, or removed.
    """

    report_id: str = ""
    section_type: str = "EXECUTIVE_SUMMARY"
    title: str = ""
    position: int = 0
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError("Section title must not be empty.", field="title")
        if not self.report_id or not self.report_id.strip():
            raise ValidationError("report_id must not be empty.", field="report_id")
        norm_type = self.section_type.upper() if isinstance(self.section_type, str) else str(self.section_type)
        if norm_type not in VALID_SECTION_TYPES:
            raise ValidationError(
                f"section_type must be one of {VALID_SECTION_TYPES!r}; got {self.section_type!r}.",
                field="section_type",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "report_id": self.report_id,
            "section_type": self.section_type.upper(),
            "title": self.title,
            "position": self.position,
            "content": self.content,
            "metadata": self.metadata if isinstance(self.metadata, dict) else {},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportSection":
        processed = dict(data)
        for dt_field in ("created_at", "updated_at"):
            if dt_field in processed and isinstance(processed[dt_field], str):
                processed[dt_field] = datetime.fromisoformat(processed[dt_field])
        if "metadata" in processed and isinstance(processed["metadata"], str):
            try:
                processed["metadata"] = json.loads(processed["metadata"])
            except Exception:
                processed["metadata"] = {}
        if "position" in processed:
            processed["position"] = int(processed["position"])

        valid_fields = {
            "id", "report_id", "section_type", "title", "position",
            "content", "metadata", "created_at", "updated_at",
        }
        filtered = {k: v for k, v in processed.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class ReportSource:
    """
    Join model linking a source to a report with its stable citation label.
    """

    report_id: str
    source_id: str
    citation_label: str  # e.g. "[1]"
    position: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "source_id": self.source_id,
            "citation_label": self.citation_label,
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportSource":
        return cls(
            report_id=data["report_id"],
            source_id=data["source_id"],
            citation_label=data.get("citation_label", ""),
            position=int(data.get("position", 0)),
        )


@dataclass
class ReportEvidence:
    """
    Join model linking evidence to a report (and optionally a section) with citation label.
    """

    report_id: str
    evidence_id: str
    citation_label: str  # e.g. "[1]" or "[1, p. 4]"
    section_id: Optional[str] = None
    position: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "evidence_id": self.evidence_id,
            "citation_label": self.citation_label,
            "section_id": self.section_id,
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportEvidence":
        return cls(
            report_id=data["report_id"],
            evidence_id=data["evidence_id"],
            citation_label=data.get("citation_label", ""),
            section_id=data.get("section_id"),
            position=int(data.get("position", 0)),
        )


@dataclass
class ReportFinding:
    """
    Join model linking a finding to a report (and optionally a section).
    """

    report_id: str
    finding_id: str
    section_id: Optional[str] = None
    position: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "finding_id": self.finding_id,
            "section_id": self.section_id,
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportFinding":
        return cls(
            report_id=data["report_id"],
            finding_id=data["finding_id"],
            section_id=data.get("section_id"),
            position=int(data.get("position", 0)),
        )


@dataclass
class ReportQualityMetrics:
    """
    Structured deterministic report quality analysis.
    """

    evidence_coverage_pct: float
    source_coverage_pct: float
    finding_coverage_pct: float
    citation_completeness_pct: float
    open_questions_count: int
    unsupported_findings_count: int
    insufficient_history_concepts_count: int
    single_source_concepts_count: int
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_coverage_pct": round(self.evidence_coverage_pct, 1),
            "source_coverage_pct": round(self.source_coverage_pct, 1),
            "finding_coverage_pct": round(self.finding_coverage_pct, 1),
            "citation_completeness_pct": round(self.citation_completeness_pct, 1),
            "open_questions_count": self.open_questions_count,
            "unsupported_findings_count": self.unsupported_findings_count,
            "insufficient_history_concepts_count": self.insufficient_history_concepts_count,
            "single_source_concepts_count": self.single_source_concepts_count,
            "gaps": list(self.gaps),
        }


@dataclass
class ReportVersionDiff:
    """
    Deterministic comparison between two versions of a report.
    """

    version_a: int
    version_b: int
    added_sections: list[dict[str, Any]] = field(default_factory=list)
    removed_sections: list[dict[str, Any]] = field(default_factory=list)
    modified_sections: list[dict[str, Any]] = field(default_factory=list)
    source_changes: dict[str, list[str]] = field(default_factory=dict)
    evidence_changes: dict[str, list[str]] = field(default_factory=dict)
    finding_changes: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_a": self.version_a,
            "version_b": self.version_b,
            "added_sections": self.added_sections,
            "removed_sections": self.removed_sections,
            "modified_sections": self.modified_sections,
            "source_changes": self.source_changes,
            "evidence_changes": self.evidence_changes,
            "finding_changes": self.finding_changes,
        }
