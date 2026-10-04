"""
Data models and enumerations for Phase 9: Research Analytics & Pattern Intelligence.
All models are strictly deterministic, explainable, and local.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class TrendStatus(str, Enum):
    """Deterministic trend classifications based on observed historical data."""
    GROWING = "Growing"
    DECLINING = "Declining"
    STABLE = "Stable"
    RECENTLY_DETECTED = "Recently Detected"
    INSUFFICIENT_HISTORY = "Insufficient History"


class PatternType(str, Enum):
    """Observable structural patterns detected across research collections."""
    CONCEPT_FREQUENCY_CHANGE = "CONCEPT_FREQUENCY_CHANGE"
    SOURCE_OVERLAP = "SOURCE_OVERLAP"
    HIGH_CONNECTIVITY = "HIGH_CONNECTIVITY"
    LOW_CONNECTIVITY = "LOW_CONNECTIVITY"
    LOW_SOURCE_COVERAGE = "LOW_SOURCE_COVERAGE"
    HIGH_SOURCE_COVERAGE = "HIGH_SOURCE_COVERAGE"
    EMERGING_CONCEPT = "EMERGING_CONCEPT"
    DECLINING_CONCEPT = "DECLINING_CONCEPT"
    INVESTIGATION_ACTIVITY = "INVESTIGATION_ACTIVITY"
    OPEN_QUESTION_GAP = "OPEN_QUESTION_GAP"
    EVIDENCE_CONCENTRATION = "EVIDENCE_CONCENTRATION"


@dataclass
class CollectionSnapshot:
    """Quantitative summary of the total research corpus and calculated densities."""
    total_sources: int = 0
    total_concepts: int = 0
    total_topics: int = 0
    total_investigations: int = 0
    total_evidence: int = 0
    total_open_questions: int = 0
    total_findings: int = 0
    total_relationships: int = 0

    # Calculated density indicators (explicitly labeled, not "quality scores")
    avg_concepts_per_source: float = 0.0
    avg_concepts_per_investigation: float = 0.0
    avg_evidence_per_investigation: float = 0.0
    avg_sources_per_investigation: float = 0.0
    avg_relationships_per_concept: float = 0.0
    calculated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sources": self.total_sources,
            "total_concepts": self.total_concepts,
            "total_topics": self.total_topics,
            "total_investigations": self.total_investigations,
            "total_evidence": self.total_evidence,
            "total_open_questions": self.total_open_questions,
            "total_findings": self.total_findings,
            "total_relationships": self.total_relationships,
            "avg_concepts_per_source": round(self.avg_concepts_per_source, 2),
            "avg_concepts_per_investigation": round(self.avg_concepts_per_investigation, 2),
            "avg_evidence_per_investigation": round(self.avg_evidence_per_investigation, 2),
            "avg_sources_per_investigation": round(self.avg_sources_per_investigation, 2),
            "avg_relationships_per_concept": round(self.avg_relationships_per_concept, 2),
            "calculated_at": self.calculated_at,
        }


@dataclass
class ConceptPatternMetrics:
    """Individual concept observation distribution and trend characteristics."""
    concept_id: str
    name: str
    total_occurrences: int = 0
    source_count: int = 0
    coverage_pct: float = 0.0
    connection_count: int = 0
    max_occurrences_in_single_source: int = 0
    avg_occurrences_per_source: float = 0.0
    earliest_observation: Optional[str] = None
    latest_observation: Optional[str] = None
    trend_status: str = TrendStatus.INSUFFICIENT_HISTORY.value
    trend_description: str = "Insufficient observations to determine direction."
    trend_ratio: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "total_occurrences": self.total_occurrences,
            "source_count": self.source_count,
            "coverage_pct": round(self.coverage_pct, 1),
            "connection_count": self.connection_count,
            "max_occurrences_in_single_source": self.max_occurrences_in_single_source,
            "avg_occurrences_per_source": round(self.avg_occurrences_per_source, 1),
            "earliest_observation": self.earliest_observation,
            "latest_observation": self.latest_observation,
            "trend_status": self.trend_status,
            "trend_description": self.trend_description,
            "trend_ratio": round(self.trend_ratio, 2) if self.trend_ratio is not None else None,
        }


@dataclass
class SourcePatternMetrics:
    """Source-level concept diversity and evidence distribution metrics."""
    source_id: str
    title: str
    file_type: str = "text"
    concept_count: int = 0
    word_count: int = 0
    concept_density: float = 0.0  # concepts per 1,000 words
    evidence_count: int = 0
    investigation_count: int = 0
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "file_type": self.file_type,
            "concept_count": self.concept_count,
            "word_count": self.word_count,
            "concept_density": round(self.concept_density, 2),
            "evidence_count": self.evidence_count,
            "investigation_count": self.investigation_count,
            "created_at": self.created_at,
        }


@dataclass
class SourceOverlap:
    """Deterministic comparative concept overlap between two research sources."""
    source_a_id: str
    source_a_title: str
    source_b_id: str
    source_b_title: str
    shared_concepts: list[str] = field(default_factory=list)
    unique_concepts_a: list[str] = field(default_factory=list)
    unique_concepts_b: list[str] = field(default_factory=list)
    shared_count: int = 0
    union_count: int = 0
    overlap_ratio: float = 0.0  # Jaccard index: shared / union
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_a_id": self.source_a_id,
            "source_a_title": self.source_a_title,
            "source_b_id": self.source_b_id,
            "source_b_title": self.source_b_title,
            "shared_concepts": self.shared_concepts,
            "unique_concepts_a": self.unique_concepts_a,
            "unique_concepts_b": self.unique_concepts_b,
            "shared_count": self.shared_count,
            "union_count": self.union_count,
            "overlap_ratio": round(self.overlap_ratio, 4),
            "overlap_pct": round(self.overlap_ratio * 100, 1),
            "explanation": self.explanation,
        }


@dataclass
class ConceptComparison:
    """Side-by-side descriptive comparison between two concepts."""
    concept_a: dict[str, Any]
    concept_b: dict[str, Any]
    shared_sources: list[dict[str, Any]] = field(default_factory=list)
    shared_source_count: int = 0
    cooccurrence_strength: Optional[float] = None
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_a": self.concept_a,
            "concept_b": self.concept_b,
            "shared_sources": self.shared_sources,
            "shared_source_count": self.shared_source_count,
            "cooccurrence_strength": (
                round(self.cooccurrence_strength, 3)
                if self.cooccurrence_strength is not None
                else None
            ),
            "explanation": self.explanation,
        }


@dataclass
class TemporalDataPoint:
    """Discrete bucket of chronological research events."""
    period: str  # YYYY-MM-DD or week
    sources_added: int = 0
    evidence_recorded: int = 0
    investigations_created: int = 0
    concept_observations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "sources_added": self.sources_added,
            "evidence_recorded": self.evidence_recorded,
            "investigations_created": self.investigations_created,
            "concept_observations": self.concept_observations,
        }


@dataclass
class TemporalTrends:
    """Aggregated timeline metrics across days or weeks."""
    interval: str = "daily"  # "daily" | "weekly" | "monthly"
    data_points: list[TemporalDataPoint] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval": self.interval,
            "data_points": [dp.to_dict() for dp in self.data_points],
            "summary": self.summary,
        }


@dataclass
class CoverageAnalysis:
    """Collection-wide distribution coverage and isolated vs connected vertices."""
    total_sources: int = 0
    total_concepts: int = 0
    single_source_concepts_count: int = 0
    single_source_concepts_pct: float = 0.0
    multi_source_concepts_count: int = 0
    multi_source_concepts_pct: float = 0.0
    low_coverage_concepts: list[dict[str, Any]] = field(default_factory=list)
    isolated_concepts: list[dict[str, Any]] = field(default_factory=list)
    highly_connected_concepts: list[dict[str, Any]] = field(default_factory=list)
    investigation_coverage: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sources": self.total_sources,
            "total_concepts": self.total_concepts,
            "single_source_concepts_count": self.single_source_concepts_count,
            "single_source_concepts_pct": round(self.single_source_concepts_pct, 1),
            "multi_source_concepts_count": self.multi_source_concepts_count,
            "multi_source_concepts_pct": round(self.multi_source_concepts_pct, 1),
            "low_coverage_concepts": self.low_coverage_concepts,
            "isolated_concepts": self.isolated_concepts,
            "highly_connected_concepts": self.highly_connected_concepts,
            "investigation_coverage": self.investigation_coverage,
        }


@dataclass
class PatternItem:
    """A deterministic, verifiable insight backed by explicit counts and formulas."""
    pattern_type: str
    title: str
    description: str
    evidence_summary: str
    calculation_formula: str
    source_ids: list[str] = field(default_factory=list)
    concept_ids: list[str] = field(default_factory=list)
    investigation_ids: list[str] = field(default_factory=list)
    calculated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "title": self.title,
            "description": self.description,
            "evidence_summary": self.evidence_summary,
            "calculation_formula": self.calculation_formula,
            "source_ids": self.source_ids,
            "concept_ids": self.concept_ids,
            "investigation_ids": self.investigation_ids,
            "calculated_at": self.calculated_at,
        }
