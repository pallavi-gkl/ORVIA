"""
Coverage analysis, isolated vs connected vertices, and investigation status classifications.
Phase 9 — Research Analytics & Pattern Intelligence
"""
from __future__ import annotations

from typing import Any

from orvia.app.analysis.analytics.models import CoverageAnalysis
from orvia.app.core.database import DatabaseManager


class CoverageAnalyzer:
    """Analyzes distribution breadth, low-coverage gaps, and topological connectivity."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get_coverage_analysis(self) -> CoverageAnalysis:
        """Compute collection-wide coverage distribution and investigation states."""
        # 1. Total sources & concepts
        src_row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM sources;")
        total_sources = int(src_row["cnt"]) if src_row else 0

        cpt_row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM concepts;")
        total_concepts = int(cpt_row["cnt"]) if cpt_row else 0

        # 2. Source distribution per concept (from concept_source_links)
        dist_rows = self._db.fetchall(
            """
            SELECT c.id, c.name, c.frequency, COUNT(csl.source_id) AS source_count
            FROM concepts c
            LEFT JOIN concept_source_links csl ON c.id = csl.concept_id
            GROUP BY c.id
            ORDER BY source_count ASC, c.frequency DESC;
            """
        )

        single_source_cpts = []
        multi_source_cpts = []

        for r in dist_rows:
            sc = int(r["source_count"] or 0)
            item = {
                "id": r["id"],
                "name": r["name"],
                "frequency": int(r["frequency"] or 0),
                "source_count": sc,
                "coverage_pct": round((sc / total_sources * 100), 1) if total_sources > 0 else 0.0,
            }
            if sc <= 1:
                single_source_cpts.append(item)
            else:
                multi_source_cpts.append(item)

        single_cnt = len(single_source_cpts)
        multi_cnt = len(multi_source_cpts)
        single_pct = (single_cnt / total_concepts * 100) if total_concepts > 0 else 0.0
        multi_pct = (multi_cnt / total_concepts * 100) if total_concepts > 0 else 0.0

        # 3. Connectivity from concept_cooccurrences and relationships
        conn_rows = self._db.fetchall(
            """
            SELECT c.id, c.name, c.frequency,
                   COUNT(DISTINCT co.other_id) AS connection_count
            FROM concepts c
            LEFT JOIN (
                SELECT concept_a_id AS cid, concept_b_id AS other_id FROM concept_cooccurrences
                UNION
                SELECT concept_b_id AS cid, concept_a_id AS other_id FROM concept_cooccurrences
                UNION
                SELECT source_concept_id AS cid, target_concept_id AS other_id FROM relationships
                UNION
                SELECT target_concept_id AS cid, source_concept_id AS other_id FROM relationships
            ) co ON c.id = co.cid
            GROUP BY c.id
            ORDER BY connection_count DESC, c.frequency DESC;
            """
        )

        isolated_cpts = []
        connected_cpts = []
        for r in conn_rows:
            conns = int(r["connection_count"] or 0)
            entry = {
                "id": r["id"],
                "name": r["name"],
                "frequency": int(r["frequency"] or 0),
                "connection_count": conns,
            }
            if conns <= 1:
                isolated_cpts.append(entry)
            else:
                connected_cpts.append(entry)

        # 4. Investigation coverage breakdown
        inv_rows = self._db.fetchall(
            """
            SELECT
                i.id, i.title, i.status,
                (SELECT COUNT(*) FROM investigation_sources WHERE investigation_id = i.id) AS source_count,
                (SELECT COUNT(*) FROM investigation_concepts WHERE investigation_id = i.id) AS concept_count,
                (SELECT COUNT(*) FROM investigation_evidence WHERE investigation_id = i.id) AS evidence_count,
                (SELECT COUNT(*) FROM investigation_questions WHERE investigation_id = i.id AND status != 'RESOLVED') AS open_questions_count,
                (SELECT COUNT(*) FROM investigation_findings WHERE investigation_id = i.id) AS findings_count
            FROM investigations i
            ORDER BY i.updated_at DESC;
            """
        )

        inv_coverage = []
        for ir in inv_rows:
            sc = int(ir["source_count"] or 0)
            cc = int(ir["concept_count"] or 0)
            ec = int(ir["evidence_count"] or 0)
            oq = int(ir["open_questions_count"] or 0)
            fc = int(ir["findings_count"] or 0)

            # Deterministic coverage label based on explicit rules:
            if sc == 0 or ec == 0:
                label = "Early-stage"
                desc = "Few sources attached or no empirical evidence recorded yet."
            elif oq > 0 and ec >= 1:
                label = "Open questions remain"
                desc = f"{oq} research question{'s remain' if oq > 1 else ' remains'} unaddressed."
            elif ec >= 3 and fc >= 1 and oq == 0:
                label = "Well-supported"
                desc = f"{ec} evidence items supporting {fc} finding{'s' if fc > 1 else ''} with 0 open questions."
            else:
                label = "Limited evidence"
                desc = f"{ec} recorded evidence item{'s' if ec != 1 else ''} across {sc} source{'s' if sc != 1 else ''}."

            inv_coverage.append({
                "id": ir["id"],
                "title": ir["title"],
                "status": ir["status"],
                "source_count": sc,
                "concept_count": cc,
                "evidence_count": ec,
                "open_questions_count": oq,
                "findings_count": fc,
                "coverage_label": label,
                "coverage_description": desc,
            })

        return CoverageAnalysis(
            total_sources=total_sources,
            total_concepts=total_concepts,
            single_source_concepts_count=single_cnt,
            single_source_concepts_pct=single_pct,
            multi_source_concepts_count=multi_cnt,
            multi_source_concepts_pct=multi_pct,
            low_coverage_concepts=single_source_cpts[:20],
            isolated_concepts=isolated_cpts[:20],
            highly_connected_concepts=connected_cpts[:20],
            investigation_coverage=inv_coverage,
        )
