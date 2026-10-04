"""
Collection-level statistical calculations and densities.
Phase 9 — Research Analytics & Pattern Intelligence
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from orvia.app.analysis.analytics.models import CollectionSnapshot
from orvia.app.core.database import DatabaseManager


class CollectionStatisticsCalculator:
    """Computes exact collection statistics and mathematical densities from the SQLite store."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get_snapshot(self, time_range: str = "all") -> CollectionSnapshot:
        """
        Compute an analytical snapshot of the current collection.
        Optionally filters counts by time range ('all', '7d', '30d', '90d').
        """
        cutoff_iso = self._get_cutoff_iso(time_range)
        where_time = "WHERE created_at >= ?" if cutoff_iso else ""
        params = (cutoff_iso,) if cutoff_iso else ()

        # 1. Total counts
        sources_cnt = self._scalar(f"SELECT COUNT(*) FROM sources {where_time};", params)
        concepts_cnt = self._scalar(f"SELECT COUNT(*) FROM concepts {where_time};", params)
        topics_cnt = self._scalar("SELECT COUNT(*) FROM topics;")
        invs_cnt = self._scalar(f"SELECT COUNT(*) FROM investigations {where_time};", params)
        evidence_cnt = self._scalar(f"SELECT COUNT(*) FROM investigation_evidence {where_time};", params)

        open_q_query = "SELECT COUNT(*) FROM investigation_questions WHERE status != 'RESOLVED'"
        if cutoff_iso:
            open_q_query += " AND created_at >= ?"
        open_q_cnt = self._scalar(f"{open_q_query};", params)

        findings_cnt = self._scalar(f"SELECT COUNT(*) FROM investigation_findings {where_time};", params)
        rel_cnt = self._scalar("SELECT COUNT(*) FROM relationships;")

        # 2. Relationship / Link counts for density ratios
        csl_cnt = self._scalar("SELECT COUNT(*) FROM concept_source_links;")
        inv_concepts_cnt = self._scalar("SELECT COUNT(*) FROM investigation_concepts;")
        inv_sources_cnt = self._scalar("SELECT COUNT(*) FROM investigation_sources;")

        # 3. Density ratios (with zero division guards)
        avg_concepts_src = (csl_cnt / sources_cnt) if sources_cnt > 0 else 0.0
        avg_concepts_inv = (inv_concepts_cnt / invs_cnt) if invs_cnt > 0 else 0.0
        avg_evidence_inv = (evidence_cnt / invs_cnt) if invs_cnt > 0 else 0.0
        avg_sources_inv = (inv_sources_cnt / invs_cnt) if invs_cnt > 0 else 0.0
        avg_rel_cpt = (rel_cnt * 2 / concepts_cnt) if concepts_cnt > 0 else 0.0

        return CollectionSnapshot(
            total_sources=sources_cnt,
            total_concepts=concepts_cnt,
            total_topics=topics_cnt,
            total_investigations=invs_cnt,
            total_evidence=evidence_cnt,
            total_open_questions=open_q_cnt,
            total_findings=findings_cnt,
            total_relationships=rel_cnt,
            avg_concepts_per_source=avg_concepts_src,
            avg_concepts_per_investigation=avg_concepts_inv,
            avg_evidence_per_investigation=avg_evidence_inv,
            avg_sources_per_investigation=avg_sources_inv,
            avg_relationships_per_concept=avg_rel_cpt,
        )

    def _scalar(self, sql: str, params: tuple = ()) -> int:
        row = self._db.fetchone(sql, params)
        if row:
            val = next(iter(row.values()), 0)
            return int(val or 0)
        return 0

    @staticmethod
    def _get_cutoff_iso(time_range: str) -> Optional[str]:
        if not time_range or time_range == "all":
            return None
        now = datetime.now(timezone.utc)
        if time_range == "7d":
            return (now - timedelta(days=7)).isoformat()
        if time_range == "30d":
            return (now - timedelta(days=30)).isoformat()
        if time_range == "90d":
            return (now - timedelta(days=90)).isoformat()
        return None
