"""
Graph Filtering & Sizing Controls
Phase 7 — Interactive Knowledge Graph

Provides deterministic graph filtering so the researcher is never overwhelmed
by huge unreadable hairballs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set

from orvia.app.knowledge.graph.models import KnowledgeGraph, GraphNodeType


@dataclass
class GraphFilter:
    """Configurable constraints applied to a KnowledgeGraph."""

    allowed_node_types: Set[str] = field(
        default_factory=lambda: {GraphNodeType.CONCEPT.value}
    )
    min_strength: float = 0.0
    min_occurrence_count: int = 0
    min_source_count: int = 0
    max_nodes: int = 40
    max_edges: int = 80
    search_query: str = ""
    include_isolated: bool = False

    def apply(self, graph: KnowledgeGraph) -> KnowledgeGraph:
        """
        Apply filter parameters to produce a bounded, relevant sub-graph.
        """
        # Step 1: Filter nodes by type, counts, and search query
        candidate_nodes = []
        query_lower = self.search_query.strip().lower()

        for node in graph.nodes.values():
            if node.node_type not in self.allowed_node_types:
                continue
            if node.occurrence_count < self.min_occurrence_count:
                continue
            if node.source_count < self.min_source_count:
                continue
            if query_lower and query_lower not in node.label.lower():
                continue
            candidate_nodes.append(node)

        # Step 2: Rank nodes by importance / occurrence and take top max_nodes
        candidate_nodes.sort(
            key=lambda n: (n.importance, n.source_count, n.occurrence_count),
            reverse=True,
        )
        selected_nodes = {n.id: n for n in candidate_nodes[:self.max_nodes]}

        # Step 3: Filter edges that connect two selected nodes and meet min_strength
        candidate_edges = []
        for edge in graph.edges.values():
            if (
                edge.source_node_id in selected_nodes
                and edge.target_node_id in selected_nodes
            ):
                if edge.strength >= self.min_strength:
                    candidate_edges.append(edge)

        # Step 4: Rank edges by strength descending and take top max_edges
        candidate_edges.sort(key=lambda e: e.strength, reverse=True)
        selected_edges = {e.id: e for e in candidate_edges[:self.max_edges]}

        # Step 5: If exclude_isolated, drop nodes that have no incident edges
        # (unless there are fewer than 2 total nodes or user explicitly wants isolated)
        if not self.include_isolated and len(selected_nodes) > 1 and len(selected_edges) > 0:
            connected_node_ids = set()
            for edge in selected_edges.values():
                connected_node_ids.add(edge.source_node_id)
                connected_node_ids.add(edge.target_node_id)

            filtered_nodes = {
                nid: node for nid, node in selected_nodes.items()
                if nid in connected_node_ids
            }
        else:
            filtered_nodes = selected_nodes

        result = KnowledgeGraph(
            nodes=filtered_nodes,
            edges=selected_edges,
            metadata={
                "filter": {
                    "node_types": list(self.allowed_node_types),
                    "min_strength": self.min_strength,
                    "max_nodes": self.max_nodes,
                    "max_edges": self.max_edges,
                    "search_query": self.search_query,
                },
                "total_candidate_nodes": len(candidate_nodes),
                "total_candidate_edges": len(candidate_edges),
            },
        )
        result.update_degrees()
        return result
