"""
Domain models for ORVIA Phase 11:
Advanced Research Workflow, Universal Context, and Workspace Integrity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ActivityType(str, Enum):
    SOURCE_IMPORTED = "source_imported"
    SOURCE_VIEWED = "source_viewed"
    SEARCH_PERFORMED = "search_performed"
    CONCEPT_VIEWED = "concept_viewed"
    CONCEPT_EXPLORED = "concept_explored"
    INVESTIGATION_CREATED = "investigation_created"
    INVESTIGATION_UPDATED = "investigation_updated"
    INVESTIGATION_VIEWED = "investigation_viewed"
    EVIDENCE_RECORDED = "evidence_recorded"
    FINDING_RECORDED = "finding_recorded"
    FINDING_UPDATED = "finding_updated"
    QUESTION_ADDED = "question_added"
    QUESTION_RESOLVED = "question_resolved"
    REPORT_CREATED = "report_created"
    REPORT_UPDATED = "report_updated"
    REPORT_EXPORTED = "report_exported"
    GRAPH_EXPLORED = "graph_explored"
    INDEX_REBUILT = "index_rebuilt"
    DEMO_LOADED = "demo_loaded"
    DEMO_CLEARED = "demo_cleared"


@dataclass
class ResearchActivity:
    """A verified user interaction or research event recorded on disk."""
    id: str
    activity_type: str
    entity_type: str
    title: str
    entity_id: Optional[str] = None
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "activity_type": self.activity_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "title": self.title,
            "description": self.description,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchActivity:
        meta = data.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return cls(
            id=data["id"],
            activity_type=data["activity_type"],
            entity_type=data["entity_type"],
            entity_id=data.get("entity_id"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            metadata=meta,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class UniversalSearchResult:
    """A search hit returned in the universal multi-entity search palette."""
    item_type: str  # COMMAND, INVESTIGATION, SOURCE, CONCEPT, REPORT, EVIDENCE, FINDING
    id: str
    title: str
    subtitle: str
    url: str
    badge: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_type": self.item_type,
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "url": self.url,
            "badge": self.badge,
            "metadata": self.metadata,
        }


@dataclass
class ResearchContext:
    """Current active research context and contextual navigation actions."""
    active_investigation_id: Optional[str] = None
    active_source_id: Optional[str] = None
    active_concept_id: Optional[str] = None
    active_report_id: Optional[str] = None
    active_investigation: Optional[dict[str, Any]] = None
    active_source: Optional[dict[str, Any]] = None
    active_concept: Optional[dict[str, Any]] = None
    active_report: Optional[dict[str, Any]] = None
    breadcrumbs: list[dict[str, str]] = field(default_factory=list)
    quick_actions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_investigation_id": self.active_investigation_id,
            "active_source_id": self.active_source_id,
            "active_concept_id": self.active_concept_id,
            "active_report_id": self.active_report_id,
            "active_investigation": self.active_investigation,
            "active_source": self.active_source,
            "active_concept": self.active_concept,
            "active_report": self.active_report,
            "breadcrumbs": self.breadcrumbs,
            "quick_actions": self.quick_actions,
        }


@dataclass
class ResearchTension:
    """
    Deterministic tension or contrast between empirical records.
    Explicitly labeled as Research Tension, NOT semantic truth conflict.
    """
    finding_id: str
    finding_title: str
    tension_type: str  # CONTRAST_EVIDENCE, CONFLICTING_RELATIONSHIP
    description: str
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "finding_title": self.finding_title,
            "tension_type": self.tension_type,
            "description": self.description,
            "evidence_items": self.evidence_items,
            "sources": self.sources,
        }


@dataclass
class IndexHealth:
    """Real status of the deterministic search index."""
    status: str  # Healthy, Needs Rebuild
    total_sources: int
    indexed_sources: int
    indexed_terms: int
    last_updated: Optional[str] = None
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_sources": self.total_sources,
            "indexed_sources": self.indexed_sources,
            "indexed_terms": self.indexed_terms,
            "last_updated": self.last_updated,
            "explanation": self.explanation,
        }


@dataclass
class DataIntegrityReport:
    """Comprehensive diagnostic of database referential integrity."""
    healthy: bool
    total_checks: int
    issues_count: int
    warnings_count: int
    checks: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "total_checks": self.total_checks,
            "issues_count": self.issues_count,
            "warnings_count": self.warnings_count,
            "checks": self.checks,
            "issues": self.issues,
            "warnings": self.warnings,
        }
