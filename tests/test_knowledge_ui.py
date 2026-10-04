"""
Integration test suite for ORVIA Phase 7: Knowledge Graph UI & REST APIs.
Tests web routes /knowledge, /knowledge/graph, /api/knowledge/graph/*, and cross-page links.
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


class TestKnowledgeUI(unittest.TestCase):
    """Integration tests for Knowledge Graph web UI and REST API endpoints."""

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
                id="src-ui-kg-1",
                title="Neural Representation Learning",
                content=(
                    "Self attention mechanisms model long range sequence dependencies. "
                    "Transformer networks rely on self attention for parallel computation. "
                    "Representation learning captures semantic relationships."
                ),
            )
            s2 = Source(
                id="src-ui-kg-2",
                title="Vision Transformer Systems",
                content=(
                    "Vision transformers divide images into discrete patches. "
                    "Self attention mechanisms connect image patches effectively. "
                    "Transformer models excel across computer vision benchmarks."
                ),
            )
            repo.save(s1)
            repo.save(s2)

        # Analyze sources to produce concepts and co-occurrences
        self.client.post("/api/concepts/analyze")

    def tearDown(self):
        db = self.app.config.get("ORVIA_DB")
        if db:
            db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_knowledge_page_route(self):
        """GET /knowledge renders graph workspace and toolbar."""
        resp = self.client.get("/knowledge")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Knowledge Graph", html)
        self.assertIn("knowledge-graph-svg", html)
        self.assertIn("graph-detail-panel", html)
        self.assertIn("Overview", html)
        self.assertIn("Focus", html)

    def test_knowledge_graph_alias_route(self):
        """GET /knowledge/graph works identically."""
        resp = self.client.get("/knowledge/graph")
        self.assertEqual(resp.status_code, 200)

    def test_api_knowledge_graph_endpoint(self):
        """GET /api/knowledge/graph returns valid JSON schema."""
        resp = self.client.get("/api/knowledge/graph")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("graph", data)
        self.assertIn("nodes", data["graph"])
        self.assertIn("edges", data["graph"])
        self.assertIn("metadata", data["graph"])
        self.assertGreater(len(data["graph"]["nodes"]), 0)

    def test_api_knowledge_graph_filtering(self):
        """GET /api/knowledge/graph supports max_nodes and mode params."""
        resp = self.client.get("/api/knowledge/graph?max_nodes=5&mode=overview")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertLessEqual(len(data["graph"]["nodes"]), 5)

    def test_api_knowledge_graph_stats(self):
        """GET /api/knowledge/graph/stats returns graph metrics."""
        resp = self.client.get("/api/knowledge/graph/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        stats = data["stats"]
        self.assertIn("total_concepts", stats)
        self.assertIn("total_relationships", stats)
        self.assertIn("density", stats)
        self.assertIn("average_degree", stats)
        self.assertGreater(stats["total_concepts"], 0)

    def test_api_knowledge_graph_search(self):
        """GET /api/knowledge/graph/search returns matching concepts."""
        resp = self.client.get("/api/knowledge/graph/search?q=attention")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertGreater(data["results"]["total_matches"], 0)

    def test_api_knowledge_graph_concept_neighborhood(self):
        """GET /api/knowledge/graph/concept/<id> returns focused subgraph."""
        api_resp = self.client.get("/api/concepts")
        concepts = api_resp.get_json()["concepts"]
        self.assertGreater(len(concepts), 0)

        cid = concepts[0]["id"]
        resp = self.client.get(f"/api/knowledge/graph/concept/{cid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("nodes", data["graph"])

    def test_api_knowledge_graph_rebuild(self):
        """POST /api/knowledge/graph/rebuild invalidates cache and returns fresh stats."""
        resp = self.client.post("/api/knowledge/graph/rebuild")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("stats", data)

    def test_overview_and_concept_cross_links(self):
        """Overview and Concept Detail cross-link into Knowledge Graph."""
        # 1. Overview has Knowledge Connections
        resp_ov = self.client.get("/overview")
        self.assertEqual(resp_ov.status_code, 200)
        html_ov = resp_ov.data.decode("utf-8")
        self.assertIn("Knowledge Connections", html_ov)
        self.assertIn("Explore Knowledge Graph", html_ov)

        # 2. Concept Detail has Explore in Graph
        api_resp = self.client.get("/api/concepts")
        cid = api_resp.get_json()["concepts"][0]["id"]
        resp_cd = self.client.get(f"/concepts/{cid}")
        self.assertEqual(resp_cd.status_code, 200)
        html_cd = resp_cd.data.decode("utf-8")
        self.assertIn("Explore in Graph", html_cd)


if __name__ == "__main__":
    unittest.main()
