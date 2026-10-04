"""
Integration tests for ORVIA Phase 5 Search Intelligence UI Routes & API Endpoints.
"""
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from orvia.app.core.config import Config
from orvia.app.ui import create_app


class TestSearchUI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_orvia_search_ui.db"
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
        db = self.app.config.get("ORVIA_DB")
        if db:
            db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _import_sample_source(self, title: str, content: str, filename: str = "sample.txt"):
        data = {
            "file": (io.BytesIO(content.encode("utf-8")), filename),
            "title": title,
        }
        res = self.client.post("/api/sources/import", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        return res.get_json()["source_id"]

    def test_search_page_initial_state(self):
        """GET /search without query renders clean initial search interface."""
        res = self.client.get("/search")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Search across your research workspace", html)
        self.assertIn("search-field", html)
        self.assertIn("search-submit-btn", html)
        self.assertIn('name="q"', html)

    def test_search_page_with_results(self):
        """GET /search?q=... renders ranked results with highlights and BM25 scores."""
        self._import_sample_source(
            title="Transformer Attention Mechanisms",
            content="Self-attention allows the model to associate each word in the input with other words in the sequence.",
            filename="transformer.txt",
        )

        res = self.client.get("/search?q=attention")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Transformer Attention Mechanisms", html)
        self.assertIn("BM25", html)
        self.assertIn('<mark class="search-highlight">', html)
        self.assertIn("</mark>", html)
        self.assertIn("search-result-card", html)
        self.assertIn("results for", html)

    def test_search_page_filters_and_sorting(self):
        """Filters by file type and applies sort ordering."""
        self._import_sample_source(
            title="Text Research Notes",
            content="Neural network architectures and deep learning fundamentals.",
            filename="notes.txt",
        )
        self._import_sample_source(
            title="JSON Model Benchmarks",
            content='{"model": "transformer", "neural_metric": 95.4}',
            filename="benchmarks.json",
        )

        # Filter by TXT
        res_txt = self.client.get("/search?q=neural&type=txt")
        self.assertEqual(res_txt.status_code, 200)
        html_txt = res_txt.get_data(as_text=True)
        self.assertIn("Text Research Notes", html_txt)

        # Sort parameter
        res_sort = self.client.get("/search?q=neural&sort=newest")
        self.assertEqual(res_sort.status_code, 200)

    def test_search_page_empty_results(self):
        """Searching for non-existent terms renders helpful empty state."""
        res = self.client.get("/search?q=nonexistentcrypticterm123")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("No results found for", html)
        self.assertIn("Try searching for broader keywords", html)

    def test_api_search_missing_query(self):
        """GET /api/search without q parameter returns 400 error."""
        res = self.client.get("/api/search")
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("Query parameter 'q' is required", data["error"])

    def test_api_search_success_json_contract(self):
        """GET /api/search returns valid JSON schema with hits, latency, and snippet markup."""
        self._import_sample_source(
            title="Vector Index Algorithms",
            content="Inverted indices and BM25 ranking algorithms form the foundation of lexical information retrieval.",
            filename="retrieval.txt",
        )

        res = self.client.get("/api/search?q=retrieval")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["query"], "retrieval")
        self.assertGreaterEqual(data["total_hits"], 1)
        self.assertGreaterEqual(data["duration_ms"], 0.0)
        self.assertIsInstance(data["results"], list)

        first_hit = data["results"][0]
        self.assertIn("id", first_hit)
        self.assertIn("title", first_hit)
        self.assertIn("score", first_hit)
        self.assertIn("snippet", first_hit)
        self.assertIn("file_type", first_hit)
        self.assertIn('<mark class="search-highlight">', first_hit["snippet"])

    def test_auto_indexing_on_import_and_deletion(self):
        """Importing a source automatically indexes it, deleting removes it from search."""
        # 1. Import a source with a distinct keyword
        src_id = self._import_sample_source(
            title="Quasar Astrophysics Study",
            content="Observations of supermassive black holes emitting relativistic jets across astronomical distances.",
            filename="quasar.txt",
        )

        # 2. Immediately searchable
        res = self.client.get("/api/search?q=relativistic")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertGreaterEqual(data["total_hits"], 1)
        hit_titles = [r["title"] for r in data["results"]]
        self.assertTrue(any("Quasar" in t for t in hit_titles))

        # 3. Delete the source
        del_res = self.client.post(f"/api/sources/{src_id}/delete")
        self.assertEqual(del_res.status_code, 200)

        # 4. No longer returned in search results
        res_after = self.client.get("/api/search?q=relativistic")
        self.assertEqual(res_after.status_code, 200)
        data_after = res_after.get_json()
        self.assertEqual(data_after["total_hits"], 0)

    def test_reindexing_on_title_edit(self):
        """Updating a source title immediately updates search index."""
        src_id = self._import_sample_source(
            title="Old Generic Document",
            content="Some standard research notes on software architecture.",
            filename="doc.txt",
        )

        # Edit title
        edit_res = self.client.post(f"/api/sources/{src_id}/edit", json={"title": "Quantum Computing Paradigms"})
        self.assertEqual(edit_res.status_code, 200)

        # Search for new title term
        res = self.client.get("/api/search?q=quantum")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertGreaterEqual(data["total_hits"], 1)
        self.assertEqual(data["results"][0]["title"], "Quantum Computing Paradigms")

    def test_navigation_and_command_palette_links(self):
        """Search is linked in the sidebar navigation and command palette."""
        res = self.client.get("/overview")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('/search', html)
        self.assertIn('Jump to Search Intelligence', html)
