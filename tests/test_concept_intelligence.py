"""
Test suite for ORVIA Phase 6: Concept Intelligence
Tests extractor, normalizer, scorer, relationships, statistics, and service.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta

from pathlib import Path
from orvia.app.core.database import DatabaseManager
from orvia.app.models.source import Source
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.analysis.concepts.extractor import ConceptExtractor, RawCandidate
from orvia.app.analysis.concepts.normalizer import ConceptNormalizer, NormalizedCandidate
from orvia.app.analysis.concepts.scorer import ConceptScorer, ScoredConcept
from orvia.app.analysis.concepts.relationships import RelationshipCalculator, ConceptRelationship
from orvia.app.analysis.concepts.statistics import ConceptStatistics, ConceptTrend
from orvia.app.analysis.service import ConceptAnalysisService


class TestConceptExtractor(unittest.TestCase):
    """Test deterministic token and n-gram candidate extraction."""

    def setUp(self):
        self.extractor = ConceptExtractor(
            min_unigram_freq=2,
            min_bigram_freq=2,
            min_trigram_freq=2,
        )

    def test_unigram_extraction_with_frequency(self):
        text = "Attention mechanisms improve transformer performance. Attention is crucial for transformer architectures."
        candidates = self.extractor.extract(
            source_id="src-1",
            title="Attention Mechanisms in Transformers",
            content=text,
        )
        texts = {c.text: c for c in candidates}
        self.assertIn("attention", texts)
        self.assertIn("transformer", texts)
        self.assertEqual(texts["attention"].total_frequency, 2)
        self.assertTrue(texts["attention"].in_title)

    def test_multiword_ngram_extraction(self):
        text = (
            "We analyze gradient descent optimization. "
            "Faster convergence with gradient descent methods. "
            "In modern neural networks, gradient descent remains fundamental."
        )
        candidates = self.extractor.extract(
            source_id="src-2",
            title="Gradient Descent Optimization",
            content=text,
        )
        texts = {c.text: c for c in candidates}
        self.assertIn("gradient descent", texts)
        self.assertEqual(texts["gradient descent"].ngram_size, 2)
        self.assertEqual(texts["gradient descent"].total_frequency, 3)
        self.assertTrue(texts["gradient descent"].in_title)

    def test_stop_words_filtered(self):
        text = "This is the and or but because however therefore this that."
        candidates = self.extractor.extract(
            source_id="src-3",
            title="Stop words only",
            content=text,
        )
        self.assertEqual(len(candidates), 0)


class TestConceptNormalizer(unittest.TestCase):
    """Test candidate normalization and conservative deduplication."""

    def setUp(self):
        self.normalizer = ConceptNormalizer()

    def test_canonical_and_display_forms(self):
        raw = [
            RawCandidate("attention", 1, 3, True, "src-1"),
            RawCandidate("gradient descent", 2, 2, False, "src-1"),
        ]
        normalized = self.normalizer.normalize(raw)
        norm_map = {n.canonical: n for n in normalized}

        self.assertIn("attention", norm_map)
        self.assertEqual(norm_map["attention"].display, "Attention")

        self.assertIn("gradient descent", norm_map)
        self.assertEqual(norm_map["gradient descent"].display, "gradient descent")

    def test_deduplication_and_frequency_aggregation(self):
        raw = [
            RawCandidate("Attention", 1, 2, False, "src-1"),
            RawCandidate("attention", 1, 3, True, "src-1"),
        ]
        normalized = self.normalizer.normalize(raw)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].canonical, "attention")
        self.assertEqual(normalized[0].total_frequency, 5)
        self.assertTrue(normalized[0].in_title)

    def test_numeric_and_short_tokens_rejected(self):
        raw = [
            RawCandidate("12345", 1, 10, False, "src-1"),
            RawCandidate("ab", 1, 10, False, "src-1"),
            RawCandidate("valid", 1, 5, False, "src-1"),
        ]
        normalized = self.normalizer.normalize(raw)
        canonicals = [n.canonical for n in normalized]
        self.assertNotIn("12345", canonicals)
        self.assertNotIn("ab", canonicals)
        self.assertIn("valid", canonicals)


class TestConceptScorer(unittest.TestCase):
    """Test concept scoring calculation and explainability."""

    def setUp(self):
        self.scorer = ConceptScorer()

    def test_scoring_components(self):
        cand = NormalizedCandidate(
            canonical="attention mechanism",
            display="attention mechanism",
            ngram_size=2,
            total_frequency=6,
            in_title=True,
            source_id="src-1",
        )
        scored = self.scorer.score(
            candidate=cand,
            source_count=3,
            collection_size=10,
            max_frequency=10,
        )
        self.assertGreater(scored.score, 0)
        self.assertGreater(scored.score_frequency, 0)
        self.assertGreater(scored.score_coverage, 0)
        self.assertGreater(scored.score_title, 0)
        self.assertGreater(scored.score_phrase, 0)
        self.assertEqual(scored.coverage_pct, 0.3)
        self.assertIn("frequency", scored.score_explanation)


class TestRelationshipCalculator(unittest.TestCase):
    """Test pairwise co-occurrence calculation."""

    def setUp(self):
        self.calc = RelationshipCalculator()

    def test_pairwise_cooccurrence_and_strength(self):
        # Concept A in src1, src2, src3
        # Concept B in src2, src3, src4
        # Shared: src2, src3 (2 shared)
        source_map = {
            "c-a": {"s1", "s2", "s3"},
            "c-b": {"s2", "s3", "s4"},
            "c-c": {"s5"},
        }
        rels = self.calc.calculate(source_map, min_shared=1)
        self.assertEqual(len(rels), 1)  # only A and B share sources
        rel = rels[0]
        self.assertEqual(rel.shared_sources, 2)
        # 2 / sqrt(3 * 3) = 2/3 = 0.6667
        self.assertAlmostEqual(rel.strength, 2 / 3, places=2)
        self.assertEqual(rel.strength_label, "Frequently co-occurs")
        self.assertEqual(rel.strength_pct, 67)


class TestConceptStatistics(unittest.TestCase):
    """Test trend detection and collection summary."""

    def setUp(self):
        self.stats = ConceptStatistics()

    def test_trend_classification_emerging(self):
        # 4 sources: s1, s2 (older half), s3, s4 (newer half)
        now = datetime.now(timezone.utc)
        timestamps = {
            "s1": now - timedelta(days=10),
            "s2": now - timedelta(days=8),
            "s3": now - timedelta(days=2),
            "s4": now - timedelta(days=1),
        }
        # Concept X only appears in s3, s4 (newer half)
        source_map = {
            "c-new": {"s3", "s4"},
            "c-steady": {"s1", "s2", "s3", "s4"},
        }
        trends = self.stats.calculate_trends(source_map, timestamps)
        self.assertEqual(trends["c-new"].label, "Emerging")
        self.assertEqual(trends["c-steady"].label, "Stable")


class TestConceptAnalysisService(unittest.TestCase):
    """End-to-end service testing using an in-memory SQLite database."""

    def setUp(self):
        self.db = DatabaseManager(db_path=Path(":memory:"))
        self.db.connect()
        self.db.initialize_schema()

        self.source_repo = SourceRepository(self.db)
        self.concept_repo = ConceptRepository(self.db)

        self.service = ConceptAnalysisService(
            db=self.db,
            source_repo=self.source_repo,
            concept_repo=self.concept_repo,
        )

        # Seed 3 test sources
        s1 = Source(
            id="src-101",
            title="Transformer Attention Mechanisms",
            content=(
                "The attention mechanism is the core innovation of transformers. "
                "Attention mechanism dynamically weights input tokens. "
                "Self-attention allows parallel representation learning."
            ),
        )
        s2 = Source(
            id="src-102",
            title="Attention in Vision Models",
            content=(
                "Vision transformers apply the attention mechanism to image patches. "
                "Cross attention connects image features with text tokens. "
                "Attention mechanism scales efficiently with patch size."
            ),
        )
        s3 = Source(
            id="src-103",
            title="Gradient Optimization in Deep Learning",
            content=(
                "Stochastic gradient optimization optimizes neural weights. "
                "Adaptive gradient algorithms speed up convergence. "
                "Gradient optimization remains essential across architectures."
            ),
        )
        self.source_repo.save(s1)
        self.source_repo.save(s2)
        self.source_repo.save(s3)

    def tearDown(self):
        self.db.disconnect()

    def test_analyze_source_and_persistence(self):
        result = self.service.analyze_source("src-101")
        self.assertEqual(result["status"], "analyzed")
        self.assertGreater(result["concepts_found"], 0)

        # Verify concepts table has rows
        concepts = self.service.get_concepts_list()
        self.assertGreater(len(concepts), 0)

        # Verify analysis_status
        status = self.service.get_analysis_status("src-101")
        self.assertEqual(status["status"], "analyzed")
        self.assertEqual(status["concepts_found"], result["concepts_found"])

    def test_analyze_all_and_relationships(self):
        summary = self.service.analyze_all()
        self.assertEqual(summary["sources_analyzed"], 3)
        self.assertEqual(summary["errors"], 0)

        # Verify concept list and coverage
        concepts = self.service.get_concepts_list()
        names = {c["name"]: c for c in concepts}

        # 'attention' or 'attention mechanism' should be in multiple sources
        self.assertIn("attention", names)
        att = names["attention"]
        self.assertEqual(att["source_count"], 2)  # in src-101 and src-102
        self.assertAlmostEqual(att["coverage_pct"], 66.7, places=1)

        # Verify relationships calculated
        detail = self.service.get_concept_detail(att["id"])
        self.assertIsNotNone(detail)
        self.assertEqual(detail["source_count"], 2)
        self.assertEqual(len(detail["sources"]), 2)

    def test_delete_source_cleanup(self):
        self.service.analyze_all()
        initial_count = self.service.get_concept_count()
        self.assertGreater(initial_count, 0)

        # Delete source 103 (the only one with 'gradient optimization')
        self.service.delete_source_concepts("src-103")
        self.source_repo.delete("src-103")
        self.service.rebuild_relationships()

        # 'gradient' concept should be cleaned up or reduced
        concepts = self.service.get_concepts_list(search="gradient")
        self.assertEqual(len(concepts), 0)

    def test_enrich_search_results(self):
        self.service.analyze_all()
        raw_results = [
            {"id": "doc-1", "source_id": "src-101", "title": "Doc 1"},
            {"id": "doc-2", "source_id": "src-102", "title": "Doc 2"},
        ]
        enriched = self.service.enrich_search_results(raw_results)
        self.assertIn("concepts", enriched[0])
        self.assertGreater(len(enriched[0]["concepts"]), 0)


if __name__ == "__main__":
    unittest.main()
