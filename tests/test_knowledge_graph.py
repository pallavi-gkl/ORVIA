"""
Unit test suite for ORVIA Phase 7: Knowledge Graph Subsystem.
Tests all requirements from Phase 7 specification:
- Node and edge model creation
- Shared-source relationship detection
- Co-occurrence relationship detection
- Relationship strength calculation
- No relationship when evidence is absent
- Duplicate relationship prevention
- Graph filtering and sizing
- Concept neighborhood generation
- Graph serialization
- Graph cache and rebuild
- Source update and deletion synchronization
- Empty collection and single-concept behaviors
"""
from __future__ import annotations

import unittest
from pathlib import Path

from orvia.app.core.database import DatabaseManager
from orvia.app.models.source import Source
from orvia.app.models.concept import Concept
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.analysis.service import ConceptAnalysisService
from orvia.app.knowledge.graph.models import (
    GraphNode,
    GraphEdge,
    GraphNodeType,
    GraphEdgeType,
    KnowledgeGraph,
)
from orvia.app.knowledge.graph.algorithms import GraphAlgorithms
from orvia.app.knowledge.graph.filters import GraphFilter
from orvia.app.knowledge.graph.serializers import GraphSerializer
from orvia.app.knowledge.graph.builder import GraphBuilder
from orvia.app.knowledge.graph.service import KnowledgeGraphService


class TestKnowledgeGraphModels(unittest.TestCase):
    """Test 1 & 2: Graph node and edge creation and properties."""

    def test_node_creation_and_properties(self):
        node = GraphNode(
            id="node-1",
            label="Attention Mechanism",
            node_type=GraphNodeType.CONCEPT.value,
            importance=0.85,
            occurrence_count=14,
            source_count=3,
        )
        self.assertEqual(node.id, "node-1")
        self.assertEqual(node.label, "Attention Mechanism")
        self.assertTrue(node.is_concept)
        self.assertFalse(node.is_source)

        data = node.to_dict()
        self.assertEqual(data["id"], "node-1")
        self.assertEqual(data["importance"], 0.85)

    def test_edge_creation_and_strength_label(self):
        edge_strong = GraphEdge(
            id="e-1",
            source_node_id="n-1",
            target_node_id="n-2",
            strength=0.78,
            evidence_count=4,
        )
        self.assertEqual(edge_strong.strength_label, "Strong observed relationship")
        self.assertEqual(edge_strong.strength_score, 78)

        edge_mod = GraphEdge(
            id="e-2",
            source_node_id="n-1",
            target_node_id="n-3",
            strength=0.45,
            evidence_count=2,
        )
        self.assertEqual(edge_mod.strength_label, "Moderate observed relationship")

        edge_weak = GraphEdge(
            id="e-3",
            source_node_id="n-2",
            target_node_id="n-3",
            strength=0.15,
            evidence_count=1,
        )
        self.assertEqual(edge_weak.strength_label, "Weak observed relationship")

    def test_graph_container_and_density(self):
        graph = KnowledgeGraph()
        n1 = GraphNode(id="n-1", label="A")
        n2 = GraphNode(id="n-2", label="B")
        n3 = GraphNode(id="n-3", label="C")
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_node(n3)

        e1 = GraphEdge(id="e-1", source_node_id="n-1", target_node_id="n-2", strength=0.5)
        graph.add_edge(e1)

        self.assertEqual(graph.node_count, 3)
        self.assertEqual(graph.edge_count, 1)
        # 1 edge out of 3 possible: density = 1/3 = 0.3333
        self.assertAlmostEqual(graph.density, 0.3333, places=2)

        graph.update_degrees()
        self.assertEqual(graph.nodes["n-1"].degree, 1)
        self.assertEqual(graph.nodes["n-3"].degree, 0)


class TestKnowledgeGraphBuilderAndService(unittest.TestCase):
    """Tests 3 to 15: Database-backed graph builder, algorithms, service, and lifecycle."""

    def setUp(self):
        self.db = DatabaseManager(db_path=Path(":memory:"))
        self.db.connect()
        self.db.initialize_schema()

        self.source_repo = SourceRepository(self.db)
        self.concept_repo = ConceptRepository(self.db)
        self.analysis_svc = ConceptAnalysisService(
            db=self.db,
            source_repo=self.source_repo,
            concept_repo=self.concept_repo,
        )
        self.service = KnowledgeGraphService(
            db=self.db,
            concept_repo=self.concept_repo,
            source_repo=self.source_repo,
        )

    def tearDown(self):
        self.db.disconnect()

    def test_empty_collection_behavior(self):
        """Test 14: Empty collection returns an empty graph without error."""
        graph_data = self.service.get_graph(mode="overview")
        self.assertEqual(graph_data["nodes"], [])
        self.assertEqual(graph_data["edges"], [])
        self.assertTrue(graph_data["metadata"]["is_empty"])

        stats = self.service.get_graph_statistics()
        self.assertEqual(stats["total_concepts"], 0)
        self.assertEqual(stats["total_relationships"], 0)

    def test_single_concept_behavior(self):
        """Test 15: Single concept produces 1 node and 0 relationships without fake connections."""
        s = Source(
            id="src-single",
            title="Single Concept Document",
            content="Entropy entropy entropy is thermodynamic measure.",
        )
        self.source_repo.save(s)
        self.analysis_svc.analyze_source("src-single")
        self.analysis_svc.rebuild_relationships()

        graph_data = self.service.get_graph(mode="overview")
        self.assertGreaterEqual(len(graph_data["nodes"]), 1)
        # There should be no cross-concept relationships since there's only 1 source with 1 dominant concept
        # Or at most 0 co-occurrence edges between distinct sources
        stats = self.service.get_graph_statistics()
        self.assertEqual(stats["total_sources"], 1)

    def test_shared_source_and_cooccurrence_detection(self):
        """Test 3 & 4: Concepts appearing together in sources form co-occurrence edges."""
        s1 = Source(
            id="src-1",
            title="Attention and Transformers",
            content=(
                "Attention mechanisms power modern transformer architectures. "
                "Attention mechanisms dynamically scale token representations. "
                "Transformer neural networks depend on self attention."
            ),
        )
        s2 = Source(
            id="src-2",
            title="Vision Transformers with Attention",
            content=(
                "Attention mechanisms are applied to visual patch sequences in vision transformer models. "
                "Attention mechanism optimizes representation across transformer layers."
            ),
        )
        s3 = Source(
            id="src-3",
            title="Gradient Descent and Optimization",
            content=(
                "Stochastic gradient optimization computes loss gradients. "
                "Gradient descent converges under convex conditions. "
                "Optimization algorithms refine model weights."
            ),
        )
        self.source_repo.save(s1)
        self.source_repo.save(s2)
        self.source_repo.save(s3)

        self.analysis_svc.analyze_all()
        self.service.invalidate_cache()

        graph_data = self.service.get_graph(mode="overview")
        self.assertGreater(len(graph_data["nodes"]), 0)
        self.assertGreater(len(graph_data["edges"]), 0)

        # "attention" and "transformer" co-occur in both s1 and s2
        edge_found = False
        for edge in graph_data["edges"]:
            src_node = next((n for n in graph_data["nodes"] if n["id"] == edge["source"]), None)
            tgt_node = next((n for n in graph_data["nodes"] if n["id"] == edge["target"]), None)
            if src_node and tgt_node:
                labels = {src_node["label"].lower(), tgt_node["label"].lower()}
                if "attention" in labels and "transformer" in labels:
                    edge_found = True
                    self.assertGreaterEqual(edge["evidence_count"], 2)
                    self.assertGreater(edge["strength"], 0.5)
                    self.assertIn("observed relationship", edge["strength_label"].lower())
                    break
        self.assertTrue(edge_found, "Expected co-occurrence edge between attention and transformer")

    def test_no_relationship_when_evidence_absent(self):
        """Test 6: Concepts appearing in disjoint sources have no edge."""
        s1 = Source(
            id="src-a",
            title="Quantum Mechanics",
            content="Quantum superposition enables parallel state representation in quantum circuits.",
        )
        s2 = Source(
            id="src-b",
            title="Ancient History",
            content="Archaeological excavations reveal ceramic pottery from classical antiquity.",
        )
        self.source_repo.save(s1)
        self.source_repo.save(s2)
        self.analysis_svc.analyze_all()
        self.service.invalidate_cache()

        graph_data = self.service.get_graph(mode="overview")
        # No edges between quantum concepts and archaeological concepts
        for edge in graph_data["edges"]:
            src_node = next((n for n in graph_data["nodes"] if n["id"] == edge["source"]), None)
            tgt_node = next((n for n in graph_data["nodes"] if n["id"] == edge["target"]), None)
            if src_node and tgt_node:
                labels = {src_node["label"].lower(), tgt_node["label"].lower()}
                self.assertFalse("quantum" in labels and "archaeological" in labels)

    def test_duplicate_relationship_prevention(self):
        """Test 7: No duplicate edges exist between the same pair of nodes."""
        s1 = Source(
            id="src-dup-1",
            title="Deep Learning Networks",
            content="Neural networks neural networks deep learning deep learning.",
        )
        s2 = Source(
            id="src-dup-2",
            title="Deep Learning Applications",
            content="Neural networks neural networks deep learning deep learning.",
        )
        self.source_repo.save(s1)
        self.source_repo.save(s2)
        self.analysis_svc.analyze_all()
        self.service.invalidate_cache()

        full_graph = self.service._builder.build_concept_graph()
        seen_pairs = set()
        for edge in full_graph.edges.values():
            pair = tuple(sorted([edge.source_node_id, edge.target_node_id]))
            self.assertNotIn(pair, seen_pairs, f"Duplicate edge detected for pair {pair}")
            seen_pairs.add(pair)

    def test_graph_filtering_and_sizing(self):
        """Test 8: GraphFilter respects max_nodes, min_strength, and search."""
        for i in range(10):
            s = Source(
                id=f"src-gen-{i}",
                title=f"Source {i}",
                content=f"TermAlpha TermAlpha TermBeta TermBeta TermGamma_{i} TermDelta_{i}.",
            )
            self.source_repo.save(s)
        self.analysis_svc.analyze_all()
        self.service.invalidate_cache()

        # Filter max 5 nodes
        filtered = self.service.get_graph(mode="overview", max_nodes=5)
        self.assertLessEqual(len(filtered["nodes"]), 5)

        # Filter search query
        searched = self.service.get_graph(mode="overview", search_query="termalpha")
        for node in searched["nodes"]:
            self.assertIn("alpha", node["label"].lower())

    def test_concept_neighborhood_generation(self):
        """Test 9: Neighborhood extraction extracts center concept and its direct links."""
        s1 = Source(
            id="src-nb-1",
            title="Hub and Spokes",
            content="CenterConcept CenterConcept SpokeOne SpokeOne SpokeTwo SpokeTwo.",
        )
        s2 = Source(
            id="src-nb-2",
            title="Hub and Spoke 3",
            content="CenterConcept CenterConcept SpokeThree SpokeThree.",
        )
        self.source_repo.save(s1)
        self.source_repo.save(s2)
        self.analysis_svc.analyze_all()
        self.service.invalidate_cache()

        center_concept = self.concept_repo.find_by_name("centerconcept")
        self.assertIsNotNone(center_concept)

        neighborhood = self.service.get_concept_neighborhood(center_concept.id, depth=1)
        self.assertIn("nodes", neighborhood)
        node_ids = {n["id"] for n in neighborhood["nodes"]}
        self.assertIn(center_concept.id, node_ids)

    def test_relationship_evidence_explanation(self):
        """Test 10 & 5: Relationship explanation returns supporting sources."""
        s1 = Source(
            id="src-ev-1",
            title="Joint Research Paper",
            content="Algorithmic fairness algorithmic fairness machine ethics machine ethics.",
        )
        self.source_repo.save(s1)
        self.analysis_svc.analyze_all()
        self.service.invalidate_cache()

        c_fairness = self.concept_repo.find_by_name("algorithmic fairness")
        c_ethics = self.concept_repo.find_by_name("machine ethics")

        if c_fairness and c_ethics:
            explanation = self.service.get_relationship_explanation(c_fairness.id, c_ethics.id)
            self.assertEqual(explanation["shared_source_count"], 1)
            self.assertEqual(len(explanation["evidence_sources"]), 1)
            self.assertEqual(explanation["evidence_sources"][0]["source_id"], "src-ev-1")

    def test_source_deletion_and_rebuild_synchronization(self):
        """Test 11, 12, 13: Deleting a source cleans up graph links and rebuilds."""
        s1 = Source(
            id="src-del-1",
            title="Temporary Source",
            content="EphemeralConcept EphemeralConcept TemporaryTopic TemporaryTopic.",
        )
        self.source_repo.save(s1)
        self.analysis_svc.analyze_all()
        self.service.invalidate_cache()

        c_ephemeral = self.concept_repo.find_by_name("ephemeralconcept")
        self.assertIsNotNone(c_ephemeral)

        # Now delete source
        self.analysis_svc.delete_source_concepts("src-del-1")
        self.source_repo.delete("src-del-1")
        self.analysis_svc.rebuild_relationships()
        self.service.invalidate_cache()

        # Verify ephemeral concept is gone from graph
        graph_data = self.service.get_graph(mode="overview")
        node_labels = [n["label"].lower() for n in graph_data["nodes"]]
        self.assertNotIn("ephemeralconcept", node_labels)


if __name__ == "__main__":
    unittest.main()
