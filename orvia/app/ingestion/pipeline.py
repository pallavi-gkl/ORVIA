"""
SourceIngestionPipeline — the ONE authoritative path through which all source
import, re-index, and removal operations must flow.

This module consolidates the duplicated post-import steps that previously
lived directly in routes.py.  Every stage is run in order, its outcome
is recorded, and a structured IngestionReport is returned to the caller
so that both the API response and the UI can display real pipeline status.

Design constraints:
  - No LLMs, no embeddings, no external APIs.
  - All data derived from actual uploaded content.
  - Reuses existing services; does NOT duplicate them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result primitives
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    """Outcome of one pipeline stage."""

    stage: str
    success: bool
    detail: str = ""
    concepts_found: int = 0
    relationships_updated: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "success": self.success,
            "detail": self.detail,
            "concepts_found": self.concepts_found,
            "relationships_updated": self.relationships_updated,
            "error": self.error,
        }


@dataclass
class IngestionReport:
    """
    Structured result of a complete source ingestion run.

    Returned from every public method on SourceIngestionPipeline so that
    callers (routes, tests) can inspect per-stage success/failure without
    parsing log output.
    """

    source_id: Optional[str] = None
    source_title: str = ""
    imported: bool = False
    duplicate: bool = False
    duplicate_id: Optional[str] = None
    word_count: int = 0
    character_count: int = 0
    file_size: int = 0
    file_type: str = ""
    filename: str = ""
    stats: dict = field(default_factory=dict)
    stages: list[StageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # ---------- derived ----------

    @property
    def indexed(self) -> bool:
        return any(s.stage == "index" and s.success for s in self.stages)

    @property
    def concepts_updated(self) -> bool:
        return any(s.stage == "concepts" and s.success for s in self.stages)

    @property
    def concepts_found(self) -> int:
        for s in self.stages:
            if s.stage == "concepts":
                return s.concepts_found
        return 0

    @property
    def relationships_updated(self) -> bool:
        return any(s.stage == "relationships" and s.success for s in self.stages)

    @property
    def relationship_count(self) -> int:
        for s in self.stages:
            if s.stage == "relationships":
                return s.relationships_updated
        return 0

    @property
    def overall_success(self) -> bool:
        return self.imported and not self.duplicate

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_title": self.source_title,
            "imported": self.imported,
            "duplicate": self.duplicate,
            "duplicate_id": self.duplicate_id,
            "word_count": self.word_count,
            "character_count": self.character_count,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "filename": self.filename,
            "stats": self.stats,
            "indexed": self.indexed,
            "concepts_updated": self.concepts_updated,
            "concepts_found": self.concepts_found,
            "relationships_updated": self.relationships_updated,
            "relationship_count": self.relationship_count,
            "overall_success": self.overall_success,
            "stages": [s.to_dict() for s in self.stages],
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class SourceIngestionPipeline:
    """
    Single authoritative entry point for:

      ingest_source()  — validate → persist → index → concepts → relationships
                         → graph invalidation → activity recording
      reindex_source() — re-run index + concept stages for an existing source
      remove_source()  — search removal + concept cleanup + relationships
                         + graph invalidation + activity recording
      reanalyze_all()  — analyze every persisted source (e.g. after extractor update)
      rebuild_search_index() — full search rebuild from scratch
    """

    def __init__(
        self,
        import_service: Any,
        search_service: Any,
        concept_service: Any,
        kg_service: Any,
        workspace_service: Optional[Any] = None,
        source_repo: Optional[Any] = None,
    ) -> None:
        self._import_svc = import_service
        self._search_svc = search_service
        self._concept_svc = concept_service
        self._kg_svc = kg_service
        self._workspace_svc = workspace_service
        self._src_repo = source_repo

    # =========================================================================
    # Public API
    # =========================================================================

    def ingest_source(
        self,
        file_bytes: bytes,
        filename: str,
        force_duplicate: bool = False,
        custom_title: Optional[str] = None,
    ) -> IngestionReport:
        """
        Full import pipeline for a new source (file upload or paste).

        Stages:
          1. persist  — save source via SourceImportService
          2. index    — add to search index
          3. concepts — extract + persist concepts
          4. relationships — rebuild pairwise co-occurrence
          5. graph    — invalidate cached graph
          6. activity — record SOURCE_IMPORTED activity
        """
        report = IngestionReport()

        # ── Stage 1: Persist ─────────────────────────────────────────────────
        try:
            result = self._import_svc.import_source(
                file_bytes=file_bytes,
                filename=filename,
                force_duplicate=force_duplicate,
                custom_title=custom_title,
            )
        except Exception as exc:
            report.errors.append(f"persist: {exc}")
            report.stages.append(StageResult(
                stage="persist", success=False, error=str(exc)
            ))
            return report

        report.filename = result.filename or filename
        report.file_type = result.file_type or ""
        report.file_size = result.file_size or 0
        report.word_count = result.word_count or 0
        report.character_count = result.character_count or 0
        report.source_title = result.title or ""
        report.stats = result.stats or {}

        if not result.success:
            if result.is_duplicate:
                report.duplicate = True
                report.duplicate_id = result.duplicate_source_id
                report.source_id = result.duplicate_source_id
                report.source_title = result.title or ""
                report.stages.append(StageResult(
                    stage="persist",
                    success=False,
                    detail="duplicate detected",
                    error=result.error_message,
                ))
            else:
                report.errors.append(result.error_message or "Unknown import error")
                report.stages.append(StageResult(
                    stage="persist", success=False, error=result.error_message
                ))
            return report

        report.imported = True
        report.source_id = result.source_id
        report.stages.append(StageResult(
            stage="persist",
            success=True,
            detail=f"{report.word_count} words stored",
        ))

        self._run_post_import_stages(report)
        return report

    def reindex_source(self, source_id: str) -> IngestionReport:
        """Re-run index + concepts + relationships for an already-persisted source."""
        report = IngestionReport(source_id=source_id, imported=True)

        if self._src_repo is None:
            report.errors.append("source_repo not available for reindex")
            return report

        src = self._src_repo.find_by_id(source_id)
        if not src:
            report.errors.append(f"Source '{source_id}' not found")
            return report

        report.source_title = getattr(src, "title", "")
        self._stage_index(report, src)
        self._stage_concepts(report)
        self._stage_relationships(report)
        self._stage_graph(report)
        return report

    def remove_source(self, source_id: str, source_title: str = "") -> IngestionReport:
        """
        Orchestrate removal of a source and its derived data.
        Note: the actual source row deletion is still handled by the caller
        (SourceRepository.delete) after this returns, to keep the transaction
        boundary in routes.py unchanged.
        """
        report = IngestionReport(source_id=source_id, source_title=source_title)

        # Search removal
        try:
            self._search_svc.remove_source(source_id)
            report.stages.append(StageResult(
                stage="index_remove", success=True, detail="removed from search index"
            ))
        except Exception as exc:
            msg = f"Could not remove from search index: {exc}"
            logger.warning(msg)
            report.warnings.append(msg)
            report.stages.append(StageResult(
                stage="index_remove", success=False, error=str(exc)
            ))

        # Concept cleanup
        try:
            self._concept_svc.delete_source_concepts(source_id)
            report.stages.append(StageResult(
                stage="concepts_remove", success=True, detail="concept links removed"
            ))
        except Exception as exc:
            msg = f"Could not remove concept links: {exc}"
            logger.warning(msg)
            report.warnings.append(msg)
            report.stages.append(StageResult(
                stage="concepts_remove", success=False, error=str(exc)
            ))

        # Rebuild relationships
        self._stage_relationships(report)

        # Graph invalidation
        self._stage_graph(report)

        # Activity
        self._stage_activity(
            report,
            activity_type="source_removed",
            entity_type="source",
            title=f"Source removed: {source_title or source_id}",
            description="Source and all derived data removed from workspace.",
        )

        return report

    def reanalyze_all(self) -> dict[str, Any]:
        """Re-analyze every persisted source. Returns per-source results."""
        try:
            stats = self._concept_svc.analyze_all()
            try:
                self._concept_svc.rebuild_relationships()
            except Exception as exc:
                logger.warning("Could not rebuild relationships after reanalyze_all: %s", exc)
            self._invalidate_graph()
            return {"success": True, "stats": stats}
        except Exception as exc:
            logger.error("reanalyze_all failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def rebuild_search_index(self) -> dict[str, Any]:
        """Rebuild the entire search index from scratch."""
        try:
            self._search_svc.ensure_indexed(force=True)
            return {"success": True}
        except Exception as exc:
            logger.error("rebuild_search_index failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _run_post_import_stages(self, report: IngestionReport) -> None:
        """Run all post-persist stages: index, concepts, relationships, graph, activity."""
        if not report.source_id or self._src_repo is None:
            report.warnings.append(
                "source_repo not configured — skipping post-import stages"
            )
            return

        src = self._src_repo.find_by_id(report.source_id)
        if not src:
            report.warnings.append(
                f"Could not load source '{report.source_id}' for post-import stages"
            )
            return

        self._stage_index(report, src)
        self._stage_concepts(report)
        self._stage_relationships(report)
        self._stage_graph(report)
        self._stage_activity(
            report,
            activity_type="source_imported",
            entity_type="source",
            title=f"Source imported: {report.source_title}",
            description=(
                f"{report.word_count} words · "
                f"{report.concepts_found} concepts extracted"
            ),
            metadata={
                "filename": report.filename,
                "file_type": report.file_type,
                "word_count": report.word_count,
                "concepts_found": report.concepts_found,
            },
        )

    def _stage_index(self, report: IngestionReport, src: Any) -> None:
        try:
            self._search_svc.index_source(src)
            report.stages.append(StageResult(
                stage="index", success=True, detail="added to search index"
            ))
        except Exception as exc:
            msg = f"Search index: {exc}"
            logger.warning("Could not index source %s: %s", report.source_id, exc)
            report.warnings.append(msg)
            report.stages.append(StageResult(
                stage="index", success=False, error=str(exc)
            ))

    def _stage_concepts(self, report: IngestionReport) -> None:
        try:
            result = self._concept_svc.analyze_source(report.source_id)
            # analyze_source returns {"status": ..., "concepts_found": N}
            n = result.get("concepts_found", 0) if isinstance(result, dict) else 0
            report.stages.append(StageResult(
                stage="concepts",
                success=True,
                detail=f"{n} concepts extracted",
                concepts_found=n,
            ))
        except Exception as exc:
            msg = f"Concept analysis: {exc}"
            logger.warning("Could not analyze concepts for %s: %s", report.source_id, exc)
            report.warnings.append(msg)
            report.stages.append(StageResult(
                stage="concepts", success=False, error=str(exc)
            ))

    def _stage_relationships(self, report: IngestionReport) -> None:
        try:
            self._concept_svc.rebuild_relationships()
            report.stages.append(StageResult(
                stage="relationships",
                success=True,
                detail="concept relationships recalculated",
            ))
        except Exception as exc:
            msg = f"Relationships: {exc}"
            logger.warning("Could not rebuild relationships: %s", exc)
            report.warnings.append(msg)
            report.stages.append(StageResult(
                stage="relationships", success=False, error=str(exc)
            ))

    def _stage_graph(self, report: IngestionReport) -> None:
        try:
            self._invalidate_graph()
            report.stages.append(StageResult(
                stage="graph", success=True, detail="knowledge graph cache invalidated"
            ))
        except Exception as exc:
            msg = f"Graph invalidation: {exc}"
            logger.warning(msg)
            report.warnings.append(msg)
            report.stages.append(StageResult(
                stage="graph", success=False, error=str(exc)
            ))

    def _stage_activity(
        self,
        report: IngestionReport,
        activity_type: str,
        entity_type: str,
        title: str,
        description: str = "",
        metadata: Optional[dict] = None,
    ) -> None:
        if self._workspace_svc is None:
            return
        try:
            self._workspace_svc.record_activity(
                activity_type=activity_type,
                entity_type=entity_type,
                entity_id=report.source_id,
                title=title,
                description=description,
                metadata=metadata or {},
            )
            report.stages.append(StageResult(
                stage="activity", success=True, detail="activity recorded"
            ))
        except Exception as exc:
            msg = f"Activity recording: {exc}"
            logger.warning(msg)
            report.warnings.append(msg)
            report.stages.append(StageResult(
                stage="activity", success=False, error=str(exc)
            ))

    def _invalidate_graph(self) -> None:
        try:
            self._kg_svc.invalidate_cache()
        except Exception as exc:
            logger.warning("Could not invalidate knowledge graph cache: %s", exc)
