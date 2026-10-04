"""
tests/test_workspace.py
Phase 11 test suite: ResearchWorkspaceService, universal search,
activity recording, research tensions, index health, data integrity,
and API routes.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from orvia.app.core.config import Config
from orvia.app.core.database import DatabaseManager
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.investigation_repository import InvestigationRepository
from orvia.app.workspace.service import ResearchWorkspaceService
from orvia.app.workspace.models import (
    ActivityType,
    ResearchActivity,
    UniversalSearchResult,
    ResearchContext,
    ResearchTension,
    IndexHealth,
    DataIntegrityReport,
)

TEST_DB = Path(__file__).parent / "test_workspace.db"


def _make_config():
    return Config(
        app_name="ORVIA Test",
        version="test",
        database_path=TEST_DB,
        log_level="ERROR",
        debug=False,
    )


class TestWorkspaceModels(unittest.TestCase):
    """Test workspace domain models serialize correctly."""

    def test_activity_type_enum_values(self):
        self.assertEqual(ActivityType.SOURCE_IMPORTED.value, "source_imported")
        self.assertEqual(ActivityType.INVESTIGATION_CREATED.value, "investigation_created")
        self.assertEqual(ActivityType.EVIDENCE_RECORDED.value, "evidence_recorded")
        self.assertEqual(ActivityType.DEMO_LOADED.value, "demo_loaded")
        self.assertEqual(ActivityType.DEMO_CLEARED.value, "demo_cleared")

    def test_research_activity_to_dict(self):
        act = ResearchActivity(
            id="abc",
            activity_type="source_imported",
            entity_type="source",
            entity_id="src-1",
            title="Test Source Imported",
            description="Imported a test document.",
            metadata={"size": 512},
        )
        d = act.to_dict()
        self.assertEqual(d["id"], "abc")
        self.assertEqual(d["activity_type"], "source_imported")
        self.assertEqual(d["entity_type"], "source")
        self.assertEqual(d["title"], "Test Source Imported")
        self.assertIsInstance(d["metadata"], dict)

    def test_research_activity_from_dict_json_metadata(self):
        d = {
            "id": "xyz",
            "activity_type": "search_performed",
            "entity_type": "search",
            "entity_id": None,
            "title": "Searched for quantum",
            "description": "",
            "metadata": json.dumps({"query": "quantum"}),
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        act = ResearchActivity.from_dict(d)
        self.assertIsInstance(act.metadata, dict)
        self.assertEqual(act.metadata.get("query"), "quantum")

    def test_universal_search_result_to_dict(self):
        r = UniversalSearchResult(
            item_type="SOURCE",
            id="s1",
            title="Test Source",
            subtitle="PDF · 1200 words",
            url="/sources/s1",
            badge="Source",
        )
        d = r.to_dict()
        self.assertEqual(d["item_type"], "SOURCE")
        self.assertEqual(d["url"], "/sources/s1")

    def test_research_context_to_dict(self):
        ctx = ResearchContext(
            active_investigation_id="inv-1",
            breadcrumbs=[{"label": "Test", "url": "/investigations/inv-1"}],
        )
        d = ctx.to_dict()
        self.assertEqual(d["active_investigation_id"], "inv-1")
        self.assertIsInstance(d["breadcrumbs"], list)

    def test_research_tension_to_dict(self):
        t = ResearchTension(
            finding_id="f1",
            finding_title="Test Finding",
            tension_type="CONTRAST_EVIDENCE",
            description="2 evidence records marked as CONTRAST.",
            evidence_items=[{"id": "ev1", "statement": "contradicts X"}],
        )
        d = t.to_dict()
        self.assertEqual(d["tension_type"], "CONTRAST_EVIDENCE")

    def test_index_health_to_dict(self):
        h = IndexHealth(
            status="Healthy",
            total_sources=10,
            indexed_sources=10,
            indexed_terms=500,
            explanation="All 10 sources indexed.",
        )
        d = h.to_dict()
        self.assertEqual(d["status"], "Healthy")
        self.assertEqual(d["total_sources"], 10)

    def test_data_integrity_report_to_dict(self):
        r = DataIntegrityReport(
            healthy=True,
            total_checks=3,
            issues_count=0,
            warnings_count=0,
        )
        d = r.to_dict()
        self.assertTrue(d["healthy"])
        self.assertEqual(d["total_checks"], 3)


class TestResearchWorkspaceService(unittest.TestCase):
    """Test ResearchWorkspaceService with a real test DB."""

    @classmethod
    def setUpClass(cls):
        if TEST_DB.exists():
            TEST_DB.unlink()
        config = _make_config()
        config.ensure_directories()
        cls.db = DatabaseManager(config.DATABASE_PATH)
        cls.db.connect()
        cls.db.initialize_schema()
        cls.src_r = SourceRepository(cls.db)
        cls.con_r = ConceptRepository(cls.db)
        cls.inv_r = InvestigationRepository(cls.db)
        # Create a test investigation for foreign key validity
        cls.db.execute(
            """
            INSERT OR IGNORE INTO investigations (id, title, research_question, status, created_at, updated_at)
            VALUES ('test-inv-1', 'Test Investigation', 'What is being tested?', 'active', '2026-01-01T00:00:00', '2026-01-01T00:00:00')
            """
        )
        cls.svc = ResearchWorkspaceService(
            db=cls.db,
            source_repo=cls.src_r,
            concept_repo=cls.con_r,
            investigation_repo=cls.inv_r,
        )

    @classmethod
    def tearDownClass(cls):
        try:
            cls.db.disconnect()
        except Exception:
            pass
        try:
            if TEST_DB.exists():
                TEST_DB.unlink()
        except Exception:
            pass

    def test_record_activity_persists(self):
        act = self.svc.record_activity(
            activity_type=ActivityType.SOURCE_IMPORTED.value,
            entity_type="source",
            title="Test source imported",
            entity_id="src-test-1",
            description="A test source.",
            metadata={"size": 1024},
        )
        self.assertIsNotNone(act.id)
        self.assertEqual(act.activity_type, "source_imported")
        self.assertEqual(act.title, "Test source imported")

    def test_get_recent_activities_returns_list(self):
        for i in range(3):
            self.svc.record_activity(
                activity_type="search_performed",
                entity_type="search",
                title=f"Search #{i}",
            )
        activities = self.svc.get_recent_activities(limit=10)
        self.assertIsInstance(activities, list)
        self.assertGreater(len(activities), 0)
        if len(activities) >= 2:
            self.assertGreaterEqual(activities[0].created_at, activities[1].created_at)

    def test_get_recent_activities_respects_limit(self):
        activities = self.svc.get_recent_activities(limit=2)
        self.assertLessEqual(len(activities), 2)

    def test_get_continue_research_empty(self):
        result = self.svc.get_continue_research()
        self.assertIn("active_investigations", result)
        self.assertIn("draft_reports", result)
        self.assertIn("open_questions_total", result)
        self.assertIsInstance(result["active_investigations"], list)

    def test_get_context_returns_empty_when_unset(self):
        ctx = self.svc.get_context()
        self.assertIsInstance(ctx, ResearchContext)
        self.assertIsNone(ctx.active_investigation_id)

    def test_set_and_get_context(self):
        self.svc.set_context(investigation_id="test-inv-1")
        ctx = self.svc.get_context()
        self.assertEqual(ctx.active_investigation_id, "test-inv-1")

    def test_universal_search_empty_query(self):
        results = self.svc.universal_search("")
        self.assertEqual(results, [])

    def test_universal_search_short_query(self):
        results = self.svc.universal_search("a")
        self.assertEqual(results, [])

    def test_universal_search_returns_list(self):
        results = self.svc.universal_search("test")
        self.assertIsInstance(results, list)
        for r in results:
            self.assertIsInstance(r, UniversalSearchResult)
            self.assertIn(r.item_type, ["SOURCE", "CONCEPT", "INVESTIGATION", "REPORT", "EVIDENCE", "FINDING"])

    def test_detect_research_tensions_returns_list(self):
        tensions = self.svc.detect_research_tensions("nonexistent-inv-id")
        self.assertIsInstance(tensions, list)

    def test_get_index_health(self):
        health = self.svc.get_index_health()
        self.assertIsInstance(health, IndexHealth)
        self.assertIsInstance(health.total_sources, int)
        self.assertIsInstance(health.indexed_sources, int)
        self.assertIsInstance(health.status, str)
        self.assertIsInstance(health.explanation, str)
        self.assertGreater(len(health.status), 0)

    def test_get_data_integrity(self):
        report = self.svc.get_data_integrity()
        self.assertIsInstance(report, DataIntegrityReport)
        self.assertIsInstance(report.healthy, bool)
        self.assertIsInstance(report.total_checks, int)
        self.assertIsInstance(report.issues, list)
        self.assertIsInstance(report.warnings, list)

    def test_data_integrity_healthy_on_empty_db(self):
        report = self.svc.get_data_integrity()
        self.assertEqual(report.issues_count, 0)
        self.assertTrue(report.healthy)

    def test_compare_sources_returns_dict(self):
        result = self.svc.compare_sources("src-a", "src-b")
        self.assertIn("shared_concepts", result)
        self.assertIn("unique_to_a", result)
        self.assertIn("unique_to_b", result)
        self.assertIn("jaccard_overlap", result)
        self.assertIn("overlap_label", result)
        self.assertIn("Concept Overlap", result["overlap_label"])

    def test_compare_sources_jaccard_zero_when_empty(self):
        result = self.svc.compare_sources("none-a", "none-b")
        self.assertEqual(result["jaccard_overlap"], 0.0)


class TestPhase11APIRoutes(unittest.TestCase):
    """Test Phase 11 API routes via Flask test client."""

    @classmethod
    def setUpClass(cls):
        from orvia.app.ui import create_app
        config = Config(
            app_name="ORVIA Test",
            version="test",
            database_path=TEST_DB,
            log_level="ERROR",
            debug=False,
        )
        config.ensure_directories()
        app = create_app(config)
        app.config["TESTING"] = True
        with app.app_context():
            from orvia.app.ui import get_db
            db = get_db()
            db.execute(
                """
                INSERT OR IGNORE INTO investigations (id, title, research_question, status, created_at, updated_at)
                VALUES ('test-inv-1', 'Test Investigation', 'What is being tested?', 'active', '2026-01-01T00:00:00', '2026-01-01T00:00:00')
                """
            )
        cls.client = app.test_client()
        cls.app = app

    def test_universal_search_api_empty_query(self):
        resp = self.client.get('/api/universal-search?q=')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIsInstance(data['results'], list)

    def test_universal_search_api_with_query(self):
        resp = self.client.get('/api/universal-search?q=test')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('groups', data)

    def test_recent_activity_api(self):
        resp = self.client.get('/api/recent-activity')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIsInstance(data['activities'], list)

    def test_continue_research_api(self):
        resp = self.client.get('/api/continue-research')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('active_investigations', data)

    def test_context_api_get(self):
        resp = self.client.get('/api/context')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('context', data)

    def test_context_api_set(self):
        resp = self.client.post('/api/context',
                                json={'investigation_id': 'test-inv-1'},
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')

    def test_index_health_api(self):
        resp = self.client.get('/api/index-health')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('health', data)
        h = data['health']
        self.assertIn('status', h)
        self.assertIn('total_sources', h)
        self.assertIn('indexed_sources', h)

    def test_data_integrity_api(self):
        resp = self.client.get('/api/data-integrity')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('report', data)
        r = data['report']
        self.assertIn('healthy', r)
        self.assertIn('issues', r)

    def test_tensions_api_empty(self):
        resp = self.client.get('/api/investigations/nonexistent-id/tensions')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIsInstance(data['tensions'], list)

    def test_timeline_page(self):
        resp = self.client.get('/timeline')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Research Timeline', html)

    def test_compare_sources_page(self):
        resp = self.client.get('/compare-sources')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Source Comparison', html)

    def test_settings_page_has_keyboard_shortcuts(self):
        resp = self.client.get('/settings')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Keyboard Shortcuts', html)

    def test_settings_page_has_index_health(self):
        resp = self.client.get('/settings')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Search Index Health', html)

    def test_settings_page_has_data_integrity(self):
        resp = self.client.get('/settings')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Data Integrity', html)

    def test_overview_page_no_fake_numbers(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertNotIn('>128<', html)
        self.assertNotIn('>2,431<', html)
        self.assertNotIn("'128'", html)
        self.assertNotIn("'2,431'", html)


if __name__ == '__main__':
    unittest.main()
