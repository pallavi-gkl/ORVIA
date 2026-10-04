"""
Comprehensive tests for ORVIA Phase 4 Source Intelligence Routes & UI Endpoints
"""
import io
import json
import unittest
from pathlib import Path
import tempfile
import shutil

from orvia.app.core.config import Config
from orvia.app.ui import create_app


class TestSourceIntelligenceUI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_orvia_sources.db"
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

    def test_sources_page_empty_state(self):
        response = self.client.get("/sources")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Sources", html)
        self.assertIn("Your research library is empty.", html)
        self.assertIn("0 INDEXED SOURCES", html)
        self.assertIn("seed-demo-btn", html)
        self.assertIn("open-add-source-modal-btn", html)

    def test_import_text_file(self):
        content = b"Attention Is All You Need\n\nThe dominant sequence transduction models are based on complex recurrent or convolutional neural networks."
        data = {
            "file": (io.BytesIO(content), "attention_paper.txt"),
            "title": "Attention Mechanisms Paper",
        }
        response = self.client.post("/api/sources/import", data=data, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertEqual(json_data["status"], "ok")
        self.assertEqual(json_data["title"], "Attention Mechanisms Paper")
        self.assertEqual(json_data["filename"], "attention_paper.txt")
        self.assertEqual(json_data["file_type"], "txt")
        self.assertGreater(json_data["word_count"], 10)
        self.assertIn("source_id", json_data)

    def test_import_csv_file(self):
        csv_bytes = b"model,tokens_per_sec,latency_ms\nmodel-a,145.2,18.4\nmodel-b,230.1,12.1\n"
        data = {
            "file": (io.BytesIO(csv_bytes), "benchmarks.csv"),
        }
        response = self.client.post("/api/sources/import", data=data, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertEqual(json_data["status"], "ok")
        self.assertEqual(json_data["file_type"], "csv")
        self.assertEqual(json_data["stats"]["row_count"], 2)
        self.assertEqual(json_data["stats"]["column_count"], 3)

    def test_import_json_file(self):
        obj = {"framework": "ORVIA", "architecture": "Modular", "tier": "Intelligence"}
        json_bytes = json.dumps(obj).encode("utf-8")
        data = {
            "file": (io.BytesIO(json_bytes), "arch.json"),
        }
        response = self.client.post("/api/sources/import", data=data, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertEqual(json_data["status"], "ok")
        self.assertEqual(json_data["file_type"], "json")
        self.assertEqual(json_data["stats"]["item_count"], 3)

    def test_duplicate_detection_and_force(self):
        content = b"Deterministic hash verification content."
        data1 = {"file": (io.BytesIO(content), "doc1.txt")}
        r1 = self.client.post("/api/sources/import", data=data1, content_type="multipart/form-data")
        self.assertEqual(r1.status_code, 200)
        first_id = r1.get_json()["source_id"]

        # Attempt same content again
        data2 = {"file": (io.BytesIO(content), "doc2.txt")}
        r2 = self.client.post("/api/sources/import", data=data2, content_type="multipart/form-data")
        self.assertEqual(r2.status_code, 409)
        j2 = r2.get_json()
        self.assertEqual(j2["status"], "duplicate")
        self.assertEqual(j2["duplicate_id"], first_id)

        # Force duplicate
        data3 = {"file": (io.BytesIO(content), "doc2_forced.txt"), "force": "true"}
        r3 = self.client.post("/api/sources/import", data=data3, content_type="multipart/form-data")
        self.assertEqual(r3.status_code, 200)
        self.assertNotEqual(r3.get_json()["source_id"], first_id)

    def test_import_unsupported_file_fails(self):
        data = {"file": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "diagram.png")}
        r = self.client.post("/api/sources/import", data=data, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["status"], "error")

    def test_source_detail_view(self):
        content = b"Paragraph 1.\n\nParagraph 2 with details."
        data = {"file": (io.BytesIO(content), "research.txt"), "title": "Inspection Test"}
        r = self.client.post("/api/sources/import", data=data, content_type="multipart/form-data")
        source_id = r.get_json()["source_id"]

        detail_response = self.client.get(f"/sources/{source_id}")
        self.assertEqual(detail_response.status_code, 200)
        html = detail_response.get_data(as_text=True)
        self.assertIn("Inspection Test", html)
        self.assertIn("research.txt", html)
        self.assertIn("Deterministic Metrics", html)
        self.assertIn("Fingerprint (SHA-256)", html)
        self.assertIn("Content Preview", html)

    def test_source_detail_404(self):
        r = self.client.get("/sources/nonexistent-id-000")
        self.assertEqual(r.status_code, 404)

    def test_update_source_title(self):
        data = {"file": (io.BytesIO(b"Simple note"), "note.txt")}
        r = self.client.post("/api/sources/import", data=data, content_type="multipart/form-data")
        source_id = r.get_json()["source_id"]

        edit_res = self.client.post(f"/api/sources/{source_id}/edit", json={"title": "Updated Research Note"})
        self.assertEqual(edit_res.status_code, 200)
        self.assertEqual(edit_res.get_json()["title"], "Updated Research Note")

        # Verify on detail page
        detail_res = self.client.get(f"/sources/{source_id}")
        self.assertIn("Updated Research Note", detail_res.get_data(as_text=True))

    def test_delete_source(self):
        data = {"file": (io.BytesIO(b"Temporary file"), "temp.txt")}
        r = self.client.post("/api/sources/import", data=data, content_type="multipart/form-data")
        source_id = r.get_json()["source_id"]

        del_res = self.client.post(f"/api/sources/{source_id}/delete")
        self.assertEqual(del_res.status_code, 200)

        # Detail should now 404
        get_res = self.client.get(f"/sources/{source_id}")
        self.assertEqual(get_res.status_code, 404)

    def test_seed_demo_data(self):
        seed_res = self.client.post("/api/sources/seed-demo")
        self.assertEqual(seed_res.status_code, 200)
        json_data = seed_res.get_json()
        self.assertEqual(json_data["status"], "ok")
        self.assertEqual(json_data["imported"], 4)

        # Verify sources list now has 4 items
        list_res = self.client.get("/sources")
        html = list_res.get_data(as_text=True)
        self.assertIn("4 INDEXED SOURCES", html)
        self.assertIn("Attention Mechanisms", html)
        self.assertIn("Python Asyncio Internals", html)
        self.assertIn("Agent Cognitive Architectures", html)
        self.assertIn("RAG Retrieval Benchmarks", html)

    def test_filtering_and_sorting(self):
        # Seed 4 items
        self.client.post("/api/sources/seed-demo")

        # Filter txt
        r_txt = self.client.get("/sources?type=txt")
        html_txt = r_txt.get_data(as_text=True)
        self.assertIn("Attention Mechanisms", html_txt)
        self.assertIn("Python Asyncio Internals", html_txt)
        self.assertNotIn("Agent Cognitive Architectures", html_txt)

        # Filter csv
        r_csv = self.client.get("/sources?type=csv")
        html_csv = r_csv.get_data(as_text=True)
        self.assertIn("RAG Retrieval Benchmarks", html_csv)
        self.assertNotIn("Attention Mechanisms", html_csv)

        # Search
        r_search = self.client.get("/sources?q=cognitive")
        html_search = r_search.get_data(as_text=True)
        self.assertIn("Agent Cognitive Architectures", html_search)
        self.assertNotIn("Attention Mechanisms", html_search)

        # Sort name
        r_sort = self.client.get("/sources?sort=name")
        self.assertEqual(r_sort.status_code, 200)



if __name__ == "__main__":
    unittest.main()
