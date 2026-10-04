"""
Unit and integration test suite for ORVIA Phase 9: Research Analytics & Pattern Intelligence.
Tests:
- Collection statistics & calculated densities
- Concept frequencies, distributions, and coverage percentages
- Deterministic source overlap with Jaccard index
- Concept and source pairwise comparators
- Chronological time bucket aggregation
- Deterministic trend detection (Growing, Declining, Stable, Recently Detected, Insufficient History)
- Coverage analysis (single-source vs multi-source, isolated vs connected vertices)
- Investigation coverage classification states
- Deterministic pattern detection engine and explainable formulas
- Time range filtering
- Edge cases: 0 sources, 1 source, empty datasets, missing timestamps
- Web routes (/analyze) and REST API endpoints (/api/analytics/*)
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orvia.app.analysis.analytics import (
    AnalyticsService,
    CollectionSnapshot,
    CollectionStatisticsCalculator,
    ComparisonEngine,
    CoverageAnalyzer,
    PatternDetector,
    PatternType,
    TemporalAnalyticsCalculator,
    TrendStatus,
)
from orvia.app.core.config import Config
from orvia.app.core.database import DatabaseManager
from orvia.app.investigations.models import (
    FindingStatus,
    InvestigationEvidence,
    InvestigationFinding,
    InvestigationQuestion,
    QuestionStatus,
)
from orvia.app.investigations.repository import InvestigationRepository
from orvia.app.models.concept import Concept
from orvia.app.models.investigation import Investigation
from orvia.app.models.source import Source
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.ui import create_app


class TestAnalyticsCore(unittest.TestCase):
    """Unit tests for Phase 9 Analytics models, algorithms, and calculators."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_analytics.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()

        self.source_repo = SourceRepository(self.db)
        self.concept_repo = ConceptRepository(self.db)
        self.inv_repo = InvestigationRepository(self.db)
        self.analytics_svc = AnalyticsService(self.db)

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_source(self, title: str, word_count: int = 500, created_at: Optional[Union[str, datetime]] = None) -> Source:
        if created_at is None:
            dt = datetime.now(timezone.utc)
        elif isinstance(created_at, str):
            dt = datetime.fromisoformat(created_at)
        else:
            dt = created_at
        src = Source(
            id=f"src-{title.lower().replace(' ', '-')}",
            title=title,
            source_type="file",
            file_type="txt",
            word_count=word_count,
            created_at=dt,
            updated_at=dt,
        )
        self.source_repo.save(src)
        return src

    def _create_concept(self, name: str, frequency: int = 1) -> Concept:
        cpt = Concept(
            id=f"cpt-{name.lower().replace(' ', '-')}",
            name=name,
            frequency=frequency,
        )
        self.concept_repo.save(cpt)
        return cpt

    def _link_concept_source(self, concept_id: str, source_id: str, occurrences: int = 1, first_seen_at: Optional[str] = None):
        self.db.execute(
            """
            INSERT OR REPLACE INTO concept_source_links (concept_id, source_id, occurrences, in_title, first_seen_at)
            VALUES (?, ?, ?, 0, ?);
            """,
            (concept_id, source_id, occurrences, first_seen_at or datetime.now(timezone.utc).isoformat()),
        )

    def _link_cooccurrence(self, concept_a_id: str, concept_b_id: str, shared_sources: int = 1, strength: float = 0.5):
        self.db.execute(
            """
            INSERT OR REPLACE INTO concept_cooccurrences (concept_a_id, concept_b_id, shared_sources, strength)
            VALUES (?, ?, ?, ?);
            """,
            (concept_a_id, concept_b_id, shared_sources, strength),
        )

    # 1. Collection statistics
    def test_collection_statistics(self):
        s1 = self._create_source("Source 1")
        s2 = self._create_source("Source 2")
        c1 = self._create_concept("Transformer", 5)
        c2 = self._create_concept("Attention", 3)
        self._link_concept_source(c1.id, s1.id, 5)
        self._link_concept_source(c2.id, s2.id, 3)

        snapshot = self.analytics_svc.get_collection_snapshot()
        self.assertEqual(snapshot.total_sources, 2)
        self.assertEqual(snapshot.total_concepts, 2)
        self.assertEqual(snapshot.avg_concepts_per_source, 1.0)

    # 2. Concept frequency calculations
    def test_concept_frequency_calculations(self):
        s1 = self._create_source("Source Alpha")
        s2 = self._create_source("Source Beta")
        c1 = self._create_concept("Latent Variable", 12)
        self._link_concept_source(c1.id, s1.id, 8)
        self._link_concept_source(c1.id, s2.id, 4)

        metrics = self.analytics_svc.get_concept_patterns()
        self.assertGreaterEqual(len(metrics), 1)
        m = next(x for x in metrics if x.concept_id == c1.id)
        self.assertEqual(m.total_occurrences, 12)
        self.assertEqual(m.source_count, 2)
        self.assertEqual(m.max_occurrences_in_single_source, 8)

    # 3. Source distribution
    def test_source_distribution(self):
        s1 = self._create_source("Source 1")
        s2 = self._create_source("Source 2")
        s3 = self._create_source("Source 3")
        c1 = self._create_concept("Entropy", 6)
        self._link_concept_source(c1.id, s1.id, 2)
        self._link_concept_source(c1.id, s2.id, 2)
        self._link_concept_source(c1.id, s3.id, 2)

        metrics = self.analytics_svc.get_concept_patterns()
        m = next(x for x in metrics if x.concept_id == c1.id)
        self.assertEqual(m.source_count, 3)
        self.assertEqual(m.coverage_pct, 100.0)

    # 4. Concept distribution
    def test_concept_distribution(self):
        s1 = self._create_source("Source 1")
        s2 = self._create_source("Source 2")
        c1 = self._create_concept("Gradient Descent", 10)
        self._link_concept_source(c1.id, s1.id, 6)
        self._link_concept_source(c1.id, s2.id, 4)

        metrics = self.analytics_svc.get_concept_patterns()
        m = next(x for x in metrics if x.concept_id == c1.id)
        self.assertEqual(m.avg_occurrences_per_source, 5.0)

    # 5. Source overlap Jaccard
    def test_source_overlap_jaccard(self):
        s1 = self._create_source("Doc A")
        s2 = self._create_source("Doc B")
        c1 = self._create_concept("Concept 1")
        c2 = self._create_concept("Concept 2")
        c3 = self._create_concept("Concept 3")

        # Doc A has Concept 1 and Concept 2
        self._link_concept_source(c1.id, s1.id)
        self._link_concept_source(c2.id, s1.id)

        # Doc B has Concept 2 and Concept 3
        self._link_concept_source(c2.id, s2.id)
        self._link_concept_source(c3.id, s2.id)

        # Shared = {Concept 2} (1)
        # Union = {Concept 1, Concept 2, Concept 3} (3)
        # Jaccard = 1 / 3 = 0.3333
        overlap = self.analytics_svc.compare_sources(s1.id, s2.id)
        self.assertEqual(overlap.shared_count, 1)
        self.assertEqual(overlap.union_count, 3)
        self.assertAlmostEqual(overlap.overlap_ratio, 1.0 / 3.0, places=3)
        self.assertIn("1 shared concepts divided by 3 total unique concepts", overlap.explanation)

    # 6. Concept comparison
    def test_concept_comparison(self):
        s1 = self._create_source("Shared Paper")
        s2 = self._create_source("Separate Paper")
        c1 = self._create_concept("Deep Learning", 10)
        c2 = self._create_concept("Reinforcement Learning", 8)

        self._link_concept_source(c1.id, s1.id, 6)
        self._link_concept_source(c2.id, s1.id, 5)
        self._link_concept_source(c1.id, s2.id, 4)
        self._link_cooccurrence(c1.id, c2.id, shared_sources=1, strength=0.7)

        comp = self.analytics_svc.compare_concepts(c1.id, c2.id)
        self.assertEqual(comp.shared_source_count, 1)
        self.assertEqual(comp.shared_sources[0]["id"], s1.id)
        self.assertEqual(comp.cooccurrence_strength, 0.7)
        self.assertIn("co-occur in 1 shared research sources", comp.explanation)

    # 7. Source comparison
    def test_source_comparison(self):
        s1 = self._create_source("Paper One", word_count=1200)
        s2 = self._create_source("Paper Two", word_count=800)
        c1 = self._create_concept("Optimization")
        self._link_concept_source(c1.id, s1.id)

        overlap = self.analytics_svc.compare_sources(s1.id, s2.id)
        self.assertIn("unique_concepts_a", overlap.to_dict())
        self.assertIn("Optimization", overlap.unique_concepts_a)
        self.assertEqual(len(overlap.unique_concepts_b), 0)

    # 8. Temporal aggregation
    def test_temporal_aggregation(self):
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).isoformat()
        today = now.isoformat()

        self._create_source("Old Source", created_at=yesterday)
        self._create_source("New Source", created_at=today)

        trends = self.analytics_svc.get_temporal_trends(interval="daily")
        self.assertGreaterEqual(len(trends.data_points), 1)

    # 9. Trend detection: Insufficient history
    def test_trend_detection_insufficient_history(self):
        calc = TemporalAnalyticsCalculator(self.db)
        # Single source
        ts_map = {"s1": datetime.now(timezone.utc)}
        status, desc, ratio = calc.calculate_concept_trend("c1", {"s1"}, ts_map)
        self.assertEqual(status, TrendStatus.INSUFFICIENT_HISTORY.value)
        self.assertIn("More time-based observations are required", desc)

    # 10. Trend detection: Growing
    def test_trend_detection_growing(self):
        calc = TemporalAnalyticsCalculator(self.db)
        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2025, 2, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 3, 1, tzinfo=timezone.utc)
        t3 = datetime(2025, 4, 1, tzinfo=timezone.utc)

        ts_map = {"s1": t0, "s2": t1, "s3": t2, "s4": t3}
        # Older half: s1, s2. Newer half: s3, s4.
        # Concept appears in 1 older source and 2 newer sources (ratio = 2/1 = 2.0 >= 1.5)
        cpt_sources = {"s1", "s3", "s4"}
        status, desc, ratio = calc.calculate_concept_trend("c1", cpt_sources, ts_map)
        self.assertEqual(status, TrendStatus.GROWING.value)
        self.assertGreaterEqual(ratio, 1.5)

    # 11. Trend detection: Declining
    def test_trend_detection_declining(self):
        calc = TemporalAnalyticsCalculator(self.db)
        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2025, 2, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 3, 1, tzinfo=timezone.utc)
        t3 = datetime(2025, 4, 1, tzinfo=timezone.utc)

        ts_map = {"s1": t0, "s2": t1, "s3": t2, "s4": t3}
        # Older half: s1, s2. Newer half: s3, s4.
        # Concept appears in both older sources, but 0 newer sources (rate 0/2 = 0 <= 0.5)
        # Note: if new_count is 0 and old_count is 2, ratio is 0.0 <= 0.5 -> Declining
        cpt_sources = {"s1", "s2"}
        status, desc, ratio = calc.calculate_concept_trend("c1", cpt_sources, ts_map)
        self.assertEqual(status, TrendStatus.DECLINING.value)

    # 12. Trend detection: Stable
    def test_trend_detection_stable(self):
        calc = TemporalAnalyticsCalculator(self.db)
        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2025, 2, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 3, 1, tzinfo=timezone.utc)
        t3 = datetime(2025, 4, 1, tzinfo=timezone.utc)

        ts_map = {"s1": t0, "s2": t1, "s3": t2, "s4": t3}
        # 1 in older half, 1 in newer half -> ratio = 1.0 -> Stable
        cpt_sources = {"s1", "s3"}
        status, desc, ratio = calc.calculate_concept_trend("c1", cpt_sources, ts_map)
        self.assertEqual(status, TrendStatus.STABLE.value)

    # 13. Trend detection: Recently Detected
    def test_trend_detection_recently_detected(self):
        calc = TemporalAnalyticsCalculator(self.db)
        t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2025, 2, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 3, 1, tzinfo=timezone.utc)
        t3 = datetime(2025, 4, 1, tzinfo=timezone.utc)

        ts_map = {"s1": t0, "s2": t1, "s3": t2, "s4": t3}
        # 0 in older half, 1 in newer half -> Recently Detected
        cpt_sources = {"s4"}
        status, desc, ratio = calc.calculate_concept_trend("c1", cpt_sources, ts_map)
        self.assertEqual(status, TrendStatus.RECENTLY_DETECTED.value)

    # 14. Coverage calculation
    def test_coverage_calculation(self):
        s1 = self._create_source("Doc 1")
        s2 = self._create_source("Doc 2")
        c1 = self._create_concept("Multi Concept")
        c2 = self._create_concept("Single Concept")

        self._link_concept_source(c1.id, s1.id)
        self._link_concept_source(c1.id, s2.id)
        self._link_concept_source(c2.id, s1.id)

        cov = self.analytics_svc.get_coverage_analysis()
        self.assertEqual(cov.single_source_concepts_count, 1)
        self.assertEqual(cov.multi_source_concepts_count, 1)
        self.assertEqual(cov.single_source_concepts_pct, 50.0)

    # 15. Low coverage detection
    def test_low_coverage_detection(self):
        s1 = self._create_source("Solo Source")
        c1 = self._create_concept("Isolated Term")
        self._link_concept_source(c1.id, s1.id)

        cov = self.analytics_svc.get_coverage_analysis()
        low_ids = [x["id"] for x in cov.low_coverage_concepts]
        self.assertIn(c1.id, low_ids)

    # 16. High connectivity detection
    def test_high_connectivity_detection(self):
        c1 = self._create_concept("Hub Concept")
        for i in range(5):
            other = self._create_concept(f"Neighbor {i}")
            self._link_cooccurrence(c1.id, other.id, shared_sources=2, strength=0.8)

        cov = self.analytics_svc.get_coverage_analysis()
        high_conn = [x for x in cov.highly_connected_concepts if x["id"] == c1.id]
        self.assertEqual(len(high_conn), 1)
        self.assertEqual(high_conn[0]["connection_count"], 5)

    # 17. Low connectivity detection
    def test_low_connectivity_detection(self):
        c1 = self._create_concept("Island Concept")
        cov = self.analytics_svc.get_coverage_analysis()
        iso = [x for x in cov.isolated_concepts if x["id"] == c1.id]
        self.assertEqual(len(iso), 1)
        self.assertEqual(iso[0]["connection_count"], 0)

    # 18. Investigation statistics
    def test_investigation_statistics(self):
        inv = Investigation(title="Analytics Inv", research_question="Does it calculate?", status="active")
        self.inv_repo.save(inv)
        src = self._create_source("Inv Source")
        self.inv_repo.add_source(inv.id, src.id)
        ev = InvestigationEvidence(
            investigation_id=inv.id,
            source_id=src.id,
            statement="Sample evidence statement",
        )
        self.inv_repo.save_evidence(ev)

        snapshot = self.analytics_svc.get_collection_snapshot()
        self.assertEqual(snapshot.total_investigations, 1)
        self.assertEqual(snapshot.total_evidence, 1)
        self.assertEqual(snapshot.avg_evidence_per_investigation, 1.0)
        self.assertEqual(snapshot.avg_sources_per_investigation, 1.0)

    # 19. Evidence coverage classification
    def test_evidence_coverage_classification(self):
        analyzer = CoverageAnalyzer(self.db)
        inv = Investigation(title="Early Inv", research_question="Early?", status="active")
        self.inv_repo.save(inv)

        cov = analyzer.get_coverage_analysis()
        inv_item = next(x for x in cov.investigation_coverage if x["id"] == inv.id)
        self.assertEqual(inv_item["coverage_label"], "Early-stage")

    # 20. Open question analysis
    def test_open_question_analysis(self):
        inv = Investigation(title="Question Inv", research_question="Q?", status="active")
        self.inv_repo.save(inv)
        q = InvestigationQuestion(investigation_id=inv.id, question="Open matter?", status="OPEN")
        self.inv_repo.save_question(q)

        snapshot = self.analytics_svc.get_collection_snapshot()
        self.assertEqual(snapshot.total_open_questions, 1)

    # 21. Pattern generation
    def test_pattern_generation(self):
        s1 = self._create_source("Source A")
        s2 = self._create_source("Source B")
        c1 = self._create_concept("Universal Concept", 10)
        self._link_concept_source(c1.id, s1.id)
        self._link_concept_source(c1.id, s2.id)

        patterns = self.analytics_svc.get_patterns()
        self.assertGreaterEqual(len(patterns), 1)
        types = [p.pattern_type for p in patterns]
        self.assertIn(PatternType.HIGH_SOURCE_COVERAGE.value, types)

    # 22. Pattern explanation
    def test_pattern_explanation(self):
        s1 = self._create_source("Source A")
        s2 = self._create_source("Source B")
        c1 = self._create_concept("Explainable Concept", 10)
        self._link_concept_source(c1.id, s1.id)
        self._link_concept_source(c1.id, s2.id)

        patterns = self.analytics_svc.get_patterns()
        p = next(x for x in patterns if x.pattern_type == PatternType.HIGH_SOURCE_COVERAGE.value)
        self.assertIn("Source coverage", p.calculation_formula)
        self.assertIn(c1.id, p.concept_ids)

    # 23. Time filtering
    def test_time_filtering(self):
        now = datetime.now(timezone.utc)
        ancient = (now - timedelta(days=400)).isoformat()
        recent = now.isoformat()

        self._create_source("Ancient Source", created_at=ancient)
        self._create_source("Recent Source", created_at=recent)

        snap_all = self.analytics_svc.get_collection_snapshot(time_range="all")
        self.assertEqual(snap_all.total_sources, 2)

        snap_7d = self.analytics_svc.get_collection_snapshot(time_range="7d")
        self.assertEqual(snap_7d.total_sources, 1)

    # 24. Empty dataset behavior
    def test_empty_dataset(self):
        snapshot = self.analytics_svc.get_collection_snapshot()
        self.assertEqual(snapshot.total_sources, 0)
        self.assertEqual(snapshot.total_concepts, 0)
        self.assertEqual(snapshot.avg_concepts_per_source, 0.0)

        patterns = self.analytics_svc.get_patterns()
        self.assertEqual(len(patterns), 0)

        coverage = self.analytics_svc.get_coverage_analysis()
        self.assertEqual(coverage.total_sources, 0)
        self.assertEqual(coverage.single_source_concepts_count, 0)

    # 25. Single source dataset behavior
    def test_single_source_dataset(self):
        s = self._create_source("Lone Source")
        c = self._create_concept("Lone Concept")
        self._link_concept_source(c.id, s.id)

        snapshot = self.analytics_svc.get_collection_snapshot()
        self.assertEqual(snapshot.total_sources, 1)
        self.assertEqual(snapshot.total_concepts, 1)
        self.assertEqual(snapshot.avg_concepts_per_source, 1.0)


class TestAnalyticsUI(unittest.TestCase):
    """Integration tests for web views and REST APIs for Phase 9 Research Analytics."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_analytics_ui.db"
        self.config = Config(
            app_name="ORVIA",
            version="0.1.0",
            database_path=self.db_path,
            log_level="ERROR",
            debug=False,
        )
        self.config.ensure_directories()
        self.app = create_app(self.config)
        self.client = self.app.test_client()

        with self.app.app_context():
            from orvia.app.ui import get_db
            db = get_db()
            src_repo = SourceRepository(db)
            cpt_repo = ConceptRepository(db)

            s1 = Source(id="src-ui-1", title="UI Paper 1", content="Content of paper 1.")
            s2 = Source(id="src-ui-2", title="UI Paper 2", content="Content of paper 2.")
            src_repo.save(s1)
            src_repo.save(s2)

            c1 = Concept(id="cpt-ui-1", name="Neural Representation", frequency=8)
            cpt_repo.save(c1)

            db.execute(
                "INSERT INTO concept_source_links (concept_id, source_id, occurrences, in_title, first_seen_at) VALUES (?, ?, ?, ?, ?);",
                (c1.id, s1.id, 5, 0, datetime.now(timezone.utc).isoformat()),
            )
            db.execute(
                "INSERT INTO concept_source_links (concept_id, source_id, occurrences, in_title, first_seen_at) VALUES (?, ?, ?, ?, ?);",
                (c1.id, s2.id, 3, 0, datetime.now(timezone.utc).isoformat()),
            )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 26. GET /analyze web page
    def test_ui_analyze_page(self):
        res = self.client.get("/analyze")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        # Required test assertions from tests/test_ui.py
        self.assertIn("Analyze & Synthesize", html)
        self.assertIn("Cross-Source Comparison", html)
        self.assertIn("Collection Totals", html)

    # 27. GET /api/analytics/overview
    def test_api_analytics_overview(self):
        res = self.client.get("/api/analytics/overview")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("snapshot", data)
        self.assertEqual(data["snapshot"]["total_sources"], 2)

    # 28. GET /api/analytics/patterns
    def test_api_analytics_patterns(self):
        res = self.client.get("/api/analytics/patterns")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("patterns", data)

    # 29. GET /api/analytics/concepts
    def test_api_analytics_concepts(self):
        res = self.client.get("/api/analytics/concepts")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(len(data["concepts"]), 1)
        self.assertEqual(data["concepts"][0]["name"], "Neural Representation")

    # 30. GET /api/analytics/sources
    def test_api_analytics_sources(self):
        res = self.client.get("/api/analytics/sources")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(len(data["sources"]), 2)

    # 31. GET /api/analytics/temporal
    def test_api_analytics_temporal(self):
        res = self.client.get("/api/analytics/temporal?interval=daily")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("temporal", data)

    # 32. GET /api/analytics/coverage
    def test_api_analytics_coverage(self):
        res = self.client.get("/api/analytics/coverage")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("coverage", data)
        self.assertEqual(data["coverage"]["total_sources"], 2)

    # 33. GET /api/analytics/compare/sources
    def test_api_analytics_compare_sources(self):
        res = self.client.get("/api/analytics/compare/sources?source_a=src-ui-1&source_b=src-ui-2")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["comparison"]["shared_count"], 1)
        self.assertEqual(data["comparison"]["overlap_ratio"], 1.0)

    # 34. GET /api/analytics/compare/concepts
    def test_api_analytics_compare_concepts(self):
        with self.app.app_context():
            from orvia.app.ui import get_db
            db = get_db()
            c2 = Concept(id="cpt-ui-2", name="Sparse Matrix", frequency=3)
            ConceptRepository(db).save(c2)

        res = self.client.get("/api/analytics/compare/concepts?concept_a=cpt-ui-1&concept_b=cpt-ui-2")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("comparison", data)

    # 35. Missing arguments in comparator
    def test_api_analytics_compare_missing_args(self):
        res = self.client.get("/api/analytics/compare/sources?source_a=src-ui-1")
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["status"], "error")


if __name__ == "__main__":
    unittest.main()
