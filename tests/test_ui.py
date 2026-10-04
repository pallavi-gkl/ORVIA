"""
Unit tests for ORVIA Phase 2 UI Shell & Routes
"""
import unittest
from pathlib import Path
import tempfile
import shutil

from orvia.app.core.config import Config
from orvia.app.ui import create_app


class TestUIShell(unittest.TestCase):
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

    def tearDown(self):
        # Close database connection bound to app
        db = self.app.config.get("ORVIA_DB")
        if db:
            db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_overview_route(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("ORVIA", html)
        self.assertIn("Explore Information.", html)
        self.assertIn("Discover What Connects.", html)
        self.assertIn("stat-grid", html)
        self.assertIn("Research Investigations", html)

    def test_investigations_route(self):
        response = self.client.get("/investigations")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Research Investigations", html)
        self.assertIn("Start with a question you're curious about.", html)

    def test_explore_route(self):
        response = self.client.get("/explore")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Explore", html)
        self.assertIn("Bring your first piece of information into ORVIA.", html)

    def test_analyze_route(self):
        response = self.client.get("/analyze")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Analyze & Synthesize", html)
        self.assertIn("Cross-Source Comparison", html)

    def test_knowledge_route(self):
        response = self.client.get("/knowledge")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Knowledge Graph & Topology", html)

    def test_reports_route(self):
        response = self.client.get("/reports")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Research Reports & Synthesis", html)

    def test_settings_route(self):
        response = self.client.get("/settings")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Workspace Settings", html)
        self.assertIn(str(self.db_path), html)

    def test_api_stats_endpoint(self):
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("sources", data["stats"])
        self.assertIn("documents", data["stats"])
        self.assertIn("topics", data["stats"])
        self.assertIn("concepts", data["stats"])
        self.assertIn("investigations", data["stats"])

    def test_command_palette_and_search_trigger_in_dom(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertIn('id="cmd-search-trigger"', html)
        self.assertIn('id="cmd-palette-overlay"', html)
        self.assertIn("Ctrl K", html)

    def test_sidebar_structure(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertIn('id="app-sidebar"', html)
        self.assertIn('id="sidebar-toggle-btn"', html)
        self.assertIn('class="logo-mark"', html)

    def test_404_handler(self):
        response = self.client.get("/nonexistent-page-xyz")
        self.assertEqual(response.status_code, 404)
        html = response.get_data(as_text=True)
        self.assertIn("Location not found in workspace", html)

    def test_explore_capture_ui(self):
        response = self.client.get("/explore")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="cr-open-btn"', html)
        self.assertIn('id="cr-overlay"', html)
        self.assertIn("Capture Research", html)
        self.assertIn("Bring information into your research space.", html)
        self.assertIn("Upload Files", html)
        self.assertIn("Paste Content", html)
        self.assertIn("Create Research Note", html)
        self.assertIn("Import Folder", html)

    def test_api_source_paste(self):
        # 1. Validation: title required
        res = self.client.post("/api/sources/paste", json={"title": "", "content": "Sample content"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Title is required", res.get_json()["error"])

        # 2. Validation: content required
        res = self.client.post("/api/sources/paste", json={"title": "Test Title", "content": ""})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Content cannot be empty", res.get_json()["error"])

        # 3. Successful paste
        res = self.client.post(
            "/api/sources/paste",
            json={
                "title": "Quantum Error Correction Note",
                "content": "Surface codes provide a topological quantum error correcting code with a 2D square lattice of physical qubits.",
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["title"], "Quantum Error Correction Note")
        self.assertTrue(data["source_id"])
        self.assertGreater(data["word_count"], 0)

        # 4. Duplicate detection
        dup_res = self.client.post(
            "/api/sources/paste",
            json={
                "title": "Another Note",
                "content": "Surface codes provide a topological quantum error correcting code with a 2D square lattice of physical qubits.",
            },
        )
        self.assertEqual(dup_res.status_code, 409)
        dup_data = dup_res.get_json()
        self.assertEqual(dup_data["status"], "duplicate")
        self.assertEqual(dup_data["duplicate_id"], data["source_id"])

        # 5. Force duplicate import
        force_res = self.client.post(
            "/api/sources/paste",
            json={
                "title": "Forced Duplicate Note",
                "content": "Surface codes provide a topological quantum error correcting code with a 2D square lattice of physical qubits.",
                "force": True,
            },
        )
        self.assertEqual(force_res.status_code, 200)
        self.assertEqual(force_res.get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
