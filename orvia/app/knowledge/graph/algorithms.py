"""
Graph Topological Algorithms
Phase 7 — Interactive Knowledge Graph

Provides deterministic graph calculations:
- Degree centrality
- k-hop neighborhood extraction
- Connected components detection
- Shortest path explanation between concepts
- Graph topology statistics
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from orvia.app.knowledge.graph.models import KnowledgeGraph, GraphNode, GraphEdge


class GraphAlgorithms:
    """Deterministic graph theory algorithms for knowledge graph exploration."""

    @staticmethod
    def extract_neighborhood(
        graph: KnowledgeGraph,
        center_node_id: str,
        depth: int = 1,
        max_nodes: int = 30,
    ) -> KnowledgeGraph:
        """
        Extract a sub-graph containing center_node_id and its neighbors up to depth steps.
        Prioritizes neighbors with stronger edge weights.
        """
        if center_node_id not in graph.nodes:
            return KnowledgeGraph(metadata={"error": f"Node {center_node_id} not in graph"})

        visited_nodes: set[str] = {center_node_id}
        queue: deque[tuple[str, int]] = deque([(center_node_id, 0)])

        while queue and len(visited_nodes) < max_nodes:
            curr_id, curr_depth = queue.popleft()
            if curr_depth >= depth:
                continue

            # Gather incident edges and sort by strength descending
            incident = graph.get_connected_edges(curr_id)
            incident.sort(key=lambda e: e.strength, reverse=True)

            for edge in incident:
                nbr_id = (
                    edge.target_node_id
                    if edge.source_node_id == curr_id
                    else edge.source_node_id
                )
                if nbr_id in graph.nodes and nbr_id not in visited_nodes:
                    visited_nodes.add(nbr_id)
                    queue.append((nbr_id, curr_depth + 1))
                    if len(visited_nodes) >= max_nodes:
                        break

        # Construct sub-graph
        subgraph = KnowledgeGraph(
            metadata={
                "mode": "focus",
                "center_node_id": center_node_id,
                "depth": depth,
            }
        )
        for nid in visited_nodes:
            subgraph.add_node(graph.nodes[nid])

        # Add all edges where both endpoints are in the visited set
        for edge in graph.edges.values():
            if edge.source_node_id in visited_nodes and edge.target_node_id in visited_nodes:
                subgraph.add_edge(edge)

        subgraph.update_degrees()
        return subgraph

    @staticmethod
    def calculate_degree_centrality(graph: KnowledgeGraph) -> dict[str, float]:
        """
        Calculate normalized degree centrality for each node: degree / (n - 1).
        """
        n = graph.node_count
        if n <= 1:
            return {nid: 0.0 for nid in graph.nodes}

        graph.update_degrees()
        return {
            nid: round(node.degree / (n - 1), 4)
            for nid, node in graph.nodes.items()
        }

    @staticmethod
    def find_connected_components(graph: KnowledgeGraph) -> list[list[str]]:
        """
        Identify disjoint connected components using breadth-first search.
        Returns a list of node ID lists, sorted by component size descending.
        """
        visited: set[str] = set()
        components: list[list[str]] = []

        for node_id in graph.nodes:
            if node_id in visited:
                continue

            comp: list[str] = []
            queue: deque[str] = deque([node_id])
            visited.add(node_id)

            while queue:
                curr = queue.popleft()
                comp.append(curr)

                for edge in graph.get_connected_edges(curr):
                    nbr = (
                        edge.target_node_id
                        if edge.source_node_id == curr
                        else edge.source_node_id
                    )
                    if nbr in graph.nodes and nbr not in visited:
                        visited.add(nbr)
                        queue.append(nbr)

            components.append(comp)

        components.sort(key=len, reverse=True)
        return components

    @staticmethod
    def shortest_path(
        graph: KnowledgeGraph,
        source_id: str,
        target_id: str,
    ) -> Optional[list[str]]:
        """
        Compute the shortest path of node IDs connecting source_id and target_id (unweighted BFS).
        Returns None if no path exists.
        """
        if source_id not in graph.nodes or target_id not in graph.nodes:
            return None
        if source_id == target_id:
            return [source_id]

        queue: deque[list[str]] = deque([[source_id]])
        visited: set[str] = {source_id}

        while queue:
            path = queue.popleft()
            curr = path[-1]

            if curr == target_id:
                return path

            for edge in graph.get_connected_edges(curr):
                nbr = (
                    edge.target_node_id
                    if edge.source_node_id == curr
                    else edge.source_node_id
                )
                if nbr in graph.nodes and nbr not in visited:
                    visited.add(nbr)
                    queue.append(path + [nbr])

        return None
