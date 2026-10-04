"""
Graph Serialization & Formatting
Phase 7 — Interactive Knowledge Graph

Serializes KnowledgeGraph objects into clean, typed JSON dictionaries
for frontend visualization and REST API delivery.
"""
from __future__ import annotations

from typing import Any
from orvia.app.knowledge.graph.models import KnowledgeGraph, GraphNode, GraphEdge


class GraphSerializer:
    """Formats and serializes KnowledgeGraph into frontend payloads."""

    @staticmethod
    def serialize(graph: KnowledgeGraph) -> dict[str, Any]:
        """
        Convert KnowledgeGraph to a structured JSON dictionary.
        """
        graph.update_degrees()

        # Nodes payload
        nodes_data = []
        for node in graph.nodes.values():
            nodes_data.append({
                "id": node.id,
                "label": node.label,
                "node_type": node.node_type,
                "importance": node.importance,
                "occurrence_count": node.occurrence_count,
                "source_count": node.source_count,
                "degree": node.degree,
                "metadata": node.metadata,
            })

        # Edges payload
        edges_data = []
        for edge in graph.edges.values():
            edges_data.append({
                "id": edge.id,
                "source": edge.source_node_id,
                "target": edge.target_node_id,
                "relationship_type": edge.relationship_type,
                "strength": round(edge.strength, 4),
                "strength_label": edge.strength_label,
                "strength_score": edge.strength_score,
                "evidence_count": edge.evidence_count,
                "explanation": edge.explanation,
                "metadata": edge.metadata,
            })

        return {
            "nodes": nodes_data,
            "edges": edges_data,
            "metadata": {
                "node_count": graph.node_count,
                "edge_count": graph.edge_count,
                "density": graph.density,
                "is_empty": graph.is_empty,
                **graph.metadata,
            },
        }

    @staticmethod
    def serialize_relationship_explanation(
        edge: GraphEdge,
        node_a: GraphNode,
        node_b: GraphNode,
        evidence_sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Produce a detailed, explainable breakdown of a single relationship.
        """
        return {
            "relationship_id": edge.id,
            "concept_a": {
                "id": node_a.id,
                "label": node_a.label,
                "occurrences": node_a.occurrence_count,
                "sources": node_a.source_count,
            },
            "concept_b": {
                "id": node_b.id,
                "label": node_b.label,
                "occurrences": node_b.occurrence_count,
                "sources": node_b.source_count,
            },
            "strength": round(edge.strength, 4),
            "strength_label": edge.strength_label,
            "strength_score": edge.strength_score,
            "shared_source_count": len(evidence_sources),
            "explanation": edge.explanation,
            "evidence_sources": evidence_sources,
        }
