"""
Deterministic comparative analysis for sources and concepts.
Phase 9 — Research Analytics & Pattern Intelligence
"""
from __future__ import annotations

from typing import Any, Optional

from orvia.app.analysis.analytics.models import ConceptComparison, SourceOverlap
from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import NotFoundError


class ComparisonEngine:
    """Provides exact mathematical comparisons and Jaccard concept overlaps between research entities."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def compare_sources(self, source_a_id: str, source_b_id: str) -> SourceOverlap:
        """
        Compare two research documents based on detected concept sets.
        Uses Jaccard index formula: shared concepts / union of concepts.
        """
        src_a = self._db.fetchone("SELECT id, title, word_count FROM sources WHERE id = ?;", (source_a_id,))
        src_b = self._db.fetchone("SELECT id, title, word_count FROM sources WHERE id = ?;", (source_b_id,))

        if not src_a:
            raise NotFoundError(entity="Source", id=source_a_id)
        if not src_b:
            raise NotFoundError(entity="Source", id=source_b_id)

        rows_a = self._db.fetchall(
            """
            SELECT c.name FROM concept_source_links csl
            JOIN concepts c ON c.id = csl.concept_id
            WHERE csl.source_id = ?
            ORDER BY c.name ASC;
            """,
            (source_a_id,),
        )
        rows_b = self._db.fetchall(
            """
            SELECT c.name FROM concept_source_links csl
            JOIN concepts c ON c.id = csl.concept_id
            WHERE csl.source_id = ?
            ORDER BY c.name ASC;
            """,
            (source_b_id,),
        )

        set_a = {r["name"] for r in rows_a}
        set_b = {r["name"] for r in rows_b}

        shared = sorted(list(set_a & set_b))
        unique_a = sorted(list(set_a - set_b))
        unique_b = sorted(list(set_b - set_a))
        union = set_a | set_b

        overlap_ratio = len(shared) / len(union) if union else 0.0
        pct = round(overlap_ratio * 100, 1)

        explanation = (
            f"Concept overlap calculation: {len(shared)} shared concepts divided by "
            f"{len(union)} total unique concepts across both sources = {pct}% Jaccard overlap."
        )

        return SourceOverlap(
            source_a_id=src_a["id"],
            source_a_title=src_a["title"],
            source_b_id=src_b["id"],
            source_b_title=src_b["title"],
            shared_concepts=shared,
            unique_concepts_a=unique_a,
            unique_concepts_b=unique_b,
            shared_count=len(shared),
            union_count=len(union),
            overlap_ratio=overlap_ratio,
            explanation=explanation,
        )

    def compare_concepts(self, concept_a_id: str, concept_b_id: str) -> ConceptComparison:
        """
        Compare two concepts across occurrence counts, containing sources, connections,
        and mutual co-occurrence evidence.
        """
        cpt_a = self._get_concept_meta(concept_a_id)
        cpt_b = self._get_concept_meta(concept_b_id)

        if not cpt_a:
            raise NotFoundError(entity="Concept", id=concept_a_id)
        if not cpt_b:
            raise NotFoundError(entity="Concept", id=concept_b_id)

        # Shared sources
        shared_rows = self._db.fetchall(
            """
            SELECT s.id, s.title, csl_a.occurrences AS occ_a, csl_b.occurrences AS occ_b
            FROM concept_source_links csl_a
            JOIN concept_source_links csl_b ON csl_a.source_id = csl_b.source_id
            JOIN sources s ON s.id = csl_a.source_id
            WHERE csl_a.concept_id = ? AND csl_b.concept_id = ?
            ORDER BY (csl_a.occurrences + csl_b.occurrences) DESC;
            """,
            (concept_a_id, concept_b_id),
        )
        shared_sources = [
            {
                "id": r["id"],
                "title": r["title"],
                "occurrences_a": int(r["occ_a"]),
                "occurrences_b": int(r["occ_b"]),
            }
            for r in shared_rows
        ]

        # Co-occurrence strength
        co_row = self._db.fetchone(
            """
            SELECT strength, shared_sources FROM concept_cooccurrences
            WHERE (concept_a_id = ? AND concept_b_id = ?)
               OR (concept_a_id = ? AND concept_b_id = ?);
            """,
            (concept_a_id, concept_b_id, concept_b_id, concept_a_id),
        )
        co_strength = float(co_row["strength"]) if co_row else None

        explanation = (
            f"'{cpt_a['name']}' ({cpt_a['total_occurrences']} occurrences across {cpt_a['source_count']} sources) "
            f"and '{cpt_b['name']}' ({cpt_b['total_occurrences']} occurrences across {cpt_b['source_count']} sources) "
            f"co-occur in {len(shared_sources)} shared research sources."
        )

        return ConceptComparison(
            concept_a=cpt_a,
            concept_b=cpt_b,
            shared_sources=shared_sources,
            shared_source_count=len(shared_sources),
            cooccurrence_strength=co_strength,
            explanation=explanation,
        )

    def _get_concept_meta(self, concept_id: str) -> Optional[dict[str, Any]]:
        row = self._db.fetchone(
            """
            SELECT c.id, c.name, c.frequency AS total_occurrences,
                   COUNT(DISTINCT csl.source_id) AS source_count,
                   MIN(csl.first_seen_at) AS earliest_observation,
                   MAX(csl.first_seen_at) AS latest_observation
            FROM concepts c
            LEFT JOIN concept_source_links csl ON c.id = csl.concept_id
            WHERE c.id = ?
            GROUP BY c.id;
            """,
            (concept_id,),
        )
        if not row:
            return None

        # Connection count
        conn_row = self._db.fetchone(
            """
            SELECT COUNT(DISTINCT other_id) AS cnt FROM (
                SELECT concept_b_id AS other_id FROM concept_cooccurrences WHERE concept_a_id = ?
                UNION
                SELECT concept_a_id AS other_id FROM concept_cooccurrences WHERE concept_b_id = ?
                UNION
                SELECT target_concept_id AS other_id FROM relationships WHERE source_concept_id = ?
                UNION
                SELECT source_concept_id AS other_id FROM relationships WHERE target_concept_id = ?
            );
            """,
            (concept_id, concept_id, concept_id, concept_id),
        )
        conn_count = int(conn_row["cnt"]) if conn_row else 0

        return {
            "id": row["id"],
            "name": row["name"],
            "total_occurrences": int(row["total_occurrences"] or 0),
            "source_count": int(row["source_count"] or 0),
            "connection_count": conn_count,
            "earliest_observation": row["earliest_observation"],
            "latest_observation": row["latest_observation"],
        }
