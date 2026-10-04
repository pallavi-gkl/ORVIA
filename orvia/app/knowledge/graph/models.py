"""
Knowledge Graph Data Models
Phase 7 — Interactive Knowledge Graph

Provides clean, extensible graph representation (nodes, edges, graph container)
supporting concepts, sources, and topics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class GraphNodeType(str, Enum):
    """Supported graph node categories."""

    CONCEPT = "concept"
    SOURCE = "source"
    TOPIC = "topic"


class GraphEdgeType(str, Enum):
    """Supported relationship edge types."""

    CONCEPT_CO_OCCURRENCE = "concept_co_occurrence"
    SHARED_SOURCE = "shared_source"
    CONCEPT_SOURCE = "concept_source"
    TOPIC_CONCEPT = "topic_concept"
    TOPIC_SOURCE = "topic_source"


@dataclass
class GraphNode:
    """A single vertex in the research knowledge graph."""

    id: str
    label: str
    node_type: str = GraphNodeType.CONCEPT.value
    importance: float = 0.5          # 0.0 to 1.0 (normalized centrality/frequency)
    occurrence_count: int = 0        # raw observations in documents
    source_count: int = 0            # number of containing research sources
    degree: int = 0                  # number of incident edges (calculated dynamically)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_concept(self) -> bool:
        return self.node_type == GraphNodeType.CONCEPT.value

    @property
    def is_source(self) -> bool:
        return self.node_type == GraphNodeType.SOURCE.value

    @property
    def is_topic(self) -> bool:
        return self.node_type == GraphNodeType.TOPIC.value

    def to_dict(self) -> dict[str, Any]:
        """Convert node to a JSON-serializable dictionary."""
        return {
            "id": self.id,
            "label": self.label,
            "node_type": self.node_type,
            "importance": round(self.importance, 4),
            "occurrence_count": self.occurrence_count,
            "source_count": self.source_count,
            "degree": self.degree,
            "metadata": self.metadata,
        }


@dataclass
class GraphEdge:
    """A directed or undirected relationship edge between two nodes."""

    id: str
    source_node_id: str
    target_node_id: str
    relationship_type: str = GraphEdgeType.CONCEPT_CO_OCCURRENCE.value
    strength: float = 0.5            # 0.0 to 1.0
    evidence_count: int = 0          # number of shared sources or text observations
    explanation: str = ""            # plain-English explanation of the connection
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def strength_label(self) -> str:
        """Human-readable strength description without misleading percentages."""
        if self.strength >= 0.65:
            return "Strong observed relationship"
        if self.strength >= 0.35:
            return "Moderate observed relationship"
        return "Weak observed relationship"

    @property
    def strength_score(self) -> int:
        """Integer score from 1 to 100 for display."""
        return max(1, min(100, round(self.strength * 100)))

    def to_dict(self) -> dict[str, Any]:
        """Convert edge to a JSON-serializable dictionary."""
        return {
            "id": self.id,
            "source": self.source_node_id,
            "target": self.target_node_id,
            "relationship_type": self.relationship_type,
            "strength": round(self.strength, 4),
            "strength_label": self.strength_label,
            "strength_score": self.strength_score,
            "evidence_count": self.evidence_count,
            "explanation": self.explanation,
            "metadata": self.metadata,
        }


@dataclass
class KnowledgeGraph:
    """Container holding a filtered or full topological research graph."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: dict[str, GraphEdge] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: GraphNode) -> None:
        """Add or update a vertex in the graph."""
        self.nodes[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        """Add or update an edge in the graph."""
        # Ensure consistent canonical ID if not given
        if not edge.id:
            s, t = sorted([edge.source_node_id, edge.target_node_id])
            edge.id = f"{s}--{t}:{edge.relationship_type}"
        self.edges[edge.id] = edge

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Retrieve node by ID."""
        return self.nodes.get(node_id)

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        """Retrieve edge by ID."""
        return self.edges.get(edge_id)

    def get_edge_between(self, node_a_id: str, node_b_id: str) -> Optional[GraphEdge]:
        """Find an edge connecting node_a and node_b in either direction."""
        for edge in self.edges.values():
            if (edge.source_node_id == node_a_id and edge.target_node_id == node_b_id) or (
                edge.source_node_id == node_b_id and edge.target_node_id == node_a_id
            ):
                return edge
        return None

    def get_connected_edges(self, node_id: str) -> list[GraphEdge]:
        """Return all edges incident to node_id."""
        return [
            e for e in self.edges.values()
            if e.source_node_id == node_id or e.target_node_id == node_id
        ]

    def get_neighbors(self, node_id: str) -> list[GraphNode]:
        """Return all adjacent nodes connected to node_id."""
        neighbor_ids = set()
        for e in self.edges.values():
            if e.source_node_id == node_id:
                neighbor_ids.add(e.target_node_id)
            elif e.target_node_id == node_id:
                neighbor_ids.add(e.source_node_id)
        return [self.nodes[nid] for nid in neighbor_ids if nid in self.nodes]

    def update_degrees(self) -> None:
        """Recalculate degree for all nodes based on current edges."""
        degrees: dict[str, int] = {nid: 0 for nid in self.nodes}
        for e in self.edges.values():
            if e.source_node_id in degrees:
                degrees[e.source_node_id] += 1
            if e.target_node_id in degrees:
                degrees[e.target_node_id] += 1
        for nid, deg in degrees.items():
            self.nodes[nid].degree = deg

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def is_empty(self) -> bool:
        return len(self.nodes) == 0

    @property
    def density(self) -> float:
        """Graph density: 2 * |E| / (|V| * (|V| - 1))."""
        n = self.node_count
        if n < 2:
            return 0.0
        max_edges = (n * (n - 1)) / 2
        return round(self.edge_count / max_edges, 4) if max_edges > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert entire graph to serializable dictionary."""
        self.update_degrees()
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges.values()],
            "metadata": {
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "density": self.density,
                **self.metadata,
            },
        }
