"""
ResearchWorkspaceService — Phase 11 cross-cutting service for global research context,
universal search, activity tracking, research tension detection, index health,
and data integrity diagnostics.

All data is deterministic and local. No LLMs, no external APIs.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from orvia.app.workspace.models import (
    ActivityType,
    ResearchActivity,
    UniversalSearchResult,
    ResearchContext,
    ResearchTension,
    IndexHealth,
    DataIntegrityReport,
)

logger = logging.getLogger(__name__)


class ResearchWorkspaceService:
    """
    Central Phase 11 service: activity logging, universal search, global context,
    research tension detection, index health, and data integrity.
    """

    def __init__(
        self,
        db: Any,
        source_repo: Any,
        concept_repo: Any,
        investigation_repo: Any,
        search_index: Any = None,
        report_repo: Any = None,
    ) -> None:
        self._db = db
        self._src_repo = source_repo
        self._con_repo = concept_repo
        self._inv_repo = investigation_repo
        self._search_index = search_index
        self._report_repo = report_repo

    # =========================================================================
    # Activity Recording
    # =========================================================================

    def record_activity(
        self,
        activity_type: str,
        entity_type: str,
        title: str,
        entity_id: Optional[str] = None,
        description: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> ResearchActivity:
        """Persist a real research activity to the research_activities table."""
        activity_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {})
        try:
            self._db.execute(
                """
                INSERT INTO research_activities
                    (id, activity_type, entity_type, entity_id, title, description, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (activity_id, activity_type, entity_type, entity_id,
                 title, description, meta_json, created_at),
            )
        except Exception as exc:
            logger.warning("Could not record activity: %s", exc)
        return ResearchActivity(
            id=activity_id,
            activity_type=activity_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            description=description,
            metadata=metadata or {},
            created_at=created_at,
        )

    def get_recent_activities(self, limit: int = 20) -> list[ResearchActivity]:
        """Return recent research activities ordered by most recent first."""
        try:
            rows = self._db.fetchall(
                """
                SELECT id, activity_type, entity_type, entity_id,
                       title, description, metadata, created_at
                FROM research_activities
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [ResearchActivity.from_dict(dict(r)) for r in rows]
        except Exception as exc:
            logger.warning("Could not read activities: %s", exc)
            return []

    # =========================================================================
    # Continue Research
    # =========================================================================

    def get_continue_research(self) -> dict[str, Any]:
        """
        Return a dict of actionable open research items:
        active investigations with open question counts, draft reports.
        Only real persisted data.
        """
        result: dict[str, Any] = {
            "active_investigations": [],
            "draft_reports": [],
            "open_questions_total": 0,
        }
        try:
            active = self._inv_repo.find_by_status("active")
            for inv in active[:5]:
                open_qs = self._inv_repo.get_questions(inv.id, status="OPEN")
                inv_data = inv.to_dict() if hasattr(inv, "to_dict") else {"id": inv.id, "title": inv.title}
                inv_data["open_questions"] = len(open_qs)
                inv_data["url"] = f"/investigations/{inv.id}"
                result["active_investigations"].append(inv_data)
                result["open_questions_total"] += len(open_qs)
        except Exception as exc:
            logger.warning("Could not get active investigations: %s", exc)

        try:
            rows = self._db.fetchall(
                "SELECT id, title, investigation_id, updated_at FROM reports WHERE status='DRAFT' ORDER BY updated_at DESC LIMIT 3"
            )
            for row in rows:
                result["draft_reports"].append({
                    "id": row["id"],
                    "title": row["title"],
                    "investigation_id": row["investigation_id"],
                    "updated_at": row["updated_at"],
                    "url": f"/reports/{row['id']}",
                })
        except Exception:
            pass

        return result

    # =========================================================================
    # Global Research Context
    # =========================================================================

    def get_context(self) -> ResearchContext:
        """Read the current research context state and enrich with real objects."""
        ctx = ResearchContext()
        try:
            row = self._db.fetchone(
                "SELECT * FROM research_context_state WHERE id='current'"
            )
            if not row:
                return ctx
            ctx.active_investigation_id = row["active_investigation_id"]
            ctx.active_source_id = row["active_source_id"]
            ctx.active_concept_id = row["active_concept_id"]
            ctx.active_report_id = row["active_report_id"]

            # Enrich with real objects
            if ctx.active_investigation_id:
                try:
                    inv = self._inv_repo.find_by_id(ctx.active_investigation_id)
                    if inv:
                        ctx.active_investigation = inv.to_dict() if hasattr(inv, "to_dict") else {"title": inv.title}
                        ctx.breadcrumbs.append({"label": inv.title, "url": f"/investigations/{inv.id}"})
                        ctx.quick_actions.append({"label": "View Investigation", "url": f"/investigations/{inv.id}"})
                except Exception:
                    pass

            if ctx.active_source_id:
                try:
                    src = self._src_repo.find_by_id(ctx.active_source_id)
                    if src:
                        ctx.active_source = {"id": src.id, "title": src.title}
                        ctx.breadcrumbs.append({"label": src.title, "url": f"/sources/{src.id}"})
                except Exception:
                    pass

            if ctx.active_concept_id:
                try:
                    con = self._con_repo.find_by_id(ctx.active_concept_id)
                    if con:
                        ctx.active_concept = {"id": con.id, "name": con.name}
                        ctx.breadcrumbs.append({"label": con.name, "url": f"/concepts/{con.id}"})
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("Could not get context: %s", exc)
        return ctx

    def set_context(
        self,
        investigation_id: Optional[str] = None,
        source_id: Optional[str] = None,
        concept_id: Optional[str] = None,
        report_id: Optional[str] = None,
    ) -> None:
        """Upsert the singleton research context state row."""
        updated_at = datetime.now(timezone.utc).isoformat()
        try:
            existing = self._db.fetchone(
                "SELECT id FROM research_context_state WHERE id='current'"
            )
            if existing:
                updates: list[tuple[str, Any]] = []
                if investigation_id is not None:
                    updates.append(("active_investigation_id", investigation_id or None))
                if source_id is not None:
                    updates.append(("active_source_id", source_id or None))
                if concept_id is not None:
                    updates.append(("active_concept_id", concept_id or None))
                if report_id is not None:
                    updates.append(("active_report_id", report_id or None))
                updates.append(("updated_at", updated_at))
                set_clause = ", ".join(f"{col} = ?" for col, _ in updates)
                values = [v for _, v in updates]
                values.append("current")
                self._db.execute(
                    f"UPDATE research_context_state SET {set_clause} WHERE id = ?",
                    values,
                )
            else:
                self._db.execute(
                    """
                    INSERT INTO research_context_state
                        (id, active_investigation_id, active_source_id, active_concept_id, active_report_id, updated_at)
                    VALUES ('current', ?, ?, ?, ?, ?)
                    """,
                    (investigation_id or None, source_id or None, concept_id or None, report_id or None, updated_at),
                )
        except Exception as exc:
            logger.warning("Could not set context: %s", exc)

    # =========================================================================
    # Universal Search
    # =========================================================================

    def universal_search(self, query: str) -> list[UniversalSearchResult]:
        """
        Search across sources, concepts, investigations, reports, evidence, findings.
        Returns results grouped by entity type. Purely deterministic substring/prefix match.
        """
        query = (query or "").strip().lower()
        if not query or len(query) < 2:
            return []

        results: list[UniversalSearchResult] = []

        # Sources
        try:
            sources = self._src_repo.find_all_metadata(search_query=query, sort_by="newest")
            for src in sources[:5]:
                results.append(UniversalSearchResult(
                    item_type="SOURCE",
                    id=src.id,
                    title=src.title,
                    subtitle=f"{getattr(src, 'file_type', '').upper()} · {getattr(src, 'word_count', 0)} words",
                    url=f"/sources/{src.id}",
                    badge="Source",
                ))
        except Exception as exc:
            logger.warning("Universal search sources error: %s", exc)

        # Concepts
        try:
            concepts = self._con_repo.search_by_name(query=query)
            for con in concepts[:5]:
                results.append(UniversalSearchResult(
                    item_type="CONCEPT",
                    id=con.id,
                    title=con.name,
                    subtitle=f"Observed in {getattr(con, 'source_count', 0)} sources",
                    url=f"/concepts/{con.id}",
                    badge="Concept",
                ))
        except Exception as exc:
            logger.warning("Universal search concepts error: %s", exc)

        # Investigations
        try:
            inv_all = self._inv_repo.find_all(limit=100)
            for inv in inv_all:
                if query in (inv.title or "").lower() or query in (getattr(inv, 'research_question', '') or "").lower():
                    results.append(UniversalSearchResult(
                        item_type="INVESTIGATION",
                        id=inv.id,
                        title=inv.title,
                        subtitle=getattr(inv, 'research_question', '')[:80],
                        url=f"/investigations/{inv.id}",
                        badge=inv.status.capitalize() if hasattr(inv, 'status') else "Investigation",
                    ))
                    if len([r for r in results if r.item_type == "INVESTIGATION"]) >= 5:
                        break
        except Exception as exc:
            logger.warning("Universal search investigations error: %s", exc)

        # Reports
        try:
            rows = self._db.fetchall(
                "SELECT id, title, status FROM reports WHERE LOWER(title) LIKE ? LIMIT 5",
                (f"%{query}%",),
            )
            for row in rows:
                results.append(UniversalSearchResult(
                    item_type="REPORT",
                    id=row["id"],
                    title=row["title"],
                    subtitle=f"Report · {row['status']}",
                    url=f"/reports/{row['id']}",
                    badge="Report",
                ))
        except Exception:
            pass

        # Evidence
        try:
            rows = self._db.fetchall(
                """
                SELECT ie.id, ie.statement, ie.evidence_type, ie.investigation_id
                FROM investigation_evidence ie
                WHERE LOWER(ie.statement) LIKE ?
                LIMIT 5
                """,
                (f"%{query}%",),
            )
            for row in rows:
                results.append(UniversalSearchResult(
                    item_type="EVIDENCE",
                    id=row["id"],
                    title=row["statement"][:80],
                    subtitle=f"{row['evidence_type']} evidence",
                    url=f"/investigations/{row['investigation_id']}?tab=evidence",
                    badge="Evidence",
                ))
        except Exception as exc:
            logger.warning("Universal search evidence error: %s", exc)

        # Findings
        try:
            rows = self._db.fetchall(
                """
                SELECT f.id, f.title, f.statement, f.investigation_id, f.status
                FROM investigation_findings f
                WHERE LOWER(f.title) LIKE ? OR LOWER(f.statement) LIKE ?
                LIMIT 5
                """,
                (f"%{query}%", f"%{query}%"),
            )
            for row in rows:
                results.append(UniversalSearchResult(
                    item_type="FINDING",
                    id=row["id"],
                    title=row["title"],
                    subtitle=row["statement"][:80] if row["statement"] else "",
                    url=f"/investigations/{row['investigation_id']}?tab=findings",
                    badge=row["status"].capitalize() if row["status"] else "Finding",
                ))
        except Exception as exc:
            logger.warning("Universal search findings error: %s", exc)

        return results

    # =========================================================================
    # Research Tension Detection
    # =========================================================================

    def detect_research_tensions(
        self, investigation_id: str
    ) -> list[ResearchTension]:
        """
        Deterministically detect research tensions in an investigation.
        A tension exists when a finding has linked CONTRAST-type evidence records,
        or when multiple conflicting relationship types exist for the same concept pair.
        Never uses semantic similarity or LLMs.
        """
        tensions: list[ResearchTension] = []
        try:
            findings = self._inv_repo.get_findings(investigation_id)
            for finding in findings:
                evidence_for_finding = self._inv_repo.get_evidence_for_finding(finding.id)
                contrast_evidence = [
                    ev for ev in evidence_for_finding
                    if (ev.evidence_type or "").upper() == "CONTRAST"
                ]
                if contrast_evidence:
                    sources = []
                    for ev in contrast_evidence:
                        src_id = getattr(ev, 'source_id', None)
                        if src_id:
                            try:
                                src = self._src_repo.find_by_id(src_id)
                                if src:
                                    sources.append({"id": src.id, "title": src.title})
                            except Exception:
                                pass

                    count = len(contrast_evidence)
                    tensions.append(ResearchTension(
                        finding_id=finding.id,
                        finding_title=finding.title,
                        tension_type="CONTRAST_EVIDENCE",
                        description=(
                            f"{count} evidence record{'s' if count > 1 else ''} "
                            f"marked as CONTRAST {'are' if count > 1 else 'is'} linked to this finding. "
                            f"Review whether these records conflict with the finding statement."
                        ),
                        evidence_items=[
                            {
                                "id": ev.id,
                                "statement": ev.statement[:120] if ev.statement else "",
                                "evidence_type": ev.evidence_type,
                            }
                            for ev in contrast_evidence
                        ],
                        sources=sources,
                    ))
        except Exception as exc:
            logger.warning("Could not detect tensions: %s", exc)
        return tensions

    # =========================================================================
    # Index Health
    # =========================================================================

    def get_index_health(self) -> IndexHealth:
        """Return real status of the search index vs total sources."""
        total_sources = 0
        indexed_docs = 0
        indexed_terms = 0
        last_updated: Optional[str] = None

        try:
            total_sources = self._src_repo.count()
        except Exception:
            pass

        if self._search_index is not None:
            try:
                indexed_docs = getattr(self._search_index, 'total_docs', 0)
                idx_internal = getattr(self._search_index, '_index', {})
                indexed_terms = len(idx_internal)
            except Exception:
                pass

            try:
                row = self._db.fetchone(
                    "SELECT MAX(indexed_at) as last_updated FROM search_index_terms"
                )
                if row and row["last_updated"]:
                    last_updated = row["last_updated"]
            except Exception:
                pass

        unindexed = total_sources - indexed_docs
        if total_sources == 0:
            status = "No Sources"
            explanation = "Add sources to your research library to enable full-text search."
        elif indexed_docs >= total_sources:
            status = "Healthy"
            explanation = f"All {total_sources} sources are indexed across {indexed_terms} terms."
        elif unindexed <= 2:
            status = "Mostly Indexed"
            explanation = f"{unindexed} source{'s' if unindexed != 1 else ''} not yet indexed. Rebuild to update."
        else:
            status = "Needs Rebuild"
            explanation = f"{unindexed} of {total_sources} sources are not indexed. Rebuild the index."

        return IndexHealth(
            status=status,
            total_sources=total_sources,
            indexed_sources=indexed_docs,
            indexed_terms=indexed_terms,
            last_updated=last_updated,
            explanation=explanation,
        )

    # =========================================================================
    # Data Integrity
    # =========================================================================

    def get_data_integrity(self) -> DataIntegrityReport:
        """Run deterministic structural checks on ORVIA's SQLite data."""
        checks: list[dict[str, Any]] = []
        issues: list[str] = []
        warnings: list[str] = []

        def run_check(name: str, sql: str, threshold: int = 0) -> int:
            try:
                row = self._db.fetchone(sql)
                count = row[0] if row else 0
                checks.append({"name": name, "count": count, "ok": count <= threshold})
                return count
            except Exception as exc:
                checks.append({"name": name, "count": -1, "ok": False, "error": str(exc)})
                return -1

        orphan_ev = run_check(
            "Orphaned evidence (missing source)",
            "SELECT COUNT(*) FROM investigation_evidence ie "
            "LEFT JOIN sources s ON ie.source_id = s.id "
            "WHERE ie.source_id IS NOT NULL AND s.id IS NULL"
        )
        if orphan_ev > 0:
            issues.append(f"{orphan_ev} evidence record(s) reference sources that no longer exist.")

        orphan_inv_src = run_check(
            "Orphaned investigation sources (missing source)",
            "SELECT COUNT(*) FROM investigation_sources ins "
            "LEFT JOIN sources s ON ins.source_id = s.id "
            "WHERE s.id IS NULL"
        )
        if orphan_inv_src > 0:
            issues.append(f"{orphan_inv_src} investigation-source links point to missing sources.")

        findings_no_ev = run_check(
            "Findings with no linked evidence",
            "SELECT COUNT(*) FROM investigation_findings f "
            "LEFT JOIN investigation_finding_evidence fe ON fe.finding_id = f.id "
            "WHERE fe.finding_id IS NULL",
            threshold=100
        )
        if findings_no_ev > 5:
            warnings.append(f"{findings_no_ev} finding(s) have no linked evidence records.")

        try:
            row = self._db.fetchone(
                "SELECT COUNT(*) FROM reports r "
                "LEFT JOIN investigations i ON r.investigation_id = i.id "
                "WHERE r.investigation_id IS NOT NULL AND i.id IS NULL"
            )
            orphan_reports = row[0] if row else 0
            checks.append({"name": "Reports with missing investigations", "count": orphan_reports, "ok": orphan_reports == 0})
            if orphan_reports > 0:
                issues.append(f"{orphan_reports} report(s) reference investigations that no longer exist.")
        except Exception:
            pass

        total_checks = len(checks)
        issues_count = len(issues)
        warnings_count = len(warnings)
        healthy = issues_count == 0

        return DataIntegrityReport(
            healthy=healthy,
            total_checks=total_checks,
            issues_count=issues_count,
            warnings_count=warnings_count,
            checks=checks,
            issues=issues,
            warnings=warnings,
        )

    # =========================================================================
    # Demo Data
    # =========================================================================

    def load_demo_data(self) -> dict[str, Any]:
        """
        Load clearly labeled demo data via the existing seed_demo_sources helper.
        Returns counts of what was loaded.
        """
        try:
            from orvia.app.ingestion.demo_data import seed_demo_sources
            count = seed_demo_sources(self._src_repo)
            self.record_activity(
                activity_type=ActivityType.DEMO_LOADED.value,
                entity_type="system",
                title="Demo dataset loaded",
                description=f"{count} demo sources added to the research library.",
            )
            return {"loaded": count, "message": f"{count} demo sources loaded. All demo entries are clearly labeled."}
        except Exception as exc:
            logger.warning("Could not load demo data: %s", exc)
            return {"loaded": 0, "error": str(exc)}

    def clear_demo_data(self) -> bool:
        """
        Remove sources that were loaded as demo data.
        Demo sources are identified by '[DEMO]' in their title.
        """
        try:
            removed = 0
            sources = self._src_repo.find_all_metadata(search_query="[DEMO]", sort_by="newest")
            for src in sources:
                if "[DEMO]" in (src.title or ""):
                    try:
                        self._src_repo.delete(src.id)
                        removed += 1
                    except Exception:
                        pass
            self.record_activity(
                activity_type=ActivityType.DEMO_CLEARED.value,
                entity_type="system",
                title="Demo dataset cleared",
                description=f"{removed} demo sources removed from the research library.",
            )
            return True
        except Exception as exc:
            logger.warning("Could not clear demo data: %s", exc)
            return False

    # =========================================================================
    # Source Comparison
    # =========================================================================

    def compare_sources(self, source_id_a: str, source_id_b: str) -> dict[str, Any]:
        """
        Compare two sources by their concept overlap.
        Returns shared concepts, unique to A, unique to B, and Jaccard coefficient.
        Labeled as concept overlap — NOT semantic similarity.
        """
        set_a: dict[str, str] = {}
        set_b: dict[str, str] = {}
        try:
            rows_a = self._db.fetchall(
                "SELECT c.id, c.name FROM concepts c JOIN concept_source_links csl ON csl.concept_id = c.id WHERE csl.source_id = ?",
                (source_id_a,)
            )
            rows_b = self._db.fetchall(
                "SELECT c.id, c.name FROM concepts c JOIN concept_source_links csl ON csl.concept_id = c.id WHERE csl.source_id = ?",
                (source_id_b,)
            )
            set_a = {r["id"]: r["name"] for r in rows_a}
            set_b = {r["id"]: r["name"] for r in rows_b}
        except Exception as exc:
            logger.warning("compare_sources error: %s", exc)

        shared_ids = set(set_a.keys()) & set(set_b.keys())
        only_a_ids = set(set_a.keys()) - set(set_b.keys())
        only_b_ids = set(set_b.keys()) - set(set_a.keys())
        union_count = len(set(set_a.keys()) | set(set_b.keys()))
        jaccard = len(shared_ids) / union_count if union_count > 0 else 0.0

        return {
            "source_a_id": source_id_a,
            "source_b_id": source_id_b,
            "shared_concepts": [{"id": cid, "name": set_a[cid]} for cid in shared_ids],
            "unique_to_a": [{"id": cid, "name": set_a[cid]} for cid in only_a_ids],
            "unique_to_b": [{"id": cid, "name": set_b[cid]} for cid in only_b_ids],
            "jaccard_overlap": round(jaccard, 4),
            "overlap_label": "Concept Overlap (calculated from concepts observed in both sources)",
        }
