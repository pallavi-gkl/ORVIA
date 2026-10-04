"""
ConceptAnalysisService — Phase 6 Concept Intelligence

Orchestrates the full concept extraction pipeline:

  1. Load source content from SourceRepository
  2. Extract raw candidates (ConceptExtractor)
  3. Normalise candidates (ConceptNormalizer)
  4. Upsert concepts into the `concepts` table
  5. Store concept-source links (concept_source_links)
  6. Score each concept across the full collection (ConceptScorer)
  7. Calculate pairwise relationships (RelationshipCalculator)
  8. Calculate trends (ConceptStatistics)
  9. Update analysis_status per source
  10. Rebuild concept_cooccurrences table

No LLMs. No embeddings. No external APIs.
All operations are deterministic, local, and reproducible.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from orvia.app.analysis.concepts.extractor import ConceptExtractor
from orvia.app.analysis.concepts.normalizer import ConceptNormalizer, NormalizedCandidate
from orvia.app.analysis.concepts.scorer import ConceptScorer, ScoredConcept
from orvia.app.analysis.concepts.relationships import RelationshipCalculator, ConceptRelationship
from orvia.app.analysis.concepts.statistics import ConceptStatistics, ConceptTrend, CollectionSummary
from orvia.app.core.database import DatabaseManager
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.models.concept import Concept

logger = logging.getLogger(__name__)


class ConceptAnalysisService:
    """
    Orchestrates the full concept detection → scoring → persistence pipeline.

    Parameters
    ----------
    db : DatabaseManager
    source_repo : SourceRepository
    concept_repo : ConceptRepository
    extractor : ConceptExtractor (optional, uses default if None)
    normalizer : ConceptNormalizer (optional)
    scorer : ConceptScorer (optional)
    rel_calc : RelationshipCalculator (optional)
    stats_calc : ConceptStatistics (optional)
    """

    def __init__(
        self,
        db: DatabaseManager,
        source_repo: SourceRepository,
        concept_repo: ConceptRepository,
        extractor: Optional[ConceptExtractor] = None,
        normalizer: Optional[ConceptNormalizer] = None,
        scorer: Optional[ConceptScorer] = None,
        rel_calc: Optional[RelationshipCalculator] = None,
        stats_calc: Optional[ConceptStatistics] = None,
    ) -> None:
        self._db = db
        self._source_repo = source_repo
        self._concept_repo = concept_repo
        self._extractor = extractor or ConceptExtractor()
        self._normalizer = normalizer or ConceptNormalizer()
        self._scorer = scorer or ConceptScorer()
        self._rel_calc = rel_calc or RelationshipCalculator()
        self._stats_calc = stats_calc or ConceptStatistics()

    # ==================================================================
    # Public API
    # ==================================================================

    def analyze_source(self, source_id: str) -> dict:
        """
        Run concept extraction for a single source.

        Returns a summary dict with `concepts_found` and `status`.
        """
        self._set_status(source_id, "analyzing")
        try:
            source = self._source_repo.find_by_id(source_id)
            if source is None:
                self._set_status(source_id, "error", error="Source not found")
                return {"status": "error", "concepts_found": 0}

            content = source.content or ""
            title = source.title or ""

            # Extract → Normalise
            raw_candidates = self._extractor.extract(
                source_id=source_id, title=title, content=content
            )
            normalized = self._normalizer.normalize(raw_candidates)

            # Upsert concepts & links
            concepts_found = self._persist_source_concepts(
                source_id=source_id,
                normalized=normalized,
            )

            self._set_status(source_id, "analyzed", concepts_found=concepts_found)
            logger.info(
                "analyze_source: source_id=%s found %d concepts", source_id, concepts_found
            )
            return {"status": "analyzed", "concepts_found": concepts_found}

        except Exception as exc:
            logger.exception("analyze_source: error for source_id=%s: %s", source_id, exc)
            self._set_status(source_id, "error", error=str(exc))
            return {"status": "error", "concepts_found": 0, "error": str(exc)}

    def analyze_all(self) -> dict:
        """
        Run concept extraction for ALL sources.

        Returns a summary dict with total concepts found.
        """
        sources = self._source_repo.find_all(limit=10_000)
        total = 0
        errors = 0
        for source in sources:
            result = self.analyze_source(source.id)
            if result["status"] == "analyzed":
                total += result["concepts_found"]
            else:
                errors += 1

        # After all sources analyzed, rebuild relationships
        self.rebuild_relationships()

        logger.info(
            "analyze_all: %d sources, %d total concepts, %d errors",
            len(sources), total, errors,
        )
        return {
            "sources_analyzed": len(sources),
            "total_concepts": total,
            "errors": errors,
        }

    def rebuild_relationships(self) -> int:
        """
        Rebuild the concept_cooccurrences table from current concept_source_links.

        Returns the number of relationships stored.
        """
        # Load concept_source_map from DB
        concept_source_map = self._load_concept_source_map()
        if not concept_source_map:
            return 0

        relationships = self._rel_calc.calculate(concept_source_map, min_shared=1)

        # Truncate & repopulate
        self._db.execute("DELETE FROM concept_cooccurrences;")
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        rows = []
        for rel in relationships:
            rows.append({
                "concept_a_id": rel.concept_a_id,
                "concept_b_id": rel.concept_b_id,
                "shared_sources": rel.shared_sources,
                "strength": rel.strength,
            })
        if rows:
            self._db.executemany(
                """
                INSERT OR REPLACE INTO concept_cooccurrences
                    (concept_a_id, concept_b_id, shared_sources, strength)
                VALUES
                    (:concept_a_id, :concept_b_id, :shared_sources, :strength);
                """,
                rows,
            )
        logger.info("rebuild_relationships: stored %d relationships", len(rows))
        return len(rows)

    def mark_needs_reanalysis(self, source_id: str) -> None:
        """Mark a source as needing reanalysis (call when source is updated)."""
        self._set_status(source_id, "needs_reanalysis")

    def get_analysis_status(self, source_id: str) -> dict:
        """Return the analysis status record for *source_id*."""
        row = self._db.fetchone(
            "SELECT * FROM analysis_status WHERE source_id = ?;", (source_id,)
        )
        if row is None:
            return {
                "source_id": source_id,
                "status": "not_analyzed",
                "concepts_found": 0,
                "analyzed_at": None,
                "error_message": None,
            }
        return dict(row)

    def get_all_analysis_statuses(self) -> list[dict]:
        """Return all analysis_status rows."""
        rows = self._db.fetchall("SELECT * FROM analysis_status;")
        return [dict(r) for r in rows]

    def delete_source_concepts(self, source_id: str) -> None:
        """
        Remove all concept-source links for *source_id*.
        Called when a source is deleted so orphaned link rows are cleaned up.
        """
        self._db.execute(
            "DELETE FROM concept_source_links WHERE source_id = ?;", (source_id,)
        )
        self._db.execute(
            "DELETE FROM analysis_status WHERE source_id = ?;", (source_id,)
        )
        # Clean up orphaned concepts (concepts with no remaining source links)
        self._db.execute(
            """
            DELETE FROM concepts
            WHERE id NOT IN (SELECT DISTINCT concept_id FROM concept_source_links);
            """
        )
        logger.info("delete_source_concepts: removed links for source_id=%s", source_id)

    # ------------------------------------------------------------------
    # Collection-level queries
    # ------------------------------------------------------------------

    def get_concepts_list(
        self,
        search: str = "",
        sort_by: str = "frequency",
        sort_dir: str = "desc",
        ngram_filter: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Return a list of concepts with collection-level statistics.

        Each dict contains:
          id, name, display, ngram_size, frequency (total occurrences),
          source_count, coverage_pct, score, in_title_count, trend
        """
        # Build query
        where_clauses = []
        params: list = []

        if search:
            where_clauses.append("c.name LIKE ?")
            params.append(f"%{search.lower()}%")

        if ngram_filter is not None:
            # Count spaces in name to approximate ngram_size
            # ngram_size = word_count = space_count + 1
            if ngram_filter == 1:
                where_clauses.append("c.name NOT LIKE '% %'")
            else:
                where_clauses.append("(LENGTH(c.name) - LENGTH(REPLACE(c.name, ' ', ''))) = ?")
                params.append(ngram_filter - 1)

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        valid_sorts = {
            "frequency": "c.frequency",
            "name": "c.name",
            "source_count": "agg.source_count",
        }
        order_col = valid_sorts.get(sort_by, "c.frequency")
        order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"

        sql = f"""
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
            {where}
            ORDER BY {order_col} {order_dir}
            LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])
        rows = self._db.fetchall(sql, params)

        total_sources = max(self._source_repo.count(), 1)
        result = []
        for row in rows:
            ngram_size = len(row["name"].split())
            display = row["name"].title() if ngram_size == 1 else row["name"]
            coverage_pct = round(row["source_count"] / total_sources * 100, 1)
            result.append({
                "id": row["id"],
                "name": row["name"],
                "display": display,
                "ngram_size": ngram_size,
                "frequency": row["frequency"],
                "source_count": row["source_count"],
                "coverage_pct": coverage_pct,
            })
        return result

    def get_concept_detail(self, concept_id: str) -> Optional[dict]:
        """
        Return full detail for a single concept.

        Includes: stats, related concepts (top 10), sources containing it,
        evidence excerpts, trend.
        """
        concept = self._concept_repo.find_by_id(concept_id)
        if concept is None:
            return None

        total_sources = max(self._source_repo.count(), 1)

        # Source links
        link_rows = self._db.fetchall(
            """
            SELECT csl.source_id, csl.occurrences, csl.in_title, csl.first_seen_at,
                   s.title AS source_title, s.file_type, s.created_at AS source_created_at
            FROM concept_source_links csl
            JOIN sources s ON s.id = csl.source_id
            WHERE csl.concept_id = ?
            ORDER BY csl.occurrences DESC;
            """,
            (concept_id,),
        )
        sources = [dict(r) for r in link_rows]
        source_count = len(sources)
        coverage_pct = round(source_count / total_sources * 100, 1)

        # Related concepts (via concept_cooccurrences)
        related_rows = self._db.fetchall(
            """
            SELECT
                CASE WHEN co.concept_a_id = ? THEN co.concept_b_id ELSE co.concept_a_id END AS other_id,
                co.shared_sources,
                co.strength
            FROM concept_cooccurrences co
            WHERE co.concept_a_id = ? OR co.concept_b_id = ?
            ORDER BY co.strength DESC
            LIMIT 10;
            """,
            (concept_id, concept_id, concept_id),
        )
        related = []
        for rr in related_rows:
            other = self._concept_repo.find_by_id(rr["other_id"])
            if other:
                ngram_size = len(other.name.split())
                related.append({
                    "id": other.id,
                    "name": other.name,
                    "display": other.name.title() if ngram_size == 1 else other.name,
                    "shared_sources": rr["shared_sources"],
                    "strength": rr["strength"],
                    "strength_pct": round(rr["strength"] * 100),
                    "strength_label": _strength_label(rr["strength"]),
                })

        # Trend calculation
        concept_source_map = {
            concept_id: {r["source_id"] for r in link_rows}
        }
        source_timestamps: dict[str, datetime] = {}
        for r in link_rows:
            try:
                source_timestamps[r["source_id"]] = datetime.fromisoformat(
                    r["source_created_at"]
                )
            except (ValueError, TypeError):
                source_timestamps[r["source_id"]] = datetime.now(tz=timezone.utc)

        trends = self._stats_calc.calculate_trends(concept_source_map, source_timestamps)
        trend = trends.get(concept_id)
        trend_label = trend.label if trend else "Stable"
        trend_desc = trend.trend_description if trend else ""

        ngram_size = len(concept.name.split())

        return {
            "id": concept.id,
            "name": concept.name,
            "display": concept.name.title() if ngram_size == 1 else concept.name,
            "ngram_size": ngram_size,
            "frequency": concept.frequency,
            "source_count": source_count,
            "coverage_pct": coverage_pct,
            "sources": sources,
            "related": related,
            "trend": trend_label,
            "trend_description": trend_desc,
            "definition": concept.definition,
            "aliases": concept.aliases,
        }

    def get_source_concepts(self, source_id: str) -> list[dict]:
        """
        Return concepts detected in a specific source.
        Used for Source Detail page integration.
        """
        rows = self._db.fetchall(
            """
            SELECT
                c.id, c.name, c.frequency,
                csl.occurrences, csl.in_title
            FROM concept_source_links csl
            JOIN concepts c ON c.id = csl.concept_id
            WHERE csl.source_id = ?
            ORDER BY csl.occurrences DESC;
            """,
            (source_id,),
        )
        result = []
        for r in rows:
            ngram_size = len(r["name"].split())
            result.append({
                "id": r["id"],
                "name": r["name"],
                "display": r["name"].title() if ngram_size == 1 else r["name"],
                "occurrences": r["occurrences"],
                "in_title": bool(r["in_title"]),
            })
        return result

    def enrich_search_results(self, results: list[dict]) -> list[dict]:
        """
        Enrich search result items with concept data.

        For each result item containing a `source_id`, add a `concepts` list
        with the top 5 detected concepts for that source.
        """
        for item in results:
            source_id = item.get("source_id")
            if source_id:
                item["concepts"] = self.get_source_concepts(source_id)[:5]
        return results

    def get_collection_summary(self) -> CollectionSummary:
        """
        Return a CollectionSummary for the Overview page.
        """
        concept_source_map = self._load_concept_source_map()
        concept_names = self._load_concept_names()

        source_timestamps: dict[str, datetime] = {}
        src_rows = self._db.fetchall(
            "SELECT id, created_at FROM sources;"
        )
        for r in src_rows:
            try:
                source_timestamps[r["id"]] = datetime.fromisoformat(r["created_at"])
            except (ValueError, TypeError):
                source_timestamps[r["id"]] = datetime.now(tz=timezone.utc)

        trends = self._stats_calc.calculate_trends(concept_source_map, source_timestamps)

        analyzed_count_row = self._db.fetchone(
            "SELECT COUNT(*) AS cnt FROM analysis_status WHERE status = 'analyzed';"
        )
        analyzed_count = int(analyzed_count_row["cnt"]) if analyzed_count_row else 0

        return self._stats_calc.collection_summary(
            concept_source_map=concept_source_map,
            concept_names=concept_names,
            total_sources=self._source_repo.count(),
            analyzed_sources=analyzed_count,
            trends=trends,
        )

    def get_concept_count(self) -> int:
        """Return total number of detected concepts."""
        return self._concept_repo.count()

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _persist_source_concepts(
        self,
        source_id: str,
        normalized: list[NormalizedCandidate],
    ) -> int:
        """
        Upsert normalised concepts and their source links.

        Steps:
          1. For each NormalizedCandidate, find or create a Concept row by name.
          2. Update the concept's frequency field (aggregate across all sources).
          3. Upsert a concept_source_links row.
        """
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        count = 0

        # Delete existing links for this source (for reanalysis)
        self._db.execute(
            "DELETE FROM concept_source_links WHERE source_id = ?;", (source_id,)
        )

        for cand in normalized:
            # Find or create concept by canonical name
            concept = self._concept_repo.find_by_name(cand.canonical)
            if concept is None:
                concept = Concept(
                    id=str(uuid.uuid4()),
                    name=cand.canonical,
                    frequency=cand.total_frequency,
                )
                self._concept_repo.save(concept)
            else:
                # Update aggregate frequency (add this source's count)
                # We update frequency by re-summing from concept_source_links
                # AFTER we insert this link — done below.
                pass

            # Upsert concept_source_links
            self._db.execute(
                """
                INSERT OR REPLACE INTO concept_source_links
                    (concept_id, source_id, occurrences, in_title, first_seen_at,
                     first_occurrence, last_occurrence)
                VALUES
                    (:concept_id, :source_id, :occurrences, :in_title, :first_seen_at,
                     :first_occurrence, :last_occurrence);
                """,
                {
                    "concept_id": concept.id,
                    "source_id": source_id,
                    "occurrences": cand.total_frequency,
                    "in_title": 1 if cand.in_title else 0,
                    "first_seen_at": now_iso,
                    "first_occurrence": getattr(cand, "first_occurrence", 0),
                    "last_occurrence": getattr(cand, "last_occurrence", 0),
                },
            )
            count += 1

        # Re-aggregate frequency for all affected concepts in this source
        self._db.execute(
            """
            UPDATE concepts
            SET frequency = (
                SELECT COALESCE(SUM(occurrences), 0)
                FROM concept_source_links
                WHERE concept_id = concepts.id
            )
            WHERE id IN (
                SELECT concept_id FROM concept_source_links WHERE source_id = ?
            );
            """,
            (source_id,),
        )

        # Clean up orphaned concepts
        self._db.execute(
            """
            DELETE FROM concepts
            WHERE id NOT IN (SELECT DISTINCT concept_id FROM concept_source_links);
            """
        )

        return count

    def _set_status(
        self,
        source_id: str,
        status: str,
        concepts_found: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Upsert analysis_status for *source_id*."""
        now_iso = datetime.now(tz=timezone.utc).isoformat() if status == "analyzed" else None
        self._db.execute(
            """
            INSERT INTO analysis_status
                (source_id, status, concepts_found, analyzed_at, error_message)
            VALUES
                (:source_id, :status, :concepts_found, :analyzed_at, :error_message)
            ON CONFLICT(source_id) DO UPDATE SET
                status = excluded.status,
                concepts_found = CASE WHEN excluded.concepts_found > 0
                                 THEN excluded.concepts_found
                                 ELSE analysis_status.concepts_found END,
                analyzed_at = CASE WHEN excluded.analyzed_at IS NOT NULL
                              THEN excluded.analyzed_at
                              ELSE analysis_status.analyzed_at END,
                error_message = excluded.error_message;
            """,
            {
                "source_id": source_id,
                "status": status,
                "concepts_found": concepts_found,
                "analyzed_at": now_iso,
                "error_message": error,
            },
        )

    def _load_concept_source_map(self) -> dict[str, set[str]]:
        """Load concept_source_map from the DB."""
        rows = self._db.fetchall(
            "SELECT concept_id, source_id FROM concept_source_links;"
        )
        result: dict[str, set[str]] = {}
        for r in rows:
            result.setdefault(r["concept_id"], set()).add(r["source_id"])
        return result

    def _load_concept_names(self) -> dict[str, str]:
        """Load concept_id → name mapping from the DB."""
        rows = self._db.fetchall("SELECT id, name FROM concepts;")
        return {r["id"]: r["name"] for r in rows}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strength_label(strength: float) -> str:
    """Return a human-readable label for a relationship strength value."""
    if strength >= 0.75:
        return "Strongly co-occurs"
    if strength >= 0.40:
        return "Frequently co-occurs"
    if strength >= 0.20:
        return "Sometimes co-occurs"
    return "Rarely co-occurs"
