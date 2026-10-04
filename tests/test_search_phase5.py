"""
Phase 5 Comprehensive Unit & Integration Tests: ORVIA Search Intelligence.
Tests all requirements:
- Porter stemmer & tokenization with positional tracking
- Query parser (single/multi-word, quoted phrases, exclusions, filters)
- Ranking engine (BM25, title boost, phrase boost, proximity calculation, match explanation)
- Positional index & co-occurrence tracking
- Zero-result intelligence & deterministic suggestions
- Term exploration & co-occurring concepts
- SQLite index persistence & restore across restarts
- Search history & research gap analytics
- UI and API history/clear/analytics routes
"""
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from orvia.app.core.config import Config
from orvia.app.core.database import DatabaseManager
from orvia.app.models.source import Source
from orvia.app.models.document import Document
from orvia.app.repositories.document_repository import DocumentRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.search.tokenizer import SearchTokenizer, PorterStemmer, Token
from orvia.app.search.query import QueryParser, ParsedQuery
from orvia.app.search.ranking import RankingEngine, MatchExplanation
from orvia.app.search.highlighter import SnippetHighlighter
from orvia.app.search.index import SearchIndex, Posting, IndexEntry
from orvia.app.search.history import SearchHistoryManager
from orvia.app.search.engine import SearchEngine
from orvia.app.search.result import SearchResult, SearchResultSet, TermExploration, ZeroResultSuggestion
from orvia.app.ui import create_app


class TestPhase5TokenizerAndQueryParser(unittest.TestCase):
    def setUp(self):
        self.tokenizer = SearchTokenizer()
        self.parser = QueryParser(self.tokenizer)

    def test_token_positions_and_stems(self):
        text = "Deep learning architectures synthesize hierarchical representations."
        tokens = self.tokenizer.tokenize(text, remove_stopwords=True, stem=True)
        self.assertTrue(len(tokens) >= 5)
        # Positions should be consecutive 0, 1, 2, ...
        for i, tok in enumerate(tokens):
            self.assertEqual(tok.position, i)
            self.assertGreater(tok.end_char, tok.start_char)
            self.assertTrue(len(tok.stem) > 0)

    def test_query_parser_complex_expression(self):
        query_str = 'transformer "scaled dot product" -recurrent format:txt'
        parsed: ParsedQuery = self.parser.parse(query_str)

        self.assertIn("transformer", parsed.raw_terms)
        self.assertEqual(len(parsed.phrases), 1)
        self.assertEqual(parsed.raw_phrases[0], "scaled dot product")
        self.assertIn("recurrent", parsed.raw_excluded)
        self.assertEqual(parsed.field_filters.get("format"), "txt")
        self.assertTrue(len(parsed.all_search_terms) >= 3)


class TestPhase5RankingEngine(unittest.TestCase):
    def setUp(self):
        self.ranking = RankingEngine(k1=1.2, b=0.75, title_boost=2.5, phrase_boost=3.0)

    def test_bm25_tf_component_with_title_boost(self):
        # Body term
        body_tf = self.ranking.calculate_bm25_tf_component(
            tf=2, doc_len=100, avg_doc_len=100.0, in_title=False
        )
        # Title term
        title_tf = self.ranking.calculate_bm25_tf_component(
            tf=2, doc_len=100, avg_doc_len=100.0, in_title=True
        )
        self.assertGreater(title_tf, body_tf)

    def test_detect_phrase_matches_and_proximity(self):
        # Positions: term0 at [5, 20], term1 at [6, 40]
        # Sequential phrase match: 5 followed by 6
        phrase = ["scaled", "dot"]
        doc_positions = {
            "scaled": [5, 20],
            "dot": [6, 40],
        }
        matches = self.ranking.detect_phrase_matches(phrase, doc_positions)
        self.assertEqual(matches, 1)

        # Proximity bonus
        bonus, min_dist = self.ranking.calculate_proximity(doc_positions)
        self.assertEqual(min_dist, 1)
        self.assertGreater(bonus, 0.0)

    def test_build_match_explanation(self):
        exp = self.ranking.build_explanation(
            score=5.4,
            term_occurrences=4,
            title_matches=1,
            phrase_matches=1,
            proximity_bonus=1.5,
            matched_terms=["scaled", "dot"],
        )
        self.assertEqual(exp.relevance_label, "High relevance")
        self.assertIn("Title match", exp.summary_text)
        self.assertIn("exact phrase", exp.summary_text.lower())


class TestPhase5IndexAndPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_index_persistence.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cooccurrence_and_stats(self):
        index = SearchIndex(db=self.db)
        index.add_document(
            id="doc-1",
            title="Attention Mechanisms",
            content="Attention mechanisms allow transformers to process tokens simultaneously.",
            file_type="txt",
        )
        index.add_document(
            id="doc-2",
            title="Transformer Scaling",
            content="Transformers scale efficiently when attention memory bottlenecks are eliminated.",
            file_type="txt",
        )

        # Check term stats for "attention"
        src_count, total_occ = index.get_term_stats("attention")
        self.assertEqual(src_count, 2)
        self.assertGreaterEqual(total_occ, 2)

        # Check related co-occurring terms for "attention"
        related = index.get_related_terms("attention", limit=5)
        self.assertTrue(len(related) > 0)

    def test_zero_result_levenshtein_suggestions(self):
        index = SearchIndex(db=self.db)
        index.add_document(
            id="doc-1",
            title="FlashAttention Optimization",
            content="FlashAttention eliminates high bandwidth memory read and write operations.",
            file_type="txt",
        )
        # Typo query: "flashattension"
        suggestions = index.get_zero_result_suggestions("flashattension", limit=3)
        self.assertIn("flashattention", suggestions)

    def test_sqlite_persistence_roundtrip(self):
        # 1. Create index, populate and persist to SQLite
        index1 = SearchIndex(db=self.db)
        index1.add_document(
            id="doc-10",
            title="Vector Similarity Search",
            content="Inverted index structures accelerate lexical document retrieval.",
            file_type="txt",
        )
        index1.save_to_sqlite()

        # 2. Check SQLite tables directly
        post_rows = self.db.fetchall("SELECT * FROM search_postings WHERE source_id = 'doc-10';")
        self.assertGreater(len(post_rows), 0)
        stats_rows = self.db.fetchall("SELECT * FROM search_source_stats WHERE source_id = 'doc-10';")
        self.assertEqual(len(stats_rows), 1)
        self.assertEqual(stats_rows[0]["title"], "Vector Similarity Search")

        # 3. Create fresh new SearchIndex and load from SQLite
        index2 = SearchIndex(db=self.db)
        dummy_source = Source(
            id="doc-10",
            title="Vector Similarity Search",
            filename="vector.txt",
            file_type="txt",
            content="Inverted index structures accelerate lexical document retrieval.",
        )
        loaded = index2.load_from_sqlite({"doc-10": dummy_source})
        self.assertTrue(loaded)
        self.assertEqual(index2.total_docs, 1)
        self.assertIn("doc-10", index2.entries)
        # Search against restored index
        hits, count = index2.search("retrieval")
        self.assertEqual(count, 1)
        self.assertEqual(hits[0].entry.id, "doc-10")


class TestPhase5SearchHistoryAndAnalytics(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_history.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()
        self.history = SearchHistoryManager(self.db)

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_search_and_queries(self):
        self.history.record_search("attention mechanism", result_count=5)
        self.history.record_search("flash attention", result_count=2)
        self.history.record_search("quantum teleportation", result_count=0)
        self.history.record_search("attention mechanism", result_count=5)

        # Recent searches
        recent = self.history.get_recent_searches(limit=5)
        self.assertEqual(len(recent), 3)  # Deduplicated: attention mechanism, quantum teleportation, flash attention
        self.assertEqual(recent[0]["query"], "attention mechanism")

        # Popular searches
        popular = self.history.get_popular_searches(limit=5)
        self.assertEqual(popular[0]["query"], "attention mechanism")
        self.assertEqual(popular[0]["search_count"], 2)

        # Zero results
        zero_res = self.history.get_zero_result_queries(limit=5)
        self.assertEqual(len(zero_res), 1)
        self.assertEqual(zero_res[0]["query"], "quantum teleportation")

        # Clear history
        cleared = self.history.clear_history()
        self.assertTrue(cleared)
        self.assertEqual(len(self.history.get_recent_searches(5)), 0)


class TestPhase5SearchEngineAndUI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_engine_ui.db"
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

    def test_search_analytics_api_flow(self):
        self._import_sample_source(
            title="Transformer Scaling Laws",
            content="Compute optimal transformer scaling relationships and empirical parameter allocations.",
            filename="scaling.txt",
        )

        # 1. Execute a query with hits
        res_hit = self.client.get("/api/search?q=transformer")
        self.assertEqual(res_hit.status_code, 200)
        hit_json = res_hit.get_json()
        self.assertEqual(hit_json["status"], "ok")
        self.assertGreater(hit_json["total_hits"], 0)
        # Term exploration should be present for single term
        self.assertIsNotNone(hit_json["term_exploration"])
        self.assertEqual(hit_json["term_exploration"]["term"], "transformer")

        # 2. Execute a query with zero hits and check suggestions
        res_zero = self.client.get("/api/search?q=transformerrr")
        self.assertEqual(res_zero.status_code, 200)
        zero_json = res_zero.get_json()
        self.assertEqual(zero_json["total_hits"], 0)
        self.assertIsNotNone(zero_json["zero_result_suggestion"])
        self.assertIn("transformer", zero_json["zero_result_suggestion"]["suggestions"])

        # 3. Check /api/search/history
        res_hist = self.client.get("/api/search/history")
        self.assertEqual(res_hist.status_code, 200)
        hist_json = res_hist.get_json()
        self.assertEqual(hist_json["status"], "ok")
        queries = [h["query"] for h in hist_json["recent"]]
        self.assertIn("transformer", queries)
        self.assertIn("transformerrr", queries)

        # 4. Check /api/search/analytics
        res_analytics = self.client.get("/api/search/analytics")
        self.assertEqual(res_analytics.status_code, 200)
        analytics_json = res_analytics.get_json()
        self.assertEqual(analytics_json["status"], "ok")
        self.assertIn("analytics", analytics_json)
        self.assertIn("zero_results", analytics_json["analytics"])
        zero_queries = [z["query"] for z in analytics_json["analytics"]["zero_results"]]
        self.assertIn("transformerrr", zero_queries)

        # 5. Clear history
        res_clear = self.client.post("/api/search/clear-history")
        self.assertEqual(res_clear.status_code, 200)
        self.assertTrue(res_clear.get_json()["cleared"])

        # History should now be empty
        res_hist_after = self.client.get("/api/search/history")
        self.assertEqual(len(res_hist_after.get_json()["recent"]), 0)


if __name__ == "__main__":
    unittest.main()
