"""
Test suite for ORVIA Phase 6 UI and API: Concept Intelligence.
Tests /concepts, /concepts/<id>, /api/concepts/*, and integrations.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from orvia.app.core.config import Config
from orvia.app.models.source import Source
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.ui import create_app


class TestConceptUI(unittest.TestCase):
    """Integration tests for Concept Intelligence web interface and API."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_orvia.db"
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
            repo = SourceRepository(db)

            s1 = Source(
                id="src-ui-1",
                title="Transformer Architecture Primer",
                content=(
                    "The transformer architecture relies on the self attention mechanism. "
                    "Self attention mechanisms model long range dependencies effectively. "
                    "Transformer networks have revolutionized natural language processing."
                ),
            )
            s2 = Source(
                id="src-ui-2",
                title="Self Attention and Convolution Comparison",
                content=(
                    "Self attention mechanisms capture global context better than convolution. "
                    "The computational cost of self attention scales quadratically. "
                    "Modern vision models blend convolution with self attention."
                ),
            )
            repo.save(s1)
            repo.save(s2)

    def tearDown(self):
        db = self.app.config.get("ORVIA_DB")
        if db:
            db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concepts_page_initial_and_empty(self):
        resp = self.client.get("/concepts")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Concept Intelligence", html)
        self.assertIn("Concepts Detected", html)

    def test_api_concepts_analyze_all(self):
        resp = self.client.post("/api/concepts/analyze")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertGreater(data["result"]["total_concepts"], 0)

    def test_concepts_page_with_data_and_filters(self):
        # Run analysis first
        self.client.post("/api/concepts/analyze")

        # GET /concepts list
        resp = self.client.get("/concepts")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Occurrences", html)

        # Filter by search
        resp_filtered = self.client.get("/concepts?q=attention")
        self.assertEqual(resp_filtered.status_code, 200)
        html_filtered = resp_filtered.data.decode("utf-8")
        self.assertIn("Attention", html_filtered)

        # Filter by single word
        resp_single = self.client.get("/concepts?ngram=1")
        self.assertEqual(resp_single.status_code, 200)

        # Filter by phrase
        resp_phrase = self.client.get("/concepts?ngram=2")
        self.assertEqual(resp_phrase.status_code, 200)

    def test_concept_detail_page(self):
        self.client.post("/api/concepts/analyze")

        # Get list of concepts from API
        api_resp = self.client.get("/api/concepts")
        self.assertEqual(api_resp.status_code, 200)
        concepts = api_resp.get_json()["concepts"]
        self.assertGreater(len(concepts), 0)

        concept_id = concepts[0]["id"]
        detail_resp = self.client.get(f"/concepts/{concept_id}")
        self.assertEqual(detail_resp.status_code, 200)
        detail_html = detail_resp.data.decode("utf-8")
        self.assertIn("DETECTED CONCEPT", detail_html)
        self.assertIn("Sources Containing This Concept", detail_html)
        self.assertIn("Related Concepts", detail_html)

    def test_concept_detail_404_on_invalid_id(self):
        resp = self.client.get("/concepts/non-existent-id")
        self.assertEqual(resp.status_code, 404)

    def test_api_concept_endpoints(self):
        self.client.post("/api/concepts/analyze")

        # API: list
        resp = self.client.get("/api/concepts")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertGreater(data["total"], 0)

        concept_id = data["concepts"][0]["id"]

        # API: detail
        resp_det = self.client.get(f"/api/concepts/{concept_id}")
        self.assertEqual(resp_det.status_code, 200)
        det_data = resp_det.get_json()
        self.assertEqual(det_data["status"], "ok")
        self.assertIn("sources", det_data["concept"])

        # API: summary
        resp_sum = self.client.get("/api/concepts/summary")
        self.assertEqual(resp_sum.status_code, 200)
        sum_data = resp_sum.get_json()
        self.assertEqual(sum_data["status"], "ok")
        self.assertGreater(sum_data["total_concepts"], 0)

        # API: rebuild relationships
        resp_rel = self.client.post("/api/concepts/rebuild-relationships")
        self.assertEqual(resp_rel.status_code, 200)
        rel_data = resp_rel.get_json()
        self.assertEqual(rel_data["status"], "ok")

    def test_source_detail_integration(self):
        self.client.post("/api/concepts/analyze")

        resp = self.client.get("/sources/src-ui-1")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Detected Concepts", html)
        self.assertIn("Analyzed", html)

    def test_overview_integration(self):
        self.client.post("/api/concepts/analyze")

        resp = self.client.get("/overview")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Recently Discovered", html)


if __name__ == "__main__":
    unittest.main()
