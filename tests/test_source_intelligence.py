"""
Unit tests for ORVIA Phase 4: Source Intelligence & Data Ingestion Pipeline.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import IngestionError
from orvia.app.ingestion.importers.csv_importer import CSVImporter
from orvia.app.ingestion.importers.json_importer import JSONImporter
from orvia.app.ingestion.importers.text_importer import TextImporter
from orvia.app.ingestion.normalizer import TextNormalizer
from orvia.app.ingestion.service import SourceImportService
from orvia.app.ingestion.statistics import SourceStatisticsCalculator
from orvia.app.repositories.source_repository import SourceRepository


class TestSourceIntelligence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_sources.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()
        self.repo = SourceRepository(self.db)
        self.service = SourceImportService(self.repo)

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── Text Normalizer ───────────────────────────────────────────────────────

    def test_normalizer_crlf_and_whitespace(self):
        raw = "Line 1\r\nLine 2\r\n\r\n\r\n\r\nLine 3   \n"
        norm = TextNormalizer.normalize(raw)
        self.assertEqual(norm, "Line 1\nLine 2\n\nLine 3")

    def test_normalizer_unicode_nfc(self):
        # 'e' + combining acute accent -> composed é
        decomposed = "e\u0301tude"
        norm = TextNormalizer.normalize(decomposed)
        self.assertEqual(norm, "étude")

    # ── Statistics Calculator ─────────────────────────────────────────────────

    def test_statistics_text(self):
        text = "First paragraph with words.\n\nSecond paragraph here."
        stats = SourceStatisticsCalculator.calculate_text_stats(text)
        self.assertEqual(stats["word_count"], 7)
        self.assertEqual(stats["paragraph_count"], 2)
        self.assertGreater(stats["character_count"], 40)

    def test_statistics_csv(self):
        csv_text = "id,name,score\n1,Alpha,92\n2,Beta,88\n"
        stats = SourceStatisticsCalculator.calculate_csv_stats(csv_text)
        self.assertEqual(stats["row_count"], 2)
        self.assertEqual(stats["column_count"], 3)
        self.assertEqual(stats["headers"], ["id", "name", "score"])

    def test_statistics_json(self):
        json_text = '{"model": "ORVIA", "parameters": 100, "active": true}'
        stats = SourceStatisticsCalculator.calculate_json_stats(json_text)
        self.assertEqual(stats["structure_type"], "object")
        self.assertEqual(stats["item_count"], 3)
        self.assertIn("model", stats["top_level_keys"])

    # ── Importers ─────────────────────────────────────────────────────────────

    def test_text_importer_success(self):
        importer = TextImporter()
        content, stats = importer.parse(b"Hello ORVIA research workspace.", "notes.txt")
        self.assertEqual(content, "Hello ORVIA research workspace.")
        self.assertEqual(stats["word_count"], 4)

    def test_text_importer_empty_raises(self):
        importer = TextImporter()
        with self.assertRaises(IngestionError):
            importer.parse(b"   \n\t  ", "empty.txt")

    def test_csv_importer_success(self):
        importer = CSVImporter()
        csv_data = b"colA,colB\nval1,val2\nval3,val4"
        content, stats = importer.parse(csv_data, "data.csv")
        self.assertEqual(stats["row_count"], 2)
        self.assertEqual(stats["column_count"], 2)

    def test_csv_importer_empty_raises(self):
        importer = CSVImporter()
        with self.assertRaises(IngestionError):
            importer.parse(b"", "empty.csv")

    def test_json_importer_success(self):
        importer = JSONImporter()
        json_data = b'{"name": "research", "tags": ["nlp", "kg"]}'
        content, stats = importer.parse(json_data, "paper.json")
        self.assertIn('"name": "research"', content)
        self.assertEqual(stats["structure_type"], "object")

    def test_json_importer_invalid_syntax_raises(self):
        importer = JSONImporter()
        with self.assertRaises(IngestionError):
            importer.parse(b'{"unclosed": "brace"', "bad.json")

    # ── SourceImportService ───────────────────────────────────────────────────

    def test_service_import_txt(self):
        res = self.service.import_source(
            file_bytes=b"Research notes on Transformer scaling laws.",
            filename="scaling.txt",
        )
        self.assertTrue(res.success)
        self.assertIsNotNone(res.source_id)
        self.assertEqual(res.file_type, "txt")
        self.assertEqual(res.word_count, 6)

        # Verify in DB
        saved = self.repo.find_by_id(res.source_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.filename, "scaling.txt")
        self.assertEqual(saved.content, "Research notes on Transformer scaling laws.")

    def test_service_import_csv(self):
        csv_bytes = b"metric,value\naccuracy,0.94\nlatency_ms,12.4\n"
        res = self.service.import_source(file_bytes=csv_bytes, filename="benchmarks.csv")
        self.assertTrue(res.success)
        self.assertEqual(res.file_type, "csv")
        self.assertEqual(res.stats["row_count"], 2)

    def test_service_import_json(self):
        json_bytes = b'{"dataset": "HotpotQA", "samples": 1000}'
        res = self.service.import_source(file_bytes=json_bytes, filename="qa.json")
        self.assertTrue(res.success)
        self.assertEqual(res.file_type, "json")

    def test_service_unsupported_extension(self):
        res = self.service.import_source(b"binary data", "document.pdf")
        self.assertFalse(res.success)
        self.assertIn("Unsupported format", res.error_message)

    def test_service_empty_file(self):
        res = self.service.import_source(b"", "empty.txt")
        self.assertFalse(res.success)
        self.assertIn("empty", res.error_message)

    def test_service_duplicate_detection(self):
        content = b"Exact identical research claim."
        # First import
        res1 = self.service.import_source(content, "claim_v1.txt")
        self.assertTrue(res1.success)

        # Second import (duplicate content)
        res2 = self.service.import_source(content, "claim_v2.txt", force_duplicate=False)
        self.assertFalse(res2.success)
        self.assertTrue(res2.is_duplicate)
        self.assertEqual(res2.duplicate_source_id, res1.source_id)
        self.assertIn("Existing source detected", res2.error_message)

        # Third import with force_duplicate=True
        res3 = self.service.import_source(content, "claim_v2.txt", force_duplicate=True)
        self.assertTrue(res3.success)
        self.assertNotEqual(res3.source_id, res1.source_id)

    # ── Repository Operations ─────────────────────────────────────────────────

    def test_repo_metadata_listing_excludes_content(self):
        self.service.import_source(b"Small source 1", "s1.txt")
        self.service.import_source(b"Small source 2", "s2.txt")

        items = self.repo.find_all_metadata()
        self.assertEqual(len(items), 2)
        # Verify content column is NOT loaded in metadata listing
        self.assertNotIn("content", items[0])
        self.assertIn("title", items[0])
        self.assertIn("file_type", items[0])

    def test_repo_filtering_and_sorting(self):
        self.service.import_source(b"A text", "a.txt")
        self.service.import_source(b"col1,col2\n1,2", "b.csv")
        self.service.import_source(b'{"key": "val"}', "c.json")

        # Filter by file_type
        csv_items = self.repo.find_all_metadata(file_type="csv")
        self.assertEqual(len(csv_items), 1)
        self.assertEqual(csv_items[0]["filename"], "b.csv")

        # Search by title/filename
        search_items = self.repo.find_all_metadata(search_query="json")
        self.assertEqual(len(search_items), 1)

    def test_repo_update_title_and_delete(self):
        res = self.service.import_source(b"Title test text", "initial.txt")
        self.assertTrue(res.success)

        # Update title
        updated = self.repo.update_title(res.source_id, "Renamed Research Title")
        self.assertTrue(updated)
        src = self.repo.find_by_id(res.source_id)
        self.assertEqual(src.title, "Renamed Research Title")

        # Delete
        deleted = self.repo.delete(res.source_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.repo.find_by_id(res.source_id))


if __name__ == "__main__":
    unittest.main()
