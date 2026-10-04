"""
Unit tests for ORVIA Phase 5 Search Intelligence:
Tokenizer, PorterStemmer, SnippetHighlighter, InvertedIndex, DocumentProcessor, and SearchService.
"""
import unittest
from pathlib import Path
import tempfile
import shutil

from orvia.app.core.config import Config
from orvia.app.core.database import DatabaseManager
from orvia.app.models.source import Source
from orvia.app.models.document import Document
from orvia.app.repositories.document_repository import DocumentRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.search.tokenizer import SearchTokenizer, PorterStemmer
from orvia.app.search.highlighter import SnippetHighlighter
from orvia.app.search.inverted_index import InvertedIndex
from orvia.app.search.document_processor import DocumentProcessor
from orvia.app.search.service import SearchService


class TestTokenizerAndStemmer(unittest.TestCase):
    def setUp(self):
        self.tokenizer = SearchTokenizer()
        self.stemmer = PorterStemmer()

    def test_porter_stemmer_rules(self):
        self.assertEqual(self.stemmer.stem("transformers"), "transform")
        self.assertEqual(self.stemmer.stem("connecting"), "connect")
        self.assertEqual(self.stemmer.stem("retrieval"), "retriev")
        self.assertEqual(self.stemmer.stem("processes"), "process")
        self.assertEqual(self.stemmer.stem("scaling"), "scale")
        self.assertEqual(self.stemmer.stem("optimization"), "optim")

    def test_tokenization_with_positions(self):
        text = "FlashAttention eliminates HBM memory bottlenecks."
        tokens = self.tokenizer.tokenize(text, remove_stopwords=True, stem=True)
        self.assertTrue(len(tokens) >= 4)
        # Check positions are strictly sequential
        for idx, tok in enumerate(tokens):
            self.assertEqual(tok.position, idx)
            self.assertGreater(tok.end_char, tok.start_char)

    def test_stop_words_filtering(self):
        text = "This is a document about the attention mechanism and its scaling."
        terms = self.tokenizer.tokenize_terms(text, stem=False)
        self.assertNotIn("this", terms)
        self.assertNotIn("is", terms)
        self.assertNotIn("a", terms)
        self.assertNotIn("the", terms)
        self.assertNotIn("and", terms)
        self.assertIn("document", terms)
        self.assertIn("attention", terms)
        self.assertIn("mechanism", terms)


class TestSnippetHighlighter(unittest.TestCase):
    def setUp(self):
        self.highlighter = SnippetHighlighter(default_window_chars=120)

    def test_highlight_terms(self):
        content = "The scaled dot-product attention formulation serves as the mathematical foundation."
        snippet = self.highlighter.generate_snippet(content, ["attention", "mathematical"])
        self.assertIn('<mark class="search-highlight">attention</mark>', snippet)
        self.assertIn('<mark class="search-highlight">mathematical</mark>', snippet)

    def test_html_escaping(self):
        content = "Dangerous <b>payload</b> & <script>alert(1)</script> within text."
        snippet = self.highlighter.generate_snippet(content, ["payload"])
        self.assertNotIn("<script>", snippet)
        self.assertIn("&lt;script&gt;", snippet)
        self.assertIn('<mark class="search-highlight">payload</mark>', snippet)

    def test_empty_content(self):
        snippet = self.highlighter.generate_snippet("", ["test"])
        self.assertEqual(snippet, "")


class TestInvertedIndex(unittest.TestCase):
    def setUp(self):
        self.index = InvertedIndex()
        self.index.add_document(
            id="doc-1",
            title="Transformer Scaling and Attention",
            content="Scaled dot-product attention has quadratic memory complexity. FlashAttention fixes it.",
            file_type="txt",
            tags=["nlp", "deep_learning"],
            created_at="2026-09-01T10:00:00",
        )
        self.index.add_document(
            id="doc-2",
            title="Python Asyncio Internals",
            content="Python event loops schedule tasks and coroutines using cooperative multitasking.",
            file_type="txt",
            tags=["python", "async"],
            created_at="2026-09-02T10:00:00",
        )
        self.index.add_document(
            id="doc-3",
            title="RAG Latency Benchmarks",
            content="Dense vector retrieval benchmarks versus BM25 lexical ranking under heavy concurrency.",
            file_type="csv",
            tags=["rag", "benchmarks"],
            created_at="2026-09-03T10:00:00",
        )

    def test_bm25_ranking_relevance(self):
        hits, count = self.index.search("attention")
        self.assertEqual(count, 1)
        self.assertEqual(hits[0].entry.id, "doc-1")
        self.assertGreater(hits[0].score, 0.0)

    def test_title_boost(self):
        # Add doc with term only in body vs doc with term in title
        self.index.add_document(
            id="doc-body",
            title="General Overview",
            content="Specialized compilers optimize execution.",
            file_type="txt",
        )
        self.index.add_document(
            id="doc-title",
            title="Compilers and Bytecode",
            content="Generic notes on software architectures.",
            file_type="txt",
        )
        hits, _ = self.index.search("compilers")
        self.assertEqual(hits[0].entry.id, "doc-title")

    def test_phrase_search(self):
        hits, count = self.index.search('"dot-product attention"')
        self.assertEqual(count, 1)
        self.assertEqual(hits[0].entry.id, "doc-1")
        self.assertTrue(hits[0].phrase_matched)

        # Non-matching phrase
        hits_miss, count_miss = self.index.search('"attention memory complexity"')
        # While individual words exist, they are not consecutive
        self.assertEqual(count_miss, 0)

    def test_exclusion_operator(self):
        # Both doc-1 and doc-3 are ML related, search "ranking" vs "ranking -lexical"
        hits, count = self.index.search("retrieval -lexical")
        self.assertEqual(count, 0)  # doc-3 contains lexical so excluded

        hits2, count2 = self.index.search("retrieval")
        self.assertEqual(count2, 1)

    def test_format_filter(self):
        hits, count = self.index.search("benchmarks", filter_type="csv")
        self.assertEqual(count, 1)
        self.assertEqual(hits[0].entry.id, "doc-3")

        hits_txt, count_txt = self.index.search("benchmarks", filter_type="txt")
        self.assertEqual(count_txt, 0)


class TestDocumentProcessorAndSearchService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_search.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()

        self.source_repo = SourceRepository(self.db)
        self.doc_repo = DocumentRepository(self.db)
        self.search_service = SearchService(self.source_repo, self.doc_repo)

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_document_processor_sections(self):
        src = Source(
            title="Deep Learning Manual",
            filename="manual.txt",
            file_type="txt",
            content="""# Introduction
Deep learning systems leverage neural layers to synthesize representations.

## Backpropagation
Gradients flow backwards through computational graph nodes according to the chain rule.

## Optimization
Adam and SGD algorithms update parameter weights iteratively.
""",
        )
        self.source_repo.save(src)
        processor = DocumentProcessor(self.doc_repo)
        docs = processor.process_source(src)

        # Primary doc + 2 sections with >= 15 words
        self.assertGreaterEqual(len(docs), 2)
        saved_docs = self.doc_repo.find_by_source(src.id)
        self.assertEqual(len(saved_docs), len(docs))

    def test_search_service_end_to_end(self):
        src1 = Source(
            title="Transformer Attention Mechanics",
            filename="attention.txt",
            file_type="txt",
            content="FlashAttention tiles inputs in on-chip SRAM to eliminate the HBM bandwidth bottleneck.",
        )
        src2 = Source(
            title="Python Async Event Loop",
            filename="async.txt",
            file_type="txt",
            content="Asyncio schedules coroutines cooperatively using OS epoll or kqueue multiplexers.",
        )
        self.source_repo.save(src1)
        self.source_repo.save(src2)

        # Index all
        indexed_count = self.search_service.ensure_indexed()
        self.assertGreaterEqual(indexed_count, 2)

        # Execute search
        results = self.search_service.search("FlashAttention")
        self.assertGreater(results.total_hits, 0)
        self.assertGreaterEqual(results.duration_ms, 0.0)
        self.assertIn("FlashAttention", results.results[0].title + results.results[0].snippet)
        self.assertIn("<mark", results.results[0].snippet)


if __name__ == "__main__":
    unittest.main()
