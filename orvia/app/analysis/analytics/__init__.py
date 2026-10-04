"""
ORVIA Research Analytics & Pattern Intelligence Subsystem
Phase 9 — Deterministic, explainable collection analytics and pattern mining.
"""
from orvia.app.analysis.analytics.models import (
    CollectionSnapshot,
    ConceptComparison,
    ConceptPatternMetrics,
    CoverageAnalysis,
    PatternItem,
    PatternType,
    SourceOverlap,
    SourcePatternMetrics,
    TemporalDataPoint,
    TemporalTrends,
    TrendStatus,
)
from orvia.app.analysis.analytics.statistics import CollectionStatisticsCalculator
from orvia.app.analysis.analytics.trends import TemporalAnalyticsCalculator
from orvia.app.analysis.analytics.coverage import CoverageAnalyzer
from orvia.app.analysis.analytics.comparisons import ComparisonEngine
from orvia.app.analysis.analytics.patterns import PatternDetector
from orvia.app.analysis.analytics.service import AnalyticsService

__all__ = [
    "CollectionSnapshot",
    "ConceptComparison",
    "ConceptPatternMetrics",
    "CoverageAnalysis",
    "PatternItem",
    "PatternType",
    "SourceOverlap",
    "SourcePatternMetrics",
    "TemporalDataPoint",
    "TemporalTrends",
    "TrendStatus",
    "CollectionStatisticsCalculator",
    "TemporalAnalyticsCalculator",
    "CoverageAnalyzer",
    "ComparisonEngine",
    "PatternDetector",
    "AnalyticsService",
]
