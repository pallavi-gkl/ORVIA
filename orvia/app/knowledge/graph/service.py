"""
Knowledge Graph Service
Phase 7 — Interactive Knowledge Graph

Orchestrator providing high-level API operations, in-memory caching,
neighborhood querying, relationship explainability, and cache invalidation.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.knowledge.graph.algorithms import GraphAlgorithms
from orvia.app.knowledge.graph.builder import GraphBuilder
from orvia.app.knowledge.graph.filters import GraphFilter
from orvia.app.knowledge.graph.models import GraphNodeType, KnowledgeGraph
from orvia.app.knowledge.graph.serializers import GraphSerializer
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.topic_repository import TopicRepository

logger = logging.getLogger(__name__)


class KnowledgeGraphService:
    """
    High-level service interface for the ORVIA Knowledge Graph.
    """

    def __init__(
        self,
        db: DatabaseManager,
        builder: Optional[GraphBuilder] = None,
        concept_repo: Optional[ConceptRepository] = None,
        source_repo: Optional[SourceRepository] = None,
        topic_repo: Optional[TopicRepository] = None,
    ) -> None:
        self._db = db
        self._concept_repo = concept_repo or ConceptRepository(db)
        self._source_repo = source_repo or SourceRepository(db)
        self._topic_repo = topic_repo or TopicRepository(db)
        self._builder = builder or GraphBuilder(
            db=db,
            concept_repo=self._concept_repo,
            source_repo=self._source_repo,
            topic_repo=self._topic_repo,
        )

        # In-memory graph cache: mode -> KnowledgeGraph
        self._cache: dict[str, KnowledgeGraph] = {}

    def invalidate_cache(self) -> None:
        """Clear all cached graph representations."""
        self._cache.clear()
        logger.debug("KnowledgeGraphService: cache invalidated")

    # ------------------------------------------------------------------
    # Query Operations
    # ------------------------------------------------------------------

    def get_graph(
        self,
        mode: str = "overview",
        node_types: Optional[list[str]] = None,
        min_strength: float = 0.0,
        max_nodes: int = 40,
        max_edges: int = 80,
        search_query: str = "",
        focus_concept_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Generate, filter, and serialize a knowledge graph according to requested mode.

        Modes:
          - overview: Top concepts and strongest co-occurrences.
          - focus: Neighborhood around focus_concept_id.
          - sources: Concepts connected directly to sources.
          - connections: Concepts with high relationship strength.
        """
        # 1. Base Graph retrieval (using cache if applicable)
        if mode == "focus" and focus_concept_id:
            base_graph = self._builder.build_graph_for_concept(focus_concept_id, depth=1)
        elif mode == "sources":
            cache_key = "base_source"
            if cache_key not in self._cache:
                self._cache[cache_key] = self._builder.build_source_graph()
            base_graph = self._cache[cache_key]
        else:
            cache_key = "base_concept"
            if cache_key not in self._cache:
                self._cache[cache_key] = self._builder.build_concept_graph()
            base_graph = self._cache[cache_key]

        # 2. Configure and apply filter
        types_set = set(node_types) if node_types else {GraphNodeType.CONCEPT.value}
        if mode == "sources":
            types_set.add(GraphNodeType.SOURCE.value)

        # In 'connections' mode, impose a higher minimum strength
        effective_min_strength = min_strength
        if mode == "connections" and min_strength == 0.0:
            effective_min_strength = 0.35

        graph_filter = GraphFilter(
            allowed_node_types=types_set,
            min_strength=effective_min_strength,
            max_nodes=max_nodes,
            max_edges=max_edges,
            search_query=search_query,
            include_isolated=(mode == "focus" or base_graph.node_count <= 2),
        )

        filtered_graph = graph_filter.apply(base_graph)
        filtered_graph.metadata["mode"] = mode
        if focus_concept_id:
            filtered_graph.metadata["focus_concept_id"] = focus_concept_id

        return GraphSerializer.serialize(filtered_graph)

    def get_concept_neighborhood(
        self,
        concept_id: str,
        depth: int = 1,
    ) -> dict[str, Any]:
        """Return serialized neighborhood graph for a specific concept."""
        subgraph = self._builder.build_graph_for_concept(concept_id, depth=depth)
        return GraphSerializer.serialize(subgraph)

    def get_relationship_explanation(
        self,
        concept_a_id: str,
        concept_b_id: str,
    ) -> dict[str, Any]:
        """
        Return the explainable evidence breakdown for the connection between two concepts.
        """
        full_graph = self._builder.build_concept_graph()
        edge = full_graph.get_edge_between(concept_a_id, concept_b_id)

        node_a = full_graph.get_node(concept_a_id)
        node_b = full_graph.get_node(concept_b_id)

        if not node_a or not node_b:
            return {"error": "One or both concepts not found in knowledge graph."}

        evidence_sources = self._builder.get_relationship_evidence(concept_a_id, concept_b_id)

        if not edge:
            # Check if there is any shared source even if edge wasn't generated
            shared_count = len(evidence_sources)
            explanation = (
                f"Observed in {shared_count} shared sources"
                if shared_count > 0
                else "No shared sources detected between these two concepts."
            )
            from orvia.app.knowledge.graph.models import GraphEdge, GraphEdgeType
            edge = GraphEdge(
                id=f"{concept_a_id}--{concept_b_id}:ad_hoc",
                source_node_id=concept_a_id,
                target_node_id=concept_b_id,
                relationship_type=GraphEdgeType.CONCEPT_CO_OCCURRENCE.value,
                strength=0.1,
                evidence_count=shared_count,
                explanation=explanation,
            )

        return GraphSerializer.serialize_relationship_explanation(
            edge=edge,
            node_a=node_a,
            node_b=node_b,
            evidence_sources=evidence_sources,
        )

    def get_graph_statistics(self) -> dict[str, Any]:
        """
        Return holistic structural statistics about the research knowledge graph.
        """
        base_graph = self._builder.build_concept_graph()
        centrality = GraphAlgorithms.calculate_degree_centrality(base_graph)
        components = GraphAlgorithms.find_connected_components(base_graph)

        # Identify top connected hub concepts
        top_connected = sorted(
            base_graph.nodes.values(),
            key=lambda n: n.degree,
            reverse=True,
        )[:5]

        total_sources = self._source_repo.count()

        # Count total observed relationships across DB
        rel_row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM concept_cooccurrences;")
        total_relationships = int(rel_row["cnt"]) if rel_row else 0

        avg_degree = (
            round(sum(n.degree for n in base_graph.nodes.values()) / max(base_graph.node_count, 1), 2)
        )

        return {
            "total_concepts": base_graph.node_count,
            "total_relationships": total_relationships,
            "total_sources": total_sources,
            "density": base_graph.density,
            "connected_components_count": len(components),
            "average_degree": avg_degree,
            "top_connected_concepts": [
                {
                    "id": n.id,
                    "label": n.label,
                    "degree": n.degree,
                    "occurrences": n.occurrence_count,
                    "sources": n.source_count,
                    "centrality": centrality.get(n.id, 0.0),
                }
                for n in top_connected
            ],
        }

    def search_graph(self, query: str) -> dict[str, Any]:
        """
        Search for nodes matching query.
        Returns matching nodes with their neighborhood context.
        """
        query_clean = query.strip().lower()
        if not query_clean:
            return {"matches": [], "query": query}

        base_graph = self._builder.build_concept_graph()
        matches = []

        for node in base_graph.nodes.values():
            if query_clean in node.label.lower() or query_clean in node.metadata.get("canonical_name", "").lower():
                matches.append({
                    "id": node.id,
                    "label": node.label,
                    "node_type": node.node_type,
                    "occurrences": node.occurrence_count,
                    "sources": node.source_count,
                    "degree": node.degree,
                })

        matches.sort(key=lambda m: (m["degree"], m["sources"], m["occurrences"]), reverse=True)
        return {
            "query": query,
            "total_matches": len(matches),
            "matches": matches,
        }

    def get_investigation_graph(self, investigation_id: str) -> dict[str, Any]:
        """
        Build and serialize an investigation-scoped knowledge graph (Phase 8).
        Uses tracked concepts, attached sources, and observed co-occurrences.
        """
        from orvia.app.knowledge.graph.serializers import GraphSerializer
        graph = self._builder.build_investigation_graph(investigation_id)
        return GraphSerializer.serialize(graph)

