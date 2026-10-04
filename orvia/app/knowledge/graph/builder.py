"""
Knowledge Graph Builder
Phase 7 — Interactive Knowledge Graph

Constructs KnowledgeGraph objects from existing ORVIA database entities:
- Concepts (Phase 6)
- Concept-source links (Phase 6)
- Pairwise co-occurrences (Phase 6)
- Research sources (Phase 4)
- Research topics (Phase 1)

FORMULA:
  Pairwise relationship strength:
    Strength(A, B) = Shared_Sources(A, B) / sqrt(Sources(A) * Sources(B))
  Normalized into [0.0, 1.0].
  Evidence is backed by concrete rows in `concept_source_links`.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.knowledge.graph.models import (
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    GraphNodeType,
    KnowledgeGraph,
)
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.topic_repository import TopicRepository

logger = logging.getLogger(__name__)


class GraphBuilder:
    """
    Constructs real KnowledgeGraph models from ORVIA's persistent storage.
    """

    def __init__(
        self,
        db: DatabaseManager,
        concept_repo: Optional[ConceptRepository] = None,
        source_repo: Optional[SourceRepository] = None,
        topic_repo: Optional[TopicRepository] = None,
    ) -> None:
        self._db = db
        self._concept_repo = concept_repo or ConceptRepository(db)
        self._source_repo = source_repo or SourceRepository(db)
        self._topic_repo = topic_repo or TopicRepository(db)

    # ------------------------------------------------------------------
    # Core Graph Builders
    # ------------------------------------------------------------------

    def build_concept_graph(self) -> KnowledgeGraph:
        """
        Build a graph focusing exclusively on Concepts and their pairwise co-occurrences.
        """
        graph = KnowledgeGraph(metadata={"graph_type": "concept"})

        # Load all concepts and their source aggregation counts
        concept_rows = self._db.fetchall(
            """
            SELECT
                c.id,
                c.name,
                c.frequency,
                COALESCE(agg.source_count, 0) AS source_count
            FROM concepts c
            LEFT JOIN (
                SELECT concept_id, COUNT(DISTINCT source_id) AS source_count
                FROM concept_source_links
                GROUP BY concept_id
            ) agg ON agg.concept_id = c.id
            ORDER BY c.frequency DESC;
            """
        )

        if not concept_rows:
            return graph

        total_sources = max(self._source_repo.count(), 1)
        max_freq = max((r["frequency"] for r in concept_rows), default=1)
        max_freq = max(max_freq, 1)

        # 1. Add Concept Nodes
        for r in concept_rows:
            cid = r["id"]
            name = r["name"]
            ngram_size = len(name.split())
            display_name = name.title() if ngram_size == 1 else name

            # Importance combines log-frequency and collection coverage
            freq_component = math.log1p(r["frequency"]) / math.log1p(max_freq)
            cov_component = r["source_count"] / total_sources
            importance = round(0.6 * cov_component + 0.4 * freq_component, 4)

            node = GraphNode(
                id=cid,
                label=display_name,
                node_type=GraphNodeType.CONCEPT.value,
                importance=importance,
                occurrence_count=r["frequency"],
                source_count=r["source_count"],
                metadata={
                    "canonical_name": name,
                    "ngram_size": ngram_size,
                    "coverage_pct": round(r["source_count"] / total_sources * 100, 1),
                },
            )
            graph.add_node(node)

        # 2. Add Pairwise Concept Co-occurrence Edges
        co_rows = self._db.fetchall(
            """
            SELECT
                concept_a_id,
                concept_b_id,
                shared_sources,
                strength
            FROM concept_cooccurrences
            ORDER BY strength DESC;
            """
        )

        for co in co_rows:
            a_id = co["concept_a_id"]
            b_id = co["concept_b_id"]

            # Only add edge if both nodes exist in the graph
            if a_id in graph.nodes and b_id in graph.nodes:
                shared_count = co["shared_sources"]
                strength = co["strength"]

                explanation = (
                    f"Observed together in {shared_count} research source"
                    f"{'s' if shared_count != 1 else ''} across your collection."
                )

                edge = GraphEdge(
                    id=f"{a_id}--{b_id}:co_occurrence",
                    source_node_id=a_id,
                    target_node_id=b_id,
                    relationship_type=GraphEdgeType.CONCEPT_CO_OCCURRENCE.value,
                    strength=strength,
                    evidence_count=shared_count,
                    explanation=explanation,
                    metadata={"shared_sources": shared_count},
                )
                graph.add_edge(edge)

        graph.update_degrees()
        return graph

    def build_source_graph(self) -> KnowledgeGraph:
        """
        Build a bipartite graph of Sources connected to Concepts.
        """
        graph = KnowledgeGraph(metadata={"graph_type": "source"})

        # Load sources
        sources = self._source_repo.find_all(limit=500)
        for s in sources:
            graph.add_node(
                GraphNode(
                    id=s.id,
                    label=s.title,
                    node_type=GraphNodeType.SOURCE.value,
                    importance=0.5,
                    occurrence_count=s.word_count,
                    source_count=1,
                    metadata={
                        "filename": s.filename,
                        "file_type": s.file_type,
                    },
                )
            )

        # Load concept source links
        links = self._db.fetchall(
            """
            SELECT
                csl.concept_id,
                csl.source_id,
                csl.occurrences,
                csl.in_title,
                c.name AS concept_name,
                c.frequency
            FROM concept_source_links csl
            JOIN concepts c ON c.id = csl.concept_id;
            """
        )

        for link in links:
            cid = link["concept_id"]
            sid = link["source_id"]

            if cid not in graph.nodes:
                name = link["concept_name"]
                ngram_size = len(name.split())
                graph.add_node(
                    GraphNode(
                        id=cid,
                        label=name.title() if ngram_size == 1 else name,
                        node_type=GraphNodeType.CONCEPT.value,
                        importance=0.6,
                        occurrence_count=link["frequency"],
                        metadata={"ngram_size": ngram_size},
                    )
                )

            if sid in graph.nodes and cid in graph.nodes:
                graph.add_edge(
                    GraphEdge(
                        id=f"{cid}--{sid}:concept_source",
                        source_node_id=cid,
                        target_node_id=sid,
                        relationship_type=GraphEdgeType.CONCEPT_SOURCE.value,
                        strength=1.0 if link["in_title"] else 0.7,
                        evidence_count=link["occurrences"],
                        explanation=(
                            f"Detected {link['occurrences']} times in this document"
                            f"{' (in title)' if link['in_title'] else ''}."
                        ),
                    )
                )

        graph.update_degrees()
        return graph

    def build_full_graph(self) -> KnowledgeGraph:
        """
        Build an all-inclusive multi-layer research graph:
        Topics ↔ Concepts ↔ Concepts (co-occurrence) + Sources ↔ Concepts.
        """
        # Start with concept graph
        graph = self.build_concept_graph()
        graph.metadata["graph_type"] = "full"

        # Load topics if any exist
        topics = self._topic_repo.find_all(limit=100)
        for t in topics:
            graph.add_node(
                GraphNode(
                    id=t.id,
                    label=t.name,
                    node_type=GraphNodeType.TOPIC.value,
                    importance=0.8,
                    metadata={"description": t.description},
                )
            )

        # Topic -> Concept connections
        topic_concept_rows = self._db.fetchall(
            "SELECT id, topic_id FROM concepts WHERE topic_id IS NOT NULL;"
        )
        for r in topic_concept_rows:
            cid = r["id"]
            tid = r["topic_id"]
            if tid in graph.nodes and cid in graph.nodes:
                graph.add_edge(
                    GraphEdge(
                        id=f"{tid}--{cid}:topic_concept",
                        source_node_id=tid,
                        target_node_id=cid,
                        relationship_type=GraphEdgeType.TOPIC_CONCEPT.value,
                        strength=0.9,
                        evidence_count=1,
                        explanation=f"Concept assigned to topic category.",
                    )
                )

        graph.update_degrees()
        return graph

    def build_graph_for_concept(self, concept_id: str, depth: int = 1) -> KnowledgeGraph:
        """
        Construct a targeted neighborhood graph around a specific concept.
        Includes the focused concept, its co-occurring concept neighbors, and the
        sources that connect them.
        """
        full_concept_graph = self.build_concept_graph()
        if concept_id not in full_concept_graph.nodes:
            return KnowledgeGraph(metadata={"error": "Concept not found"})

        from orvia.app.knowledge.graph.algorithms import GraphAlgorithms
        subgraph = GraphAlgorithms.extract_neighborhood(
            full_concept_graph,
            center_node_id=concept_id,
            depth=depth,
            max_nodes=35,
        )

        subgraph.metadata.update({
            "mode": "focus",
            "focused_concept_id": concept_id,
            "focused_concept_label": subgraph.nodes[concept_id].label,
        })
        return subgraph

    def build_investigation_graph(self, investigation_id: str) -> KnowledgeGraph:
        """
        Build an investigation-scoped knowledge graph (Phase 8).
        Includes:
        - concepts explicitly tracked in the investigation
        - concepts detected in attached sources
        - attached sources themselves
        - observed co-occurrences between these concepts
        - appearances linking attached sources to their detected concepts
        """
        graph = KnowledgeGraph(metadata={
            "graph_type": "investigation",
            "investigation_id": investigation_id,
        })

        # 1. Fetch tracked concepts
        tracked_cpt_rows = self._db.fetchall(
            """
            SELECT c.id, c.name, c.frequency, ic.role
            FROM investigation_concepts ic
            JOIN concepts c ON c.id = ic.concept_id
            WHERE ic.investigation_id = ?;
            """,
            (investigation_id,),
        )
        tracked_cpt_map = {r["id"]: r for r in tracked_cpt_rows}

        # 2. Fetch attached sources
        attached_src_rows = self._db.fetchall(
            """
            SELECT s.id, s.title, COALESCE(s.file_type, s.source_type) AS file_type,
                   s.word_count, inv_s.relationship_type
            FROM investigation_sources inv_s
            JOIN sources s ON s.id = inv_s.source_id
            WHERE inv_s.investigation_id = ?;
            """,
            (investigation_id,),
        )
        attached_src_map = {r["id"]: r for r in attached_src_rows}

        # 3. Fetch concepts detected in attached sources
        detected_cpt_rows = []
        if attached_src_map:
            placeholders = ",".join("?" for _ in attached_src_map)
            detected_cpt_rows = self._db.fetchall(
                f"""
                SELECT DISTINCT c.id, c.name, c.frequency, csl.source_id
                FROM concept_source_links csl
                JOIN concepts c ON c.id = csl.concept_id
                WHERE csl.source_id IN ({placeholders});
                """,
                list(attached_src_map.keys()),
            )

        # Build concept nodes set
        concept_nodes_data = {}
        for r in tracked_cpt_rows:
            concept_nodes_data[r["id"]] = {
                "name": r["name"],
                "frequency": r["frequency"],
                "is_tracked": True,
                "role": r["role"],
            }
        for r in detected_cpt_rows:
            cid = r["id"]
            if cid not in concept_nodes_data:
                concept_nodes_data[cid] = {
                    "name": r["name"],
                    "frequency": r["frequency"],
                    "is_tracked": False,
                    "role": "DETECTED",
                }

        # Add concept nodes to graph
        for cid, data in concept_nodes_data.items():
            graph.add_node(
                GraphNode(
                    id=cid,
                    label=data["name"],
                    node_type=GraphNodeType.CONCEPT.value,
                    occurrence_count=int(data["frequency"] or 0),
                    metadata={
                        "is_tracked": data["is_tracked"],
                        "investigation_role": data["role"],
                    },
                )
            )

        # Add source nodes to graph
        for sid, sdata in attached_src_map.items():
            graph.add_node(
                GraphNode(
                    id=sid,
                    label=sdata["title"],
                    node_type=GraphNodeType.SOURCE.value,
                    occurrence_count=int(sdata["word_count"] or 0),
                    metadata={
                        "relationship_type": sdata["relationship_type"],
                        "file_type": sdata["file_type"],
                    },
                )
            )

        # 4. Add edges: appearances linking attached sources to concepts
        for r in detected_cpt_rows:
            cid = r["id"]
            sid = r["source_id"]
            if cid in graph.nodes and sid in graph.nodes:
                graph.add_edge(
                    GraphEdge(
                        id=f"{sid}--{cid}:appears_in",
                        source_node_id=sid,
                        target_node_id=cid,
                        relationship_type=GraphEdgeType.CONCEPT_SOURCE.value,
                        strength=0.75,
                        explanation="Concept appears in attached source",
                    )
                )

        # 5. Add edges: concept-concept co-occurrences between nodes present in the graph
        concept_ids = list(concept_nodes_data.keys())
        if len(concept_ids) >= 2:
            placeholders = ",".join("?" for _ in concept_ids)
            cooccur_rows = self._db.fetchall(
                f"""
                SELECT concept_a_id, concept_b_id, shared_sources, strength
                FROM concept_cooccurrences
                WHERE concept_a_id IN ({placeholders})
                  AND concept_b_id IN ({placeholders});
                """,
                concept_ids + concept_ids,
            )
            for cr in cooccur_rows:
                ca = cr["concept_a_id"]
                cb = cr["concept_b_id"]
                if ca in graph.nodes and cb in graph.nodes:
                    shared = int(cr["shared_sources"] or 1)
                    graph.add_edge(
                        GraphEdge(
                            id=f"{ca}--{cb}:co_occurrence",
                            source_node_id=ca,
                            target_node_id=cb,
                            relationship_type=GraphEdgeType.CONCEPT_CO_OCCURRENCE.value,
                            strength=round(float(cr["strength"] or 0.5), 3),
                            evidence_count=shared,
                            explanation=f"Observed in {shared} shared source{'s' if shared > 1 else ''}",
                        )
                    )

        # Compute graph metrics (degree centrality, density, components)
        from orvia.app.knowledge.graph.algorithms import GraphAlgorithms
        graph.update_degrees()
        GraphAlgorithms.calculate_degree_centrality(graph)
        components = GraphAlgorithms.find_connected_components(graph)
        graph.metadata.update({
            "density": graph.density,
            "connected_components_count": len(components),
        })

        return graph

    def get_relationship_evidence(
        self,
        concept_a_id: str,
        concept_b_id: str,
    ) -> list[dict]:
        """
        Return the list of specific sources that contain BOTH concept A and concept B.
        Used when the user clicks an edge in the UI to inspect the supporting evidence.
        """
        rows = self._db.fetchall(
            """
            SELECT
                s.id AS source_id,
                s.title AS source_title,
                s.file_type,
                csl_a.occurrences AS occurrences_a,
                csl_b.occurrences AS occurrences_b
            FROM concept_source_links csl_a
            JOIN concept_source_links csl_b ON csl_a.source_id = csl_b.source_id
            JOIN sources s ON s.id = csl_a.source_id
            WHERE csl_a.concept_id = ? AND csl_b.concept_id = ?
            ORDER BY (csl_a.occurrences + csl_b.occurrences) DESC;
            """,
            (concept_a_id, concept_b_id),
        )
        return [dict(r) for r in rows]
