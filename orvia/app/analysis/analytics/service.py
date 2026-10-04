"""
AnalyticsService — High-level orchestration for Phase 9 Research Analytics.
Coordinates statistics, temporal series, coverage, comparisons, and pattern mining.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from orvia.app.analysis.analytics.comparisons import ComparisonEngine
from orvia.app.analysis.analytics.coverage import CoverageAnalyzer
from orvia.app.analysis.analytics.models import (
    CollectionSnapshot,
    ConceptComparison,
    ConceptPatternMetrics,
    CoverageAnalysis,
    PatternItem,
    SourceOverlap,
    SourcePatternMetrics,
    TemporalTrends,
    TrendStatus,
)
from orvia.app.analysis.analytics.patterns import PatternDetector
from orvia.app.analysis.analytics.statistics import CollectionStatisticsCalculator
from orvia.app.analysis.analytics.trends import TemporalAnalyticsCalculator
from orvia.app.core.database import DatabaseManager


class AnalyticsService:
    """Orchestrates all Phase 9 research analytics operations."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        self._stats_calc = CollectionStatisticsCalculator(db)
        self._temporal_calc = TemporalAnalyticsCalculator(db)
        self._coverage_analyzer = CoverageAnalyzer(db)
        self._comparison_engine = ComparisonEngine(db)
        self._pattern_detector = PatternDetector(db)

    def get_collection_snapshot(self, time_range: str = "all") -> CollectionSnapshot:
        """Return collection snapshot and calculated densities."""
        return self._stats_calc.get_snapshot(time_range=time_range)

    def get_patterns(self, limit: int = 15) -> list[PatternItem]:
        """Detect and return explainable research patterns."""
        return self._pattern_detector.detect_patterns(limit=limit)

    def get_temporal_trends(self, interval: str = "daily", limit: int = 30) -> TemporalTrends:
        """Aggregate chronological activity over days, weeks, or months."""
        return self._temporal_calc.get_temporal_trends(interval=interval, limit=limit)

    def get_coverage_analysis(self) -> CoverageAnalysis:
        """Return coverage distributions, isolated concepts, and investigation coverage."""
        return self._coverage_analyzer.get_coverage_analysis()

    def compare_sources(self, source_a_id: str, source_b_id: str) -> SourceOverlap:
        """Compute Jaccard concept overlap between two research sources."""
        return self._comparison_engine.compare_sources(source_a_id, source_b_id)

    def compare_concepts(self, concept_a_id: str, concept_b_id: str) -> ConceptComparison:
        """Compare two concepts side-by-side."""
        return self._comparison_engine.compare_concepts(concept_a_id, concept_b_id)

    def get_concept_patterns(
        self,
        limit: int = 50,
        sort_by: str = "occurrences",
        order: str = "desc",
    ) -> list[ConceptPatternMetrics]:
        """
        Return structured concept analytics including occurrences, containing sources,
        coverage percentage, connection counts, and deterministic trends.
        """
        src_row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM sources;")
        total_sources = int(src_row["cnt"]) if src_row else 0

        # Load all source timestamps for trend detection
        source_ts_rows = self._db.fetchall("SELECT id, created_at FROM sources;")
        all_source_ts = {}
        for r in source_ts_rows:
            dt_str = r["created_at"]
            if dt_str:
                try:
                    all_source_ts[r["id"]] = datetime.fromisoformat(dt_str)
                except Exception:
                    pass

        # Query concept observation metrics
        rows = self._db.fetchall(
            """
            SELECT
                c.id, c.name, c.frequency AS total_occurrences,
                COUNT(DISTINCT csl.source_id) AS source_count,
                MAX(csl.occurrences) AS max_single_source,
                MIN(csl.first_seen_at) AS earliest_seen,
                MAX(csl.first_seen_at) AS latest_seen
            FROM concepts c
            LEFT JOIN concept_source_links csl ON c.id = csl.concept_id
            GROUP BY c.id
            ORDER BY c.frequency DESC;
            """
        )

        # Preload connections for all concepts in one query
        conn_rows = self._db.fetchall(
            """
            SELECT cid, COUNT(DISTINCT other_id) AS conn_cnt FROM (
                SELECT concept_a_id AS cid, concept_b_id AS other_id FROM concept_cooccurrences
                UNION
                SELECT concept_b_id AS cid, concept_a_id AS other_id FROM concept_cooccurrences
                UNION
                SELECT source_concept_id AS cid, target_concept_id AS other_id FROM relationships
                UNION
                SELECT target_concept_id AS cid, source_concept_id AS other_id FROM relationships
            ) GROUP BY cid;
            """
        )
        conn_map = {r["cid"]: int(r["conn_cnt"]) for r in conn_rows}

        # Preload concept -> set of source_ids
        csl_links = self._db.fetchall("SELECT concept_id, source_id FROM concept_source_links;")
        concept_sources_map = {}
        for r in csl_links:
            concept_sources_map.setdefault(r["concept_id"], set()).add(r["source_id"])

        metrics_list: list[ConceptPatternMetrics] = []
        for r in rows:
            cid = r["id"]
            tot_occ = int(r["total_occurrences"] or 0)
            sc = int(r["source_count"] or 0)
            cov_pct = (sc / total_sources * 100) if total_sources > 0 else 0.0
            conns = conn_map.get(cid, 0)
            max_occ = int(r["max_single_source"] or 0)
            avg_occ = (tot_occ / sc) if sc > 0 else 0.0

            cpt_src_ids = concept_sources_map.get(cid, set())
            trend_status, trend_desc, ratio = self._temporal_calc.calculate_concept_trend(
                concept_id=cid,
                concept_source_ids=cpt_src_ids,
                all_source_timestamps=all_source_ts,
            )

            metrics_list.append(
                ConceptPatternMetrics(
                    concept_id=cid,
                    name=r["name"],
                    total_occurrences=tot_occ,
                    source_count=sc,
                    coverage_pct=cov_pct,
                    connection_count=conns,
                    max_occurrences_in_single_source=max_occ,
                    avg_occurrences_per_source=avg_occ,
                    earliest_observation=r["earliest_seen"],
                    latest_observation=r["latest_seen"],
                    trend_status=trend_status,
                    trend_description=trend_desc,
                    trend_ratio=ratio,
                )
            )

        # In-memory sorting based on requested parameters
        reverse = (order.lower() != "asc")
        if sort_by == "source_count":
            metrics_list.sort(key=lambda m: (m.source_count, m.total_occurrences), reverse=reverse)
        elif sort_by == "connection_count":
            metrics_list.sort(key=lambda m: (m.connection_count, m.total_occurrences), reverse=reverse)
        elif sort_by == "name":
            metrics_list.sort(key=lambda m: m.name.lower(), reverse=not reverse)
        else:  # default 'occurrences'
            metrics_list.sort(key=lambda m: (m.total_occurrences, m.source_count), reverse=reverse)

        return metrics_list[:limit]

    def get_source_patterns(
        self,
        limit: int = 50,
        sort_by: str = "concept_count",
        order: str = "desc",
    ) -> list[SourcePatternMetrics]:
        """Return source-level diversity, word count, density, and evidence metrics."""
        rows = self._db.fetchall(
            """
            SELECT
                s.id, s.title, s.file_type, s.word_count, s.created_at,
                (SELECT COUNT(DISTINCT concept_id) FROM concept_source_links WHERE source_id = s.id) AS concept_count,
                (SELECT COUNT(*) FROM investigation_evidence WHERE source_id = s.id) AS evidence_count,
                (SELECT COUNT(DISTINCT investigation_id) FROM investigation_sources WHERE source_id = s.id) AS investigation_count
            FROM sources s
            ORDER BY concept_count DESC;
            """
        )

        sources_list: list[SourcePatternMetrics] = []
        for r in rows:
            wc = int(r["word_count"] or 0)
            cc = int(r["concept_count"] or 0)
            # Density: concepts per 1,000 words
            density = (cc / (wc / 1000.0)) if wc >= 50 else 0.0

            sources_list.append(
                SourcePatternMetrics(
                    source_id=r["id"],
                    title=r["title"],
                    file_type=r["file_type"] or "text",
                    concept_count=cc,
                    word_count=wc,
                    concept_density=density,
                    evidence_count=int(r["evidence_count"] or 0),
                    investigation_count=int(r["investigation_count"] or 0),
                    created_at=r["created_at"] or "",
                )
            )

        reverse = (order.lower() != "asc")
        if sort_by == "word_count":
            sources_list.sort(key=lambda s: s.word_count, reverse=reverse)
        elif sort_by == "evidence_count":
            sources_list.sort(key=lambda s: s.evidence_count, reverse=reverse)
        elif sort_by == "concept_density":
            sources_list.sort(key=lambda s: s.concept_density, reverse=reverse)
        elif sort_by == "title":
            sources_list.sort(key=lambda s: s.title.lower(), reverse=not reverse)
        else:  # default 'concept_count'
            sources_list.sort(key=lambda s: s.concept_count, reverse=reverse)

        return sources_list[:limit]

    def get_full_analytics(self, time_range: str = "all") -> dict[str, Any]:
        """Bundle all primary analytics sections for the /analyze view."""
        snapshot = self.get_collection_snapshot(time_range=time_range)
        patterns = self.get_patterns(limit=8)
        concepts = self.get_concept_patterns(limit=12)
        sources = self.get_source_patterns(limit=10)
        temporal = self.get_temporal_trends(interval="daily", limit=14)
        coverage = self.get_coverage_analysis()

        return {
            "snapshot": snapshot.to_dict(),
            "patterns": [p.to_dict() for p in patterns],
            "concepts": [c.to_dict() for c in concepts],
            "sources": [s.to_dict() for s in sources],
            "temporal": temporal.to_dict(),
            "coverage": coverage.to_dict(),
            "time_range": time_range,
        }
