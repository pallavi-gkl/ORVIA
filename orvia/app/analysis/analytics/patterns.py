"""
Deterministic pattern detection engine for research collections.
Phase 9 — Research Analytics & Pattern Intelligence
"""
from __future__ import annotations

from typing import Any

from orvia.app.analysis.analytics.models import PatternItem, PatternType, TrendStatus
from orvia.app.core.database import DatabaseManager


class PatternDetector:
    """Detects observable, explainable structural patterns across the research store."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def detect_patterns(self, limit: int = 15) -> list[PatternItem]:
        """
        Scan collection data and return a ranked list of verified structural patterns.
        Every pattern includes exact calculations and contributing entity IDs.
        """
        patterns: list[PatternItem] = []

        # 1. Source counts & Concept counts
        src_row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM sources;")
        total_sources = int(src_row["cnt"]) if src_row else 0

        cpt_row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM concepts;")
        total_concepts = int(cpt_row["cnt"]) if cpt_row else 0

        # Pattern: High Source Coverage
        if total_sources >= 2:
            high_cov_rows = self._db.fetchall(
                """
                SELECT c.id, c.name, COUNT(DISTINCT csl.source_id) AS src_cnt, c.frequency
                FROM concepts c
                JOIN concept_source_links csl ON c.id = csl.concept_id
                GROUP BY c.id
                HAVING src_cnt >= 2 AND src_cnt >= (? / 2.0)
                ORDER BY src_cnt DESC, c.frequency DESC
                LIMIT 3;
                """,
                (total_sources,),
            )
            for r in high_cov_rows:
                sc = int(r["src_cnt"])
                pct = round(sc / total_sources * 100, 1)
                patterns.append(
                    PatternItem(
                        pattern_type=PatternType.HIGH_SOURCE_COVERAGE.value,
                        title=f"Broad collection presence: '{r['name']}'",
                        description=f"Concept appears across {sc} of {total_sources} research sources ({pct}% coverage).",
                        evidence_summary=f"{sc} sources containing {int(r['frequency'] or 0)} total occurrences.",
                        calculation_formula=f"Source coverage = {sc} / {total_sources} = {pct}%",
                        concept_ids=[r["id"]],
                    )
                )

        # Pattern: Low Source Coverage / Single Source Concentrations
        if total_sources >= 3 and total_concepts >= 5:
            single_src_rows = self._db.fetchall(
                """
                SELECT c.id, c.name, c.frequency
                FROM concepts c
                JOIN concept_source_links csl ON c.id = csl.concept_id
                GROUP BY c.id
                HAVING COUNT(DISTINCT csl.source_id) = 1
                ORDER BY c.frequency DESC;
                """
            )
            if len(single_src_rows) >= 3:
                sample_names = ", ".join(f"'{r['name']}'" for r in single_src_rows[:3])
                pct = round(len(single_src_rows) / total_concepts * 100, 1)
                patterns.append(
                    PatternItem(
                        pattern_type=PatternType.LOW_SOURCE_COVERAGE.value,
                        title="Concepts localized to single sources",
                        description=f"{len(single_src_rows)} concepts ({pct}% of collection) appear in only one document (e.g. {sample_names}).",
                        evidence_summary=f"{len(single_src_rows)} concepts with source_count == 1.",
                        calculation_formula=f"Localized count / total concepts = {len(single_src_rows)} / {total_concepts} = {pct}%",
                        concept_ids=[r["id"] for r in single_src_rows[:5]],
                    )
                )

        # Pattern: High Topological Connectivity
        high_conn_rows = self._db.fetchall(
            """
            SELECT c.id, c.name, COUNT(DISTINCT co.other_id) AS conn_cnt, c.frequency
            FROM concepts c
            JOIN (
                SELECT concept_a_id AS cid, concept_b_id AS other_id FROM concept_cooccurrences
                UNION
                SELECT concept_b_id AS cid, concept_a_id AS other_id FROM concept_cooccurrences
            ) co ON c.id = co.cid
            GROUP BY c.id
            HAVING conn_cnt >= 4
            ORDER BY conn_cnt DESC
            LIMIT 2;
            """
        )
        for r in high_conn_rows:
            conns = int(r["conn_cnt"])
            patterns.append(
                PatternItem(
                    pattern_type=PatternType.HIGH_CONNECTIVITY.value,
                    title=f"High connectivity hub: '{r['name']}'",
                    description=f"Concept exhibits observed co-occurrence edges with {conns} distinct concepts.",
                    evidence_summary=f"{conns} bidirectional co-occurrence relationships recorded.",
                    calculation_formula="Topological node degree calculated from co-occurrence matrix",
                    concept_ids=[r["id"]],
                )
            )

        # Pattern: High Source Overlap
        overlap_rows = self._db.fetchall(
            """
            SELECT
                csl_a.source_id AS s_a, s1.title AS title_a,
                csl_b.source_id AS s_b, s2.title AS title_b,
                COUNT(DISTINCT csl_a.concept_id) AS shared_concepts
            FROM concept_source_links csl_a
            JOIN concept_source_links csl_b ON csl_a.concept_id = csl_b.concept_id AND csl_a.source_id < csl_b.source_id
            JOIN sources s1 ON s1.id = csl_a.source_id
            JOIN sources s2 ON s2.id = csl_b.source_id
            GROUP BY s_a, s_b
            HAVING shared_concepts >= 3
            ORDER BY shared_concepts DESC
            LIMIT 2;
            """
        )
        for r in overlap_rows:
            sa = r["s_a"]
            sb = r["s_b"]
            shared_c = int(r["shared_concepts"])

            total_a = self._scalar(
                "SELECT COUNT(DISTINCT concept_id) FROM concept_source_links WHERE source_id = ?;", (sa,)
            )
            total_b = self._scalar(
                "SELECT COUNT(DISTINCT concept_id) FROM concept_source_links WHERE source_id = ?;", (sb,)
            )
            union_c = (total_a + total_b) - shared_c
            if union_c > 0:
                jaccard = round(shared_c / union_c, 3)
                if jaccard >= 0.25:
                    pct = round(jaccard * 100, 1)
                    patterns.append(
                        PatternItem(
                            pattern_type=PatternType.SOURCE_OVERLAP.value,
                            title="Substantial concept overlap between sources",
                            description=f"'{r['title_a']}' and '{r['title_b']}' share {shared_c} concepts ({pct}% overlap).",
                            evidence_summary=f"{shared_c} shared concepts out of {union_c} unique combined concepts.",
                            calculation_formula=f"Jaccard index = {shared_c} / {union_c} = {jaccard}",
                            source_ids=[sa, sb],
                        )
                    )

        # Pattern: Open Research Questions without Evidence
        gap_inv_rows = self._db.fetchall(
            """
            SELECT i.id, i.title,
                   (SELECT COUNT(*) FROM investigation_questions WHERE investigation_id = i.id AND status != 'RESOLVED') AS oq_cnt,
                   (SELECT COUNT(*) FROM investigation_evidence WHERE investigation_id = i.id) AS ev_cnt
            FROM investigations i
            WHERE i.status = 'active'
            ORDER BY oq_cnt DESC;
            """
        )
        for r in gap_inv_rows:
            oq = int(r["oq_cnt"] or 0)
            ev = int(r["ev_cnt"] or 0)
            if oq > 0 and ev == 0:
                patterns.append(
                    PatternItem(
                        pattern_type=PatternType.OPEN_QUESTION_GAP.value,
                        title=f"Unbacked inquiry: '{r['title']}'",
                        description=f"Investigation has {oq} open question{'s' if oq > 1 else ''} but 0 empirical evidence statements recorded.",
                        evidence_summary=f"{oq} open questions, 0 evidence items attached.",
                        calculation_formula="open_questions > 0 AND evidence_count == 0",
                        investigation_ids=[r["id"]],
                    )
                )

        # Pattern: Evidence Concentration
        tot_ev = self._scalar("SELECT COUNT(*) FROM investigation_evidence;")
        if tot_ev >= 4:
            conc_rows = self._db.fetchall(
                """
                SELECT ie.source_id, s.title, COUNT(*) AS ev_cnt
                FROM investigation_evidence ie
                JOIN sources s ON s.id = ie.source_id
                GROUP BY ie.source_id
                HAVING ev_cnt >= (? * 0.4)
                ORDER BY ev_cnt DESC
                LIMIT 1;
                """,
                (tot_ev,),
            )
            for r in conc_rows:
                cnt = int(r["ev_cnt"])
                pct = round(cnt / tot_ev * 100, 1)
                patterns.append(
                    PatternItem(
                        pattern_type=PatternType.EVIDENCE_CONCENTRATION.value,
                        title=f"Evidence concentrated in '{r['title']}'",
                        description=f"Source accounts for {cnt} of {tot_ev} ({pct}%) empirical evidence citations recorded in investigations.",
                        evidence_summary=f"{cnt} of {tot_ev} total evidence records.",
                        calculation_formula=f"Evidence share = {cnt} / {tot_ev} = {pct}%",
                        source_ids=[r["source_id"]],
                    )
                )

        return patterns[:limit]

    def _scalar(self, sql: str, params: tuple = ()) -> int:
        row = self._db.fetchone(sql, params)
        if row:
            val = next(iter(row.values()), 0)
            return int(val or 0)
        return 0
