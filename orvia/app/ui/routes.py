"""
ORVIA UI Routes
All page routes and API endpoints for the ORVIA research workspace,
including Source Intelligence, Research Library, and Data Ingestion.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from orvia.app.ingestion.demo_data import seed_demo_sources
from orvia.app.ingestion.service import SourceImportService
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.document_repository import DocumentRepository
from orvia.app.repositories.investigation_repository import InvestigationRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.topic_repository import TopicRepository
from orvia.app.storage.file_storage import FileStorage
from orvia.app.search.index import SearchIndex
from orvia.app.search.service import SearchService
from orvia.app.analysis.service import ConceptAnalysisService
from orvia.app.knowledge.graph.service import KnowledgeGraphService
from orvia.app.ingestion.pipeline import SourceIngestionPipeline

logger = logging.getLogger(__name__)


def _get_repos() -> tuple[
    SourceRepository,
    DocumentRepository,
    TopicRepository,
    ConceptRepository,
    InvestigationRepository,
]:
    """Return fresh repository instances bound to the current request's DB connection."""
    from orvia.app.ui import get_db

    db = get_db()
    return (
        SourceRepository(db),
        DocumentRepository(db),
        TopicRepository(db),
        ConceptRepository(db),
        InvestigationRepository(db),
    )


def _get_import_service() -> SourceImportService:
    """Return a SourceImportService initialized with the active database repository."""
    src_r, _, _, _, _ = _get_repos()
    config = current_app.config["ORVIA_CONFIG"]
    storage = FileStorage(config.DATABASE_PATH.parent / "sources")
    return SourceImportService(source_repo=src_r, storage=storage)


def _get_search_service() -> SearchService:
    """Return a SearchService bound to the current database connection and shared index."""
    from orvia.app.ui import get_db
    db = get_db()
    src_r, doc_r, _, _, _ = _get_repos()
    shared_index = current_app.extensions.setdefault("orvia_search_index", SearchIndex(db=db))
    shared_index.db = db
    svc = SearchService(source_repo=src_r, document_repo=doc_r, index=shared_index, db=db)
    if not getattr(shared_index, "_initialized_from_db", False):
        svc.ensure_indexed()
        shared_index._initialized_from_db = True
    return svc


def _get_concept_analysis_service() -> ConceptAnalysisService:
    """Return a ConceptAnalysisService bound to the current DB connection and repositories."""
    from orvia.app.ui import get_db

    db = get_db()
    src_r, _, _, con_r, _ = _get_repos()
    return ConceptAnalysisService(
        db=db,
        source_repo=src_r,
        concept_repo=con_r,
    )


def _get_knowledge_graph_service() -> KnowledgeGraphService:
    """Return a KnowledgeGraphService bound to the active database connection."""
    from orvia.app.ui import get_db

    db = get_db()
    src_r, _, top_r, con_r, _ = _get_repos()
    shared_svc = current_app.extensions.get("orvia_knowledge_graph_service")
    if shared_svc is None or getattr(shared_svc, "_db", None) != db:
        shared_svc = KnowledgeGraphService(
            db=db,
            concept_repo=con_r,
            source_repo=src_r,
            topic_repo=top_r,
        )
        current_app.extensions["orvia_knowledge_graph_service"] = shared_svc
    return shared_svc


def _invalidate_knowledge_graph() -> None:
    """Invalidate cached graph structures when research entities change."""
    svc = current_app.extensions.get("orvia_knowledge_graph_service")
    if svc is not None:
        svc.invalidate_cache()


def _get_workspace_service():
    """Return a ResearchWorkspaceService for activity recording (best-effort)."""
    try:
        from orvia.app.ui import get_db
        from orvia.app.workspace.service import ResearchWorkspaceService
        db = get_db()
        src_r, _, _, con_r, inv_r = _get_repos()
        return ResearchWorkspaceService(
            db=db,
            source_repo=src_r,
            concept_repo=con_r,
            investigation_repo=inv_r,
        )
    except Exception as exc:
        logger.warning("Could not construct workspace service: %s", exc)
        return None


def _get_pipeline() -> SourceIngestionPipeline:
    """
    Return a fully-wired SourceIngestionPipeline for the current request.
    This is the single point of truth for post-import orchestration.
    """
    src_r, _, _, _, _ = _get_repos()
    return SourceIngestionPipeline(
        import_service=_get_import_service(),
        search_service=_get_search_service(),
        concept_service=_get_concept_analysis_service(),
        kg_service=_get_knowledge_graph_service(),
        workspace_service=_get_workspace_service(),
        source_repo=src_r,
    )


def register_routes(app: Flask) -> None:
    """Register all URL routes on the Flask application."""

    # ── Overview ──────────────────────────────────────────────────────────────
    @app.route("/")
    @app.route("/overview")
    def overview():
        src_r, doc_r, top_r, con_r, inv_r = _get_repos()
        concept_svc = _get_concept_analysis_service()
        stats = {
            "sources": src_r.count(),
            "documents": doc_r.count(),
            "topics": top_r.count(),
            "concepts": con_r.count(),
            "investigations": inv_r.count(),
        }
        recent_investigations = inv_r.find_all(limit=5)
        recent_sources = src_r.find_all(limit=5)
        concept_summary = concept_svc.get_collection_summary()
        kg_svc = _get_knowledge_graph_service()
        graph_stats = kg_svc.get_graph_statistics()
        analytics_svc = _get_analytics_service()
        observed_patterns = analytics_svc.get_patterns(limit=3)
        return render_template(
            "overview.html",
            active_page="overview",
            page_title="Overview",
            stats=stats,
            recent_investigations=recent_investigations,
            recent_sources=recent_sources,
            concept_summary=concept_summary,
            graph_stats=graph_stats,
            observed_patterns=observed_patterns,
        )

    # ── Sources (Research Library) ───────────────────────────────────────────
    @app.route("/sources")
    def sources():
        src_r, _, _, _, _ = _get_repos()
        selected_type = request.args.get("type", "all").strip().lower()
        search_query = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "newest").strip().lower()

        # Retrieve metadata only (excluding heavy content field for fast loading)
        sources_list = src_r.find_all_metadata(
            file_type=selected_type,
            search_query=search_query,
            sort_by=sort_by,
        )
        counts = src_r.count_by_type()

        return render_template(
            "sources.html",
            active_page="sources",
            page_title="Sources",
            sources=sources_list,
            counts=counts,
            current_type=selected_type,
            search_query=search_query,
            sort_by=sort_by,
            total_sources=counts.get("all", 0),
        )

    # ── Source Details ────────────────────────────────────────────────────────
    @app.route("/sources/<source_id>")
    def source_detail(source_id: str):
        src_r, _, _, _, _ = _get_repos()
        source = src_r.find_by_id(source_id)
        if not source:
            abort(404)

        # Parse CSV rows for table preview if applicable
        csv_preview_rows = []
        if source.file_type == "csv" and source.content:
            try:
                reader = csv.reader(io.StringIO(source.content.strip()))
                csv_preview_rows = list(reader)[:50]  # preview first 50 rows
            except Exception:
                csv_preview_rows = []

        concept_svc = _get_concept_analysis_service()
        concepts = concept_svc.get_source_concepts(source_id)
        status_info = concept_svc.get_analysis_status(source_id)

        return render_template(
            "source_detail.html",
            active_page="sources",
            page_title=source.title,
            source=source,
            stats=source.metadata or {},
            csv_preview_rows=csv_preview_rows,
            concepts=concepts,
            analysis_status=status_info,
        )

    # ── API: Source Import (File Upload) ──────────────────────────────────────
    @app.route("/api/sources/import", methods=["POST"])
    def api_source_import():
        if "file" not in request.files:
            return jsonify({"status": "error", "error": "No file payload received in request."}), 400

        uploaded_file = request.files["file"]
        if not uploaded_file or not uploaded_file.filename:
            return jsonify({"status": "error", "error": "No file selected."}), 400

        file_bytes = uploaded_file.read()
        filename = uploaded_file.filename
        custom_title = request.form.get("title", "").strip() or None
        force_duplicate = request.form.get("force", "").lower() in ("true", "1", "yes")

        report = _get_pipeline().ingest_source(
            file_bytes=file_bytes,
            filename=filename,
            force_duplicate=force_duplicate,
            custom_title=custom_title,
        )

        if report.duplicate:
            return jsonify({
                "status": "duplicate",
                "error": "A source with identical content already exists.",
                "duplicate_id": report.duplicate_id,
                "title": report.source_title,
                "filename": report.filename,
            }), 409

        if not report.imported:
            error = report.errors[0] if report.errors else "Import failed."
            return jsonify({"status": "error", "error": error}), 400

        return jsonify({
            "status": "ok",
            "source_id": report.source_id,
            "title": report.source_title,
            "filename": report.filename,
            "file_type": report.file_type,
            "file_size": report.file_size,
            "word_count": report.word_count,
            "stats": report.stats,
            "concepts_found": report.concepts_found,
            "pipeline_stages": [s.to_dict() for s in report.stages],
            "warnings": report.warnings,
        })

    # ── API: Paste / Create Text Source ──────────────────────────────────────
    @app.route("/api/sources/paste", methods=["POST"])
    def api_source_paste():
        """
        Accept pasted text (Paste Content / Create Research Note) and persist
        it as a source through the authoritative ingestion pipeline.
        Guarantees identical duplicate detection, indexing, and concept
        analysis to a direct file upload.
        """
        import re as _re
        data = request.get_json(force=True, silent=True) or {}
        title = (data.get("title") or "").strip()
        content = (data.get("content") or "").strip()
        force_duplicate = bool(data.get("force", False))

        if not title:
            return jsonify({"status": "error", "error": "Title is required."}), 400
        if not content:
            return jsonify({"status": "error", "error": "Content cannot be empty."}), 400
        if len(content.encode("utf-8")) > 25 * 1024 * 1024:
            return jsonify({"status": "error", "error": "Content exceeds maximum allowed size (25 MB)."}), 400

        # Build a safe .txt filename from the title
        safe_name = _re.sub(r"[^\w\s-]", "", title).strip()
        safe_name = _re.sub(r"[\s-]+", "_", safe_name)[:80] or "research_note"
        filename = f"{safe_name}.txt"
        file_bytes = content.encode("utf-8")

        report = _get_pipeline().ingest_source(
            file_bytes=file_bytes,
            filename=filename,
            force_duplicate=force_duplicate,
            custom_title=title,
        )

        if report.duplicate:
            return jsonify({
                "status": "duplicate",
                "error": "A source with identical content already exists.",
                "duplicate_id": report.duplicate_id,
                "title": report.source_title,
            }), 409

        if not report.imported:
            error = report.errors[0] if report.errors else "Import failed."
            return jsonify({"status": "error", "error": error}), 400

        return jsonify({
            "status": "ok",
            "source_id": report.source_id,
            "title": report.source_title,
            "filename": report.filename,
            "word_count": report.word_count,
            "character_count": report.character_count,
            "concepts_found": report.concepts_found,
            "pipeline_stages": [s.to_dict() for s in report.stages],
            "warnings": report.warnings,
        })

    # ── API: Delete Source ────────────────────────────────────────────────────
    @app.route("/api/sources/<source_id>/delete", methods=["POST"])
    def api_source_delete(source_id: str):
        src_r, _, _, _, _ = _get_repos()
        # Capture title before deleting
        src = src_r.find_by_id(source_id)
        source_title = getattr(src, "title", "") if src else ""

        # Run pre-delete pipeline stages (search removal, concept cleanup, etc.)
        _get_pipeline().remove_source(source_id, source_title=source_title)

        success = src_r.delete(source_id)
        if not success:
            return jsonify({"status": "error", "error": "Source not found or could not be removed."}), 404
        return jsonify({"status": "ok", "message": "Source removed from workspace."})

    # ── API: Update Source Title ──────────────────────────────────────────────
    @app.route("/api/sources/<source_id>/edit", methods=["POST"])
    def api_source_edit(source_id: str):
        src_r, _, _, _, _ = _get_repos()
        new_title = request.form.get("title") or request.json.get("title") if request.is_json else None
        if not new_title or not new_title.strip():
            return jsonify({"status": "error", "error": "Title cannot be blank."}), 400

        success = src_r.update_title(source_id, new_title.strip())
        if not success:
            return jsonify({"status": "error", "error": "Source not found."}), 404

        try:
            src = src_r.find_by_id(source_id)
            if src:
                _get_search_service().index_source(src)
        except Exception as e:
            logger.warning("Could not re-index edited source %s: %s", source_id, e)

        try:
            concept_svc = _get_concept_analysis_service()
            concept_svc.mark_needs_reanalysis(source_id)
        except Exception as e:
            logger.warning("Could not mark source %s for reanalysis: %s", source_id, e)

        _invalidate_knowledge_graph()

        return jsonify({"status": "ok", "title": new_title.strip()})

    # ── API: Seed Demo Data ───────────────────────────────────────────────────
    @app.route("/api/sources/seed-demo", methods=["POST"])
    def api_seed_demo():
        import_service = _get_import_service()
        results = seed_demo_sources(import_service, force=False)
        imported_count = sum(1 for r in results if r.success)

        if imported_count > 0:
            try:
                _get_search_service().ensure_indexed(force=True)
            except Exception as e:
                logger.warning("Could not re-index after demo seeding: %s", e)
            try:
                concept_svc = _get_concept_analysis_service()
                concept_svc.analyze_all()
            except Exception as e:
                logger.warning("Could not analyze concepts after demo seeding: %s", e)
            _invalidate_knowledge_graph()

        return jsonify(
            {
                "status": "ok",
                "imported": imported_count,
                "message": f"Successfully indexed {imported_count} research reference materials.",
            }
        )

    # ── Search Intelligence ────────────────────────────────────────────────────
    @app.route("/search")
    def search_page():
        query = request.args.get("q", "").strip()
        filter_type = request.args.get("type", "all").strip().lower()
        sort_by = request.args.get("sort", "relevance").strip().lower()

        search_svc = _get_search_service()
        result_set = None
        if query:
            result_set = search_svc.search(
                query=query,
                filter_type=filter_type,
                sort_by=sort_by,
                limit=25,
            )
            if result_set and result_set.results:
                concept_svc = _get_concept_analysis_service()
                for r in result_set.results:
                    if r.source_id:
                        setattr(r, "concepts", concept_svc.get_source_concepts(r.source_id)[:4])

        recent_searches = search_svc.get_search_history(limit=8)
        popular_searches = search_svc.get_popular_searches(limit=5)
        total_sources = search_svc.source_repo.count()

        return render_template(
            "search.html",
            active_page="search",
            page_title="Explore" if not query else f"Explore: {query}",
            query=query,
            result_set=result_set,
            current_type=filter_type,
            sort_by=sort_by,
            recent_searches=recent_searches,
            popular_searches=popular_searches,
            total_sources=total_sources,
        )

    @app.route("/api/search")
    def api_search():
        query = request.args.get("q", "").strip()
        filter_type = request.args.get("type", "all").strip().lower()
        sort_by = request.args.get("sort", "relevance").strip().lower()
        limit = min(int(request.args.get("limit", 25)), 100)
        offset = max(int(request.args.get("offset", 0)), 0)

        if not query:
            return jsonify({"status": "error", "error": "Query parameter 'q' is required."}), 400

        search_svc = _get_search_service()
        result_set = search_svc.search(
            query=query,
            filter_type=filter_type,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )

        concept_svc = _get_concept_analysis_service()

        return jsonify({
            "status": "ok",
            "query": result_set.query,
            "total_hits": result_set.total_hits,
            "duration_ms": result_set.duration_ms,
            "filter_type": result_set.filter_type,
            "sort_by": result_set.sort_by,
            "term_exploration": {
                "term": result_set.term_exploration.term,
                "source_count": result_set.term_exploration.source_count,
                "total_occurrences": result_set.term_exploration.total_occurrences,
                "related_terms": result_set.term_exploration.related_terms,
            } if result_set.term_exploration else None,
            "zero_result_suggestion": {
                "query": result_set.zero_result_suggestion.query,
                "suggestions": result_set.zero_result_suggestion.suggestions,
                "message": result_set.zero_result_suggestion.message,
            } if result_set.zero_result_suggestion else None,
            "results": [
                {
                    "id": r.id,
                    "title": r.title,
                    "source_id": r.source_id,
                    "source_title": r.source_title,
                    "filename": r.filename,
                    "file_type": r.file_type,
                    "score": round(r.score, 4),
                    "relevance_label": r.relevance_label,
                    "match_reason": r.match_reason,
                    "match_count": r.match_count,
                    "snippet": r.snippet,
                    "word_count": r.word_count,
                    "tags": r.tags,
                    "created_at": r.created_at,
                    "matched_terms": r.matched_terms,
                    "concepts": concept_svc.get_source_concepts(r.source_id)[:4] if r.source_id else [],
                }
                for r in result_set.results
            ],
        })

    @app.route("/api/search/history")
    def api_search_history():
        search_svc = _get_search_service()
        limit = min(int(request.args.get("limit", 10)), 50)
        return jsonify({
            "status": "ok",
            "recent": search_svc.get_search_history(limit=limit),
            "popular": search_svc.get_popular_searches(limit=5),
        })

    @app.route("/api/search/clear-history", methods=["POST"])
    def api_search_clear_history():
        search_svc = _get_search_service()
        cleared = search_svc.clear_search_history()
        return jsonify({"status": "ok" if cleared else "error", "cleared": cleared})

    @app.route("/api/search/analytics")
    def api_search_analytics():
        search_svc = _get_search_service()
        return jsonify({
            "status": "ok",
            "analytics": search_svc.get_search_analytics(),
        })

    # ── Investigations ────────────────────────────────────────────────────────
    def _get_investigation_service():
        """Return InvestigationService bound to current request DB."""
        from orvia.app.ui import get_db
        from orvia.app.investigations.service import InvestigationService
        db = get_db()
        src_r, _, _, con_r, inv_r = _get_repos()
        return InvestigationService(db=db, investigation_repo=inv_r, source_repo=src_r, concept_repo=con_r)

    @app.route("/investigations")
    def investigations():
        _, _, _, _, inv_r = _get_repos()
        status_filter = request.args.get("status", "all").strip().lower()
        search_q = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "updated_at").strip()
        order = request.args.get("order", "desc").strip()
        all_invs = inv_r.search(
            query=search_q,
            status=status_filter if status_filter != "all" else None,
            sort_by=sort_by,
            order=order,
        )
        active_investigations = [i for i in all_invs if i.status in ("active", "draft")]
        paused_investigations = [i for i in all_invs if i.status == "paused"]
        completed_investigations = [i for i in all_invs if i.status == "completed"]
        archived_investigations = [i for i in all_invs if i.status == "archived"]
        stats_map = {inv.id: inv_r.get_stats(inv.id).to_dict() for inv in all_invs}
        counts = {
            "active": inv_r.count("active") + inv_r.count("draft"),
            "paused": inv_r.count("paused"),
            "completed": inv_r.count("completed"),
            "archived": inv_r.count("archived"),
            "total": inv_r.count(),
        }
        return render_template(
            "investigations.html",
            active_page="investigations",
            page_title="Research Investigations",
            active_investigations=active_investigations,
            paused_investigations=paused_investigations,
            completed_investigations=completed_investigations,
            archived_investigations=archived_investigations,
            stats_map=stats_map,
            counts=counts,
            search_q=search_q,
            status_filter=status_filter,
            sort_by=sort_by,
        )

    @app.route("/investigations/new", methods=["GET"])
    def investigation_new():
        src_r, _, _, con_r, _ = _get_repos()
        recent_sources = src_r.find_all(limit=20)
        return render_template(
            "investigation_new.html",
            active_page="investigations",
            page_title="New Investigation",
            recent_sources=recent_sources,
        )

    @app.route("/investigations/<inv_id>")
    def investigation_detail(inv_id: str):
        inv_svc = _get_investigation_service()
        try:
            workspace = inv_svc.get_workspace(inv_id)
        except Exception:
            abort(404)
        tab = request.args.get("tab", "overview").strip().lower()
        src_r, _, _, con_r, _ = _get_repos()
        all_sources = src_r.find_all_metadata(limit=50)
        all_concepts = con_r.find_all(limit=100)
        return render_template(
            "investigation_detail.html",
            active_page="investigations",
            page_title=workspace["investigation"].title,
            workspace=workspace,
            active_tab=tab,
            all_sources=all_sources,
            all_concepts=all_concepts,
            source_relationship_types=["RELEVANT", "PRIMARY_EVIDENCE", "BACKGROUND", "CONTRADICTORY", "REFERENCE"],
            concept_roles=["KEY_CONCEPT", "SUPPORTING_CONCEPT", "EMERGING_CONCEPT", "OPEN_CONCEPT"],
            evidence_types=["OBSERVATION", "FACT", "CLAIM", "STATISTIC", "DEFINITION", "EXAMPLE", "CONTRAST"],
            finding_statuses=["DRAFT", "SUPPORTED", "NEEDS_EVIDENCE", "REVISED"],
            question_statuses=["OPEN", "INVESTIGATING", "RESOLVED"],
        )

    @app.route("/api/investigations", methods=["POST"])
    def api_create_investigation():
        data = request.get_json(force=True, silent=True) or {}
        title = (data.get("title") or "").strip()
        research_question = (data.get("research_question") or "").strip()
        description = (data.get("description") or "").strip()
        initial_status = (data.get("status") or "active").strip()
        if not title or not research_question:
            return jsonify({"status": "error", "error": "title and research_question are required."}), 400
        try:
            inv_svc = _get_investigation_service()
            inv = inv_svc.create_investigation(
                title=title, research_question=research_question,
                description=description, initial_status=initial_status,
            )
            return jsonify({"status": "ok", "investigation": inv.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>", methods=["GET"])
    def api_get_investigation(inv_id: str):
        try:
            inv_svc = _get_investigation_service()
            inv = inv_svc.get_investigation(inv_id)
            return jsonify({"status": "ok", "investigation": inv.to_dict()})
        except Exception:
            return jsonify({"status": "error", "error": "Investigation not found."}), 404

    @app.route("/api/investigations/<inv_id>", methods=["POST"])
    def api_update_investigation(inv_id: str):
        data = request.get_json(force=True, silent=True) or {}
        try:
            inv_svc = _get_investigation_service()
            inv = inv_svc.update_investigation(
                investigation_id=inv_id, title=data.get("title"),
                research_question=data.get("research_question"), description=data.get("description"),
            )
            return jsonify({"status": "ok", "investigation": inv.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/status", methods=["POST"])
    def api_update_investigation_status(inv_id: str):
        data = request.get_json(force=True, silent=True) or {}
        new_status = (data.get("status") or "").strip()
        if not new_status:
            return jsonify({"status": "error", "error": "status is required."}), 400
        try:
            inv_svc = _get_investigation_service()
            inv, warning = inv_svc.transition_status(inv_id, new_status)
            return jsonify({"status": "ok", "investigation": inv.to_dict(), "warning": warning})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/delete", methods=["POST"])
    def api_delete_investigation(inv_id: str):
        try:
            inv_svc = _get_investigation_service()
            inv_svc.delete_investigation(inv_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/stats", methods=["GET"])
    def api_investigation_stats(inv_id: str):
        _, _, _, _, inv_r = _get_repos()
        stats = inv_r.get_stats(inv_id)
        return jsonify({"status": "ok", "stats": stats.to_dict()})

    @app.route("/api/investigations/<inv_id>/sources", methods=["POST"])
    def api_attach_source_to_investigation(inv_id: str):
        data = request.get_json(force=True, silent=True) or {}
        source_id = (data.get("source_id") or "").strip()
        rel_type = (data.get("relationship_type") or "RELEVANT").strip()
        notes = (data.get("notes") or "").strip() or None
        if not source_id:
            return jsonify({"status": "error", "error": "source_id required."}), 400
        try:
            inv_svc = _get_investigation_service()
            s = inv_svc.attach_source(inv_id, source_id, rel_type, notes)
            return jsonify({"status": "ok", "source": s.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/sources/<source_id>/remove", methods=["POST"])
    def api_detach_source_from_investigation(inv_id: str, source_id: str):
        try:
            inv_svc = _get_investigation_service()
            inv_svc.detach_source(inv_id, source_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/concepts", methods=["POST"])
    def api_track_concept_in_investigation(inv_id: str):
        data = request.get_json(force=True, silent=True) or {}
        concept_id = (data.get("concept_id") or "").strip()
        role = (data.get("role") or "KEY_CONCEPT").strip()
        notes = (data.get("notes") or "").strip() or None
        if not concept_id:
            return jsonify({"status": "error", "error": "concept_id required."}), 400
        try:
            inv_svc = _get_investigation_service()
            c = inv_svc.track_concept(inv_id, concept_id, role, notes)
            return jsonify({"status": "ok", "concept": c.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/concepts/<concept_id>/remove", methods=["POST"])
    def api_untrack_concept_from_investigation(inv_id: str, concept_id: str):
        try:
            inv_svc = _get_investigation_service()
            inv_svc.untrack_concept(inv_id, concept_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/evidence", methods=["GET"])
    def api_list_investigation_evidence(inv_id: str):
        _, _, _, _, inv_r = _get_repos()
        ev_type = request.args.get("type", "").strip()
        evidence_list = inv_r.get_evidence_for_investigation(inv_id, evidence_type=ev_type or None)
        return jsonify({"status": "ok", "evidence": [e.to_dict() for e in evidence_list]})

    @app.route("/api/investigations/<inv_id>/evidence", methods=["POST"])
    def api_record_investigation_evidence(inv_id: str):
        data = request.get_json(force=True, silent=True) or {}
        source_id = (data.get("source_id") or "").strip()
        statement = (data.get("statement") or "").strip()
        if not source_id or not statement:
            return jsonify({"status": "error", "error": "source_id and statement are required."}), 400
        try:
            inv_svc = _get_investigation_service()
            ev = inv_svc.record_evidence(
                investigation_id=inv_id, source_id=source_id, statement=statement,
                excerpt=data.get("excerpt", ""), location=data.get("location", ""),
                evidence_type=data.get("evidence_type", "OBSERVATION"),
                confidence=float(data.get("confidence", 1.0)),
                notes=data.get("notes"), title=data.get("title", ""),
            )
            return jsonify({"status": "ok", "evidence": ev.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/evidence/<ev_id>/delete", methods=["POST"])
    def api_delete_investigation_evidence(inv_id: str, ev_id: str):
        try:
            inv_svc = _get_investigation_service()
            inv_svc.delete_evidence(ev_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/questions", methods=["POST"])
    def api_add_investigation_question(inv_id: str):
        data = request.get_json(force=True, silent=True) or {}
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"status": "error", "error": "question is required."}), 400
        try:
            inv_svc = _get_investigation_service()
            q = inv_svc.add_question(inv_id, question)
            return jsonify({"status": "ok", "question": q.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/questions/<q_id>/status", methods=["POST"])
    def api_update_investigation_question_status(inv_id: str, q_id: str):
        data = request.get_json(force=True, silent=True) or {}
        status = (data.get("status") or "").strip()
        resolution_note = (data.get("resolution_note") or "").strip() or None
        try:
            inv_svc = _get_investigation_service()
            q = inv_svc.update_question_status(q_id, status, resolution_note)
            return jsonify({"status": "ok", "question": q.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/questions/<q_id>/delete", methods=["POST"])
    def api_delete_investigation_question(inv_id: str, q_id: str):
        try:
            inv_svc = _get_investigation_service()
            inv_svc.delete_question(q_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/findings", methods=["POST"])
    def api_record_investigation_finding(inv_id: str):
        data = request.get_json(force=True, silent=True) or {}
        title = (data.get("title") or "").strip()
        statement = (data.get("statement") or "").strip()
        if not title or not statement:
            return jsonify({"status": "error", "error": "title and statement are required."}), 400
        try:
            inv_svc = _get_investigation_service()
            f = inv_svc.record_finding(inv_id, title, statement, data.get("status", "DRAFT"), data.get("evidence_ids", []))
            return jsonify({"status": "ok", "finding": f.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/findings/<f_id>/link-evidence", methods=["POST"])
    def api_link_evidence_to_investigation_finding(inv_id: str, f_id: str):
        data = request.get_json(force=True, silent=True) or {}
        ev_id = (data.get("evidence_id") or "").strip()
        if not ev_id:
            return jsonify({"status": "error", "error": "evidence_id required."}), 400
        try:
            inv_svc = _get_investigation_service()
            inv_svc.link_evidence_to_finding(f_id, ev_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/findings/<f_id>/delete", methods=["POST"])
    def api_delete_investigation_finding(inv_id: str, f_id: str):
        try:
            inv_svc = _get_investigation_service()
            inv_svc.delete_finding(f_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/notes", methods=["POST"])
    def api_add_investigation_note(inv_id: str):
        data = request.get_json(force=True, silent=True) or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"status": "error", "error": "content required."}), 400
        try:
            inv_svc = _get_investigation_service()
            note = inv_svc.add_note(inv_id, data.get("title", ""), content, data.get("note_type", "GENERAL"))
            return jsonify({"status": "ok", "note": note.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/notes/<note_id>/delete", methods=["POST"])
    def api_delete_investigation_note(inv_id: str, note_id: str):
        try:
            inv_svc = _get_investigation_service()
            inv_svc.delete_note(note_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/investigations/<inv_id>/activity", methods=["GET"])
    def api_investigation_activity(inv_id: str):
        _, _, _, _, inv_r = _get_repos()
        limit = int(request.args.get("limit", 50))
        acts = inv_r.get_activities(inv_id, limit=limit)
        return jsonify({"status": "ok", "activities": [a.to_dict() for a in acts]})

    @app.route("/api/investigations/<inv_id>/graph", methods=["GET"])
    def api_investigation_graph(inv_id: str):
        kg_svc = _get_knowledge_graph_service()
        graph_data = kg_svc.get_investigation_graph(inv_id)
        return jsonify({"status": "ok", "graph": graph_data})

    # ── Concepts (Concept Intelligence) ──────────────────────────────────────
    @app.route("/concepts")
    @app.route("/concepts", endpoint="concepts")
    def concepts_page():
        search_query = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "frequency").strip().lower()
        sort_dir = request.args.get("order", "desc").strip().lower()
        ngram_arg = request.args.get("ngram", "all").strip().lower()

        ngram_filter = None
        if ngram_arg in ("1", "single", "unigram"):
            ngram_filter = 1
        elif ngram_arg in ("2", "phrase", "ngram", "bigram"):
            ngram_filter = 2

        concept_svc = _get_concept_analysis_service()
        concepts_list = concept_svc.get_concepts_list(
            search=search_query,
            sort_by=sort_by,
            sort_dir=sort_dir,
            ngram_filter=ngram_filter,
            limit=100,
        )
        summary = concept_svc.get_collection_summary()

        return render_template(
            "concepts.html",
            active_page="concepts",
            page_title="Concepts",
            concepts=concepts_list,
            summary=summary,
            search_query=search_query,
            sort_by=sort_by,
            sort_dir=sort_dir,
            ngram_filter=ngram_arg,
            total_concepts=len(concepts_list),
        )

    @app.route("/concepts/<concept_id>")
    def concept_detail(concept_id: str):
        concept_svc = _get_concept_analysis_service()
        detail = concept_svc.get_concept_detail(concept_id)
        if not detail:
            abort(404)

        return render_template(
            "concept_detail.html",
            active_page="concepts",
            page_title=f"Concept · {detail['display']}",
            concept=detail,
        )

    # ── API: Concept Intelligence ────────────────────────────────────────────
    @app.route("/api/concepts")
    def api_concepts():
        search_query = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "frequency").strip().lower()
        sort_dir = request.args.get("order", "desc").strip().lower()
        ngram_arg = request.args.get("ngram", "all").strip().lower()
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)

        ngram_filter = None
        if ngram_arg in ("1", "single", "unigram"):
            ngram_filter = 1
        elif ngram_arg in ("2", "phrase", "ngram"):
            ngram_filter = 2

        concept_svc = _get_concept_analysis_service()
        concepts_list = concept_svc.get_concepts_list(
            search=search_query,
            sort_by=sort_by,
            sort_dir=sort_dir,
            ngram_filter=ngram_filter,
            limit=limit,
            offset=offset,
        )
        return jsonify({
            "status": "ok",
            "total": len(concepts_list),
            "concepts": concepts_list,
        })

    @app.route("/api/concepts/<concept_id>")
    def api_concept_detail(concept_id: str):
        concept_svc = _get_concept_analysis_service()
        detail = concept_svc.get_concept_detail(concept_id)
        if not detail:
            return jsonify({"status": "error", "error": "Concept not found"}), 404
        return jsonify({"status": "ok", "concept": detail})

    @app.route("/api/concepts/analyze", methods=["POST"])
    def api_concepts_analyze_all():
        concept_svc = _get_concept_analysis_service()
        result = concept_svc.analyze_all()
        _invalidate_knowledge_graph()
        return jsonify({"status": "ok", "result": result})

    @app.route("/api/concepts/analyze/<source_id>", methods=["POST"])
    def api_concepts_analyze_source(source_id: str):
        concept_svc = _get_concept_analysis_service()
        result = concept_svc.analyze_source(source_id)
        if result.get("status") == "analyzed":
            concept_svc.rebuild_relationships()
        _invalidate_knowledge_graph()
        return jsonify({"status": "ok", "result": result})

    @app.route("/api/concepts/rebuild-relationships", methods=["POST"])
    def api_concepts_rebuild_relationships():
        concept_svc = _get_concept_analysis_service()
        count = concept_svc.rebuild_relationships()
        _invalidate_knowledge_graph()
        return jsonify({"status": "ok", "relationships_count": count})

    @app.route("/api/concepts/summary")
    def api_concepts_summary():
        concept_svc = _get_concept_analysis_service()
        summary = concept_svc.get_collection_summary()
        return jsonify({
            "status": "ok",
            "total_concepts": summary.total_concepts,
            "total_sources_analyzed": summary.total_sources_analyzed,
            "avg_concepts_per_source": summary.avg_concepts_per_source,
            "top_concepts": summary.top_concepts,
            "emerging_concepts": summary.emerging_concepts,
            "recently_detected": summary.recently_detected,
        })

    # ── Explore ───────────────────────────────────────────────────────────────
    @app.route("/explore")
    def explore():
        src_r, doc_r, top_r, con_r, _ = _get_repos()
        return render_template(
            "explore.html",
            active_page="explore",
            page_title="Explore",
            source_count=src_r.count(),
            document_count=doc_r.count(),
            topic_count=top_r.count(),
            concept_count=con_r.count(),
        )

    # ── Research Analytics & Pattern Intelligence (Phase 9) ───────────────────
    def _get_analytics_service():
        """Return AnalyticsService bound to current request DB."""
        from orvia.app.ui import get_db
        from orvia.app.analysis.analytics.service import AnalyticsService
        db = get_db()
        return AnalyticsService(db=db)

    @app.route("/analyze")
    @app.route("/analyze/patterns")
    def analyze():
        analytics_svc = _get_analytics_service()
        time_range = request.args.get("time_range", "all").strip().lower()
        if time_range not in ("all", "7d", "30d", "90d"):
            time_range = "all"
        active_tab = request.args.get("tab", "overview").strip().lower()

        data = analytics_svc.get_full_analytics(time_range=time_range)

        # For comparison tools:
        src_r, _, _, con_r, _ = _get_repos()
        all_sources = src_r.find_all(limit=100)
        all_concepts = con_r.find_all(limit=150)

        source_a_id = request.args.get("source_a", "").strip()
        source_b_id = request.args.get("source_b", "").strip()
        source_comparison = None
        if source_a_id and source_b_id and source_a_id != source_b_id:
            try:
                source_comparison = analytics_svc.compare_sources(source_a_id, source_b_id)
            except Exception:
                pass

        concept_a_id = request.args.get("concept_a", "").strip()
        concept_b_id = request.args.get("concept_b", "").strip()
        concept_comparison = None
        if concept_a_id and concept_b_id and concept_a_id != concept_b_id:
            try:
                concept_comparison = analytics_svc.compare_concepts(concept_a_id, concept_b_id)
            except Exception:
                pass

        return render_template(
            "analyze.html",
            active_page="analyze",
            page_title="Research Analytics & Pattern Intelligence",
            analytics=data,
            time_range=time_range,
            active_tab=active_tab,
            all_sources=all_sources,
            all_concepts=all_concepts,
            source_a_id=source_a_id,
            source_b_id=source_b_id,
            source_comparison=source_comparison,
            concept_a_id=concept_a_id,
            concept_b_id=concept_b_id,
            concept_comparison=concept_comparison,
        )

    @app.route("/api/analytics/overview")
    def api_analytics_overview():
        analytics_svc = _get_analytics_service()
        time_range = request.args.get("time_range", "all").strip().lower()
        snapshot = analytics_svc.get_collection_snapshot(time_range=time_range)
        return jsonify({"status": "ok", "snapshot": snapshot.to_dict()})

    @app.route("/api/analytics/patterns")
    def api_analytics_patterns():
        analytics_svc = _get_analytics_service()
        limit = min(int(request.args.get("limit", 15)), 50)
        patterns = analytics_svc.get_patterns(limit=limit)
        return jsonify({"status": "ok", "patterns": [p.to_dict() for p in patterns]})

    @app.route("/api/analytics/concepts")
    def api_analytics_concepts():
        analytics_svc = _get_analytics_service()
        limit = min(int(request.args.get("limit", 50)), 200)
        sort_by = request.args.get("sort_by", "occurrences").strip()
        order = request.args.get("order", "desc").strip()
        concepts = analytics_svc.get_concept_patterns(limit=limit, sort_by=sort_by, order=order)
        return jsonify({"status": "ok", "concepts": [c.to_dict() for c in concepts]})

    @app.route("/api/analytics/sources")
    def api_analytics_sources():
        analytics_svc = _get_analytics_service()
        limit = min(int(request.args.get("limit", 50)), 200)
        sort_by = request.args.get("sort_by", "concept_count").strip()
        order = request.args.get("order", "desc").strip()
        sources = analytics_svc.get_source_patterns(limit=limit, sort_by=sort_by, order=order)
        return jsonify({"status": "ok", "sources": [s.to_dict() for s in sources]})

    @app.route("/api/analytics/temporal")
    def api_analytics_temporal():
        analytics_svc = _get_analytics_service()
        interval = request.args.get("interval", "daily").strip().lower()
        limit = min(int(request.args.get("limit", 30)), 100)
        temporal = analytics_svc.get_temporal_trends(interval=interval, limit=limit)
        return jsonify({"status": "ok", "temporal": temporal.to_dict()})

    @app.route("/api/analytics/coverage")
    def api_analytics_coverage():
        analytics_svc = _get_analytics_service()
        coverage = analytics_svc.get_coverage_analysis()
        return jsonify({"status": "ok", "coverage": coverage.to_dict()})

    @app.route("/api/analytics/compare/sources")
    def api_analytics_compare_sources():
        source_a = request.args.get("source_a", "").strip()
        source_b = request.args.get("source_b", "").strip()
        if not source_a or not source_b:
            return jsonify({"status": "error", "error": "Both source_a and source_b are required."}), 400
        analytics_svc = _get_analytics_service()
        try:
            comparison = analytics_svc.compare_sources(source_a, source_b)
            return jsonify({"status": "ok", "comparison": comparison.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/analytics/compare/concepts")
    def api_analytics_compare_concepts():
        concept_a = request.args.get("concept_a", "").strip()
        concept_b = request.args.get("concept_b", "").strip()
        if not concept_a or not concept_b:
            return jsonify({"status": "error", "error": "Both concept_a and concept_b are required."}), 400
        analytics_svc = _get_analytics_service()
        try:
            comparison = analytics_svc.compare_concepts(concept_a, concept_b)
            return jsonify({"status": "ok", "comparison": comparison.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/analytics/investigations")
    def api_analytics_investigations():
        analytics_svc = _get_analytics_service()
        coverage = analytics_svc.get_coverage_analysis()
        return jsonify({"status": "ok", "investigations": coverage.investigation_coverage})

    # ── Knowledge Graph ───────────────────────────────────────────────────────
    @app.route("/knowledge")
    @app.route("/knowledge/graph")
    def knowledge():
        src_r, _, top_r, con_r, _ = _get_repos()
        kg_svc = _get_knowledge_graph_service()

        focus_concept_id = request.args.get("focus", "").strip() or None
        mode = request.args.get("mode", "overview").strip().lower()
        if focus_concept_id and mode == "overview":
            mode = "focus"

        stats = kg_svc.get_graph_statistics()
        initial_graph = kg_svc.get_graph(
            mode=mode,
            focus_concept_id=focus_concept_id,
            max_nodes=35,
        )

        return render_template(
            "knowledge.html",
            active_page="knowledge",
            page_title="Knowledge Graph",
            topic_count=top_r.count(),
            concept_count=con_r.count(),
            source_count=src_r.count(),
            stats=stats,
            initial_graph=initial_graph,
            focus_concept_id=focus_concept_id,
            mode=mode,
        )

    # ── API: Knowledge Graph ─────────────────────────────────────────────────
    @app.route("/api/knowledge/graph")
    def api_knowledge_graph():
        kg_svc = _get_knowledge_graph_service()

        mode = request.args.get("mode", "overview").strip().lower()
        focus_id = request.args.get("focus", "").strip() or None
        if focus_id and mode == "overview":
            mode = "focus"

        search_q = request.args.get("q", "").strip()
        min_strength = float(request.args.get("min_strength", 0.0))
        max_nodes = min(int(request.args.get("max_nodes", 40)), 200)
        max_edges = min(int(request.args.get("max_edges", 80)), 400)

        raw_types = request.args.get("types", "").strip()
        node_types = (
            [t.strip().lower() for t in raw_types.split(",") if t.strip()]
            if raw_types
            else None
        )

        graph_data = kg_svc.get_graph(
            mode=mode,
            node_types=node_types,
            min_strength=min_strength,
            max_nodes=max_nodes,
            max_edges=max_edges,
            search_query=search_q,
            focus_concept_id=focus_id,
        )
        return jsonify({"status": "ok", "graph": graph_data})

    @app.route("/api/knowledge/graph/concept/<concept_id>")
    def api_knowledge_concept_neighborhood(concept_id: str):
        kg_svc = _get_knowledge_graph_service()
        depth = min(int(request.args.get("depth", 1)), 3)
        graph_data = kg_svc.get_concept_neighborhood(concept_id, depth=depth)
        return jsonify({"status": "ok", "graph": graph_data})

    @app.route("/api/knowledge/graph/relationship/<concept_a_id>/<concept_b_id>")
    def api_knowledge_relationship_explanation(concept_a_id: str, concept_b_id: str):
        kg_svc = _get_knowledge_graph_service()
        explanation = kg_svc.get_relationship_explanation(concept_a_id, concept_b_id)
        if "error" in explanation:
            return jsonify({"status": "error", "error": explanation["error"]}), 404
        return jsonify({"status": "ok", "relationship": explanation})

    @app.route("/api/knowledge/graph/stats")
    def api_knowledge_graph_stats():
        kg_svc = _get_knowledge_graph_service()
        return jsonify({"status": "ok", "stats": kg_svc.get_graph_statistics()})

    @app.route("/api/knowledge/graph/search")
    def api_knowledge_graph_search():
        q = request.args.get("q", "").strip()
        kg_svc = _get_knowledge_graph_service()
        results = kg_svc.search_graph(q)
        return jsonify({"status": "ok", "results": results})

    @app.route("/api/knowledge/graph/rebuild", methods=["POST"])
    def api_knowledge_graph_rebuild():
        kg_svc = _get_knowledge_graph_service()
        kg_svc.invalidate_cache()
        stats = kg_svc.get_graph_statistics()
        return jsonify({
            "status": "ok",
            "message": "Knowledge graph cache rebuilt",
            "stats": stats,
        })

    # ── Reports (Phase 10) ───────────────────────────────────────────────────
    def _get_report_service():
        """Return ResearchReportService bound to current request DB."""
        from orvia.app.reports.service import ResearchReportService
        from orvia.app.analysis.analytics.service import AnalyticsService
        from orvia.app.ui import get_db
        db = get_db()
        src_r, _, _, con_r, inv_r = _get_repos()
        analytics_svc = AnalyticsService(db)
        return ResearchReportService(
            db=db,
            investigation_repo=inv_r,
            source_repo=src_r,
            concept_repo=con_r,
            analytics_service=analytics_svc,
        )

    @app.route("/reports")
    def reports():
        svc = _get_report_service()
        _, _, _, _, inv_r = _get_repos()
        status_filter = request.args.get("status", "all").strip().lower()
        search_q = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "updated_at").strip()
        order = request.args.get("order", "desc").strip()
        reports_list = svc.list_reports(
            status=status_filter.upper() if status_filter != "all" else None,
            search_query=search_q or None,
            sort_by=sort_by,
            order=order,
            limit=100,
        )
        counts = {
            "total": len(reports_list),
            "draft": sum(1 for r in reports_list if r["status"] == "DRAFT"),
            "in_review": sum(1 for r in reports_list if r["status"] == "IN_REVIEW"),
            "final": sum(1 for r in reports_list if r["status"] == "FINAL"),
            "archived": sum(1 for r in reports_list if r["status"] == "ARCHIVED"),
        }
        all_invs = inv_r.find_all(limit=100)
        return render_template(
            "reports.html",
            active_page="reports",
            page_title="Research Reports & Synthesis",
            reports_list=reports_list,
            counts=counts,
            all_invs=all_invs,
            search_q=search_q,
            status_filter=status_filter,
            sort_by=sort_by,
            investigation_count=inv_r.count(),
        )

    @app.route("/reports/<report_id>")
    def report_detail(report_id: str):
        svc = _get_report_service()
        try:
            workspace = svc.get_report(report_id)
        except Exception:
            abort(404)
        tab = request.args.get("tab", "preview").strip().lower()
        quality = None
        try:
            quality = svc.get_quality_metrics(report_id).to_dict()
        except Exception:
            pass
        versions = []
        try:
            versions = [v.to_dict() for v in svc.get_versions(report_id)]
        except Exception:
            pass
        return render_template(
            "report_detail.html",
            active_page="reports",
            page_title=workspace["report"]["title"],
            workspace=workspace,
            active_tab=tab,
            quality=quality,
            versions=versions,
            section_types=[
                "EXECUTIVE_SUMMARY", "RESEARCH_QUESTION", "SCOPE", "SOURCES",
                "KEY_CONCEPTS", "EVIDENCE", "FINDINGS", "COMPARISON",
                "PATTERNS", "RELATIONSHIPS", "OPEN_QUESTIONS", "LIMITATIONS",
                "CONCLUSION", "REFERENCES",
            ],
        )

    @app.route("/api/reports", methods=["POST"])
    def api_create_report():
        data = request.get_json(force=True, silent=True) or {}
        investigation_id = (data.get("investigation_id") or "").strip()
        if not investigation_id:
            return jsonify({"status": "error", "error": "investigation_id is required."}), 400
        try:
            svc = _get_report_service()
            workspace = svc.create_report(
                investigation_id=investigation_id,
                title=data.get("title", "") or None,
                subtitle=data.get("subtitle", "") or None,
                selected_sections=data.get("selected_sections") or None,
            )
            return jsonify({"status": "ok", "report": workspace["report"]}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>", methods=["GET"])
    def api_get_report(report_id: str):
        try:
            svc = _get_report_service()
            workspace = svc.get_report(report_id)
            return jsonify({"status": "ok", "workspace": workspace})
        except Exception:
            return jsonify({"status": "error", "error": "Report not found."}), 404

    @app.route("/api/reports/<report_id>", methods=["POST"])
    def api_update_report(report_id: str):
        data = request.get_json(force=True, silent=True) or {}
        try:
            svc = _get_report_service()
            report = svc.update_report(
                report_id=report_id,
                title=data.get("title"),
                subtitle=data.get("subtitle"),
                summary=data.get("summary"),
            )
            return jsonify({"status": "ok", "report": report.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/status", methods=["POST"])
    def api_update_report_status(report_id: str):
        data = request.get_json(force=True, silent=True) or {}
        new_status = (data.get("status") or "").strip()
        if not new_status:
            return jsonify({"status": "error", "error": "status is required."}), 400
        try:
            svc = _get_report_service()
            report = svc.update_report_status(report_id, new_status)
            return jsonify({"status": "ok", "report": report.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/delete", methods=["POST"])
    def api_delete_report(report_id: str):
        try:
            svc = _get_report_service()
            svc.delete_report(report_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/version", methods=["POST"])
    def api_create_report_version(report_id: str):
        data = request.get_json(force=True, silent=True) or {}
        new_status = (data.get("status") or "DRAFT").strip()
        try:
            svc = _get_report_service()
            new_report = svc.create_version(report_id, new_status)
            return jsonify({"status": "ok", "report": new_report.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/versions", methods=["GET"])
    def api_get_report_versions(report_id: str):
        try:
            svc = _get_report_service()
            versions = svc.get_versions(report_id)
            return jsonify({"status": "ok", "versions": [v.to_dict() for v in versions]})
        except Exception:
            return jsonify({"status": "error", "error": "Report not found."}), 404

    @app.route("/api/reports/<report_id>/compare/<other_id>", methods=["GET"])
    def api_compare_report_versions(report_id: str, other_id: str):
        try:
            svc = _get_report_service()
            diff = svc.compare_versions(report_id, other_id)
            return jsonify({"status": "ok", "diff": diff.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/quality", methods=["GET"])
    def api_report_quality(report_id: str):
        try:
            svc = _get_report_service()
            quality = svc.get_quality_metrics(report_id)
            return jsonify({"status": "ok", "quality": quality.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/export/markdown", methods=["GET"])
    def api_export_report_markdown(report_id: str):
        try:
            svc = _get_report_service()
            md = svc.export_markdown(report_id)
            from flask import Response
            return Response(
                md, mimetype="text/markdown",
                headers={"Content-Disposition": f"attachment; filename=report-{report_id[:8]}.md"}
            )
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/sections", methods=["POST"])
    def api_add_report_section(report_id: str):
        data = request.get_json(force=True, silent=True) or {}
        section_type = (data.get("section_type") or "").strip().upper()
        title = (data.get("title") or "").strip()
        if not section_type or not title:
            return jsonify({"status": "error", "error": "section_type and title are required."}), 400
        try:
            svc = _get_report_service()
            sec = svc.add_custom_section(
                report_id=report_id,
                section_type=section_type,
                title=title,
                content=data.get("content", ""),
                position=data.get("position"),
            )
            return jsonify({"status": "ok", "section": sec.to_dict()}), 201
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/sections/<section_id>", methods=["POST"])
    def api_update_report_section(report_id: str, section_id: str):
        data = request.get_json(force=True, silent=True) or {}
        try:
            svc = _get_report_service()
            sec = svc.update_section(
                section_id=section_id,
                title=data.get("title"),
                content=data.get("content"),
                position=data.get("position"),
            )
            return jsonify({"status": "ok", "section": sec.to_dict()})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/sections/<section_id>/delete", methods=["POST"])
    def api_delete_report_section(report_id: str, section_id: str):
        try:
            svc = _get_report_service()
            svc.delete_section(section_id)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/sections/reorder", methods=["POST"])
    def api_reorder_report_sections(report_id: str):
        data = request.get_json(force=True, silent=True) or {}
        section_ids = data.get("section_ids", [])
        if not section_ids:
            return jsonify({"status": "error", "error": "section_ids list required."}), 400
        try:
            svc = _get_report_service()
            svc.reorder_sections(report_id, section_ids)
            return jsonify({"status": "ok"})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @app.route("/api/reports/<report_id>/provenance/<finding_id>", methods=["GET"])
    def api_report_provenance(report_id: str, finding_id: str):
        try:
            svc = _get_report_service()
            chain = svc.get_provenance_chain(report_id, finding_id)
            return jsonify({"status": "ok", "provenance": chain})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 404

    @app.route("/api/investigations/<inv_id>/reports", methods=["GET"])
    def api_investigation_reports(inv_id: str):
        try:
            svc = _get_report_service()
            reports_data = svc.get_reports_for_investigation(inv_id)
            return jsonify({"status": "ok", "reports": reports_data})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    # ── Settings ──────────────────────────────────────────────────────────────
    @app.route("/settings")
    def settings():
        config = current_app.config["ORVIA_CONFIG"]
        return render_template(
            "settings.html",
            active_page="settings",
            page_title="Settings",
            db_path=str(config.DATABASE_PATH),
            app_version=config.VERSION,
        )

    # ── API: Workspace stats (JSON) ───────────────────────────────────────────
    @app.route("/api/stats")
    def api_stats():
        src_r, doc_r, top_r, con_r, inv_r = _get_repos()
        return jsonify(
            {
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stats": {
                    "sources": src_r.count(),
                    "documents": doc_r.count(),
                    "topics": top_r.count(),
                    "concepts": con_r.count(),
                    "investigations": inv_r.count(),
                },
            }
        )

    # ── Phase 11: Workspace Service Helper ───────────────────────────────────
    def _get_workspace_service():
        """Return ResearchWorkspaceService bound to current request DB."""
        from orvia.app.workspace.service import ResearchWorkspaceService
        from orvia.app.ui import get_db
        db = get_db()
        src_r, _, _, con_r, inv_r = _get_repos()
        shared_index = current_app.extensions.get("orvia_search_index")
        report_repo = None
        try:
            from orvia.app.reports.repository import ReportRepository
            report_repo = ReportRepository(db)
        except Exception:
            pass
        return ResearchWorkspaceService(
            db=db,
            source_repo=src_r,
            concept_repo=con_r,
            investigation_repo=inv_r,
            search_index=shared_index,
            report_repo=report_repo,
        )

    # ── Phase 11: Universal Search API ───────────────────────────────────────
    @app.route("/api/universal-search")
    def api_universal_search():
        query = request.args.get("q", "").strip()
        if not query or len(query) < 2:
            return jsonify({"status": "ok", "results": [], "groups": {}})
        svc = _get_workspace_service()
        results = svc.universal_search(query)
        groups: dict[str, list] = {}
        for r in results:
            groups.setdefault(r.item_type, []).append(r.to_dict())
        return jsonify({
            "status": "ok",
            "query": query,
            "results": [r.to_dict() for r in results],
            "groups": groups,
        })

    # ── Phase 11: Recent Activity API ────────────────────────────────────────
    @app.route("/api/recent-activity")
    def api_recent_activity():
        svc = _get_workspace_service()
        limit = min(int(request.args.get("limit", 20)), 100)
        activities = svc.get_recent_activities(limit=limit)
        return jsonify({
            "status": "ok",
            "activities": [a.to_dict() for a in activities],
        })

    # ── Phase 11: Continue Research API ──────────────────────────────────────
    @app.route("/api/continue-research")
    def api_continue_research():
        svc = _get_workspace_service()
        data = svc.get_continue_research()
        return jsonify({"status": "ok", **data})

    # ── Phase 11: Research Context API ───────────────────────────────────────
    @app.route("/api/context", methods=["GET"])
    def api_get_context():
        svc = _get_workspace_service()
        ctx = svc.get_context()
        return jsonify({"status": "ok", "context": ctx.to_dict()})

    @app.route("/api/context", methods=["POST"])
    def api_set_context():
        data = request.get_json(force=True, silent=True) or {}
        svc = _get_workspace_service()
        svc.set_context(
            investigation_id=data.get("investigation_id"),
            source_id=data.get("source_id"),
            concept_id=data.get("concept_id"),
            report_id=data.get("report_id"),
        )
        return jsonify({"status": "ok"})

    # ── Phase 11: Index Health API ────────────────────────────────────────────
    @app.route("/api/index-health")
    def api_index_health():
        svc = _get_workspace_service()
        health = svc.get_index_health()
        return jsonify({"status": "ok", "health": health.to_dict()})

    @app.route("/api/index-rebuild", methods=["POST"])
    def api_index_rebuild():
        try:
            search_svc = _get_search_service()
            count = search_svc.ensure_indexed(force=True)
            ws_svc = _get_workspace_service()
            ws_svc.record_activity(
                activity_type="index_rebuilt",
                entity_type="system",
                title="Search index rebuilt",
                description=f"{count} sources indexed.",
            )
            return jsonify({"status": "ok", "indexed": count, "message": f"Index rebuilt: {count} sources indexed."})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 500

    # ── Phase 11: Data Integrity API ─────────────────────────────────────────
    @app.route("/api/data-integrity")
    def api_data_integrity():
        svc = _get_workspace_service()
        report = svc.get_data_integrity()
        return jsonify({"status": "ok", "report": report.to_dict()})

    # ── Phase 11: Research Tensions API ──────────────────────────────────────
    @app.route("/api/investigations/<inv_id>/tensions")
    def api_investigation_tensions(inv_id: str):
        svc = _get_workspace_service()
        tensions = svc.detect_research_tensions(inv_id)
        return jsonify({"status": "ok", "tensions": [t.to_dict() for t in tensions]})

    # ── Phase 11: Source Comparison Page ─────────────────────────────────────
    @app.route("/compare-sources")
    def compare_sources_page():
        src_r, _, _, _, _ = _get_repos()
        source_a_id = request.args.get("a", "").strip()
        source_b_id = request.args.get("b", "").strip()
        all_sources = src_r.find_all_metadata(sort_by="newest")
        comparison = None
        source_a = None
        source_b = None
        if source_a_id and source_b_id:
            source_a = src_r.find_by_id(source_a_id)
            source_b = src_r.find_by_id(source_b_id)
            if source_a and source_b:
                ws_svc = _get_workspace_service()
                comparison = ws_svc.compare_sources(source_a_id, source_b_id)
        return render_template(
            "compare_sources.html",
            active_page="sources",
            page_title="Source Comparison",
            all_sources=all_sources,
            source_a=source_a,
            source_b=source_b,
            comparison=comparison,
        )

    # ── Phase 11: Research Timeline Page ─────────────────────────────────────
    @app.route("/timeline")
    def timeline():
        events: list[dict] = []
        try:
            from orvia.app.ui import get_db
            db = get_db()
            rows = db.fetchall(
                "SELECT id, title, 'source' as entity_type, created_at FROM sources ORDER BY created_at DESC LIMIT 50"
            )
            for r in rows:
                events.append({"entity_type": "source", "id": r["id"], "title": r["title"],
                               "url": f"/sources/{r['id']}", "timestamp": r["created_at"]})
            rows = db.fetchall(
                "SELECT id, title, 'investigation' as entity_type, created_at FROM investigations ORDER BY created_at DESC LIMIT 50"
            )
            for r in rows:
                events.append({"entity_type": "investigation", "id": r["id"], "title": r["title"],
                               "url": f"/investigations/{r['id']}", "timestamp": r["created_at"]})
            rows = db.fetchall(
                "SELECT id, statement as title, investigation_id, created_at FROM investigation_evidence ORDER BY created_at DESC LIMIT 30"
            )
            for r in rows:
                events.append({"entity_type": "evidence", "id": r["id"], "title": r["title"][:80],
                               "url": f"/investigations/{r['investigation_id']}?tab=evidence",
                               "timestamp": r["created_at"]})
            rows = db.fetchall(
                "SELECT id, title, investigation_id, created_at FROM investigation_findings ORDER BY created_at DESC LIMIT 30"
            )
            for r in rows:
                events.append({"entity_type": "finding", "id": r["id"], "title": r["title"],
                               "url": f"/investigations/{r['investigation_id']}?tab=findings",
                               "timestamp": r["created_at"]})
            try:
                rows = db.fetchall(
                    "SELECT id, title, created_at FROM reports ORDER BY created_at DESC LIMIT 20"
                )
                for r in rows:
                    events.append({"entity_type": "report", "id": r["id"], "title": r["title"],
                                   "url": f"/reports/{r['id']}", "timestamp": r["created_at"]})
            except Exception:
                pass
        except Exception as exc:
            logger.warning("Timeline query error: %s", exc)

        events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

        return render_template(
            "timeline.html",
            active_page="overview",
            page_title="Research Timeline",
            events=events[:100],
        )

    # ── Phase 11: Demo Data API ───────────────────────────────────────────────
    @app.route("/api/demo/load", methods=["GET", "POST"])
    def api_demo_load():
        svc = _get_workspace_service()
        result = svc.load_demo_data()
        return jsonify({"status": "ok", **result})

    @app.route("/api/demo/clear", methods=["POST"])
    def api_demo_clear():
        """Remove all sources tagged [DEMO] from the workspace."""
        try:
            src_r, _, _, _, _ = _get_repos()
            all_sources = src_r.find_all(limit=10000)
            demo_sources = [s for s in all_sources if s.title and "[DEMO]" in s.title]
            removed = 0
            for source in demo_sources:
                try:
                    src_r.delete(source.id)
                    removed += 1
                except Exception as exc:
                    logger.warning("Could not delete demo source %s: %s", source.id, exc)
            # Also rebuild index after clearing demo data
            try:
                from orvia.app.ui import get_db
                db = get_db()
                from orvia.app.search.engine import SearchEngine
                engine = SearchEngine(db)
                remaining = src_r.find_all(limit=10000)
                engine.rebuild_index(remaining)
            except Exception as exc:
                logger.warning("Could not rebuild index after demo clear: %s", exc)
            return jsonify({
                "status": "ok",
                "removed": removed,
                "message": f"Cleared {removed} demo source(s) from workspace.",
            })
        except Exception as exc:
            logger.exception("Demo clear failed: %s", exc)
            return jsonify({"status": "error", "error": str(exc)}), 500

    # ── Phase 12: Database Backup & Safety API ───────────────────────────────
    @app.route("/api/backup/create", methods=["POST"])
    def api_backup_create():
        try:
            from orvia.app.ui import get_db
            db = get_db()
            backup_path = db.create_backup()
            stat = backup_path.stat()
            size_kb = stat.st_size / 1024
            size_display = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.2f} MB"
            ws_svc = _get_workspace_service()
            ws_svc.record_activity(
                activity_type="backup_created",
                entity_type="system",
                title="Database backup created",
                description=f"Snapshot saved: {backup_path.name} ({size_display})",
            )
            return jsonify({
                "status": "ok",
                "filename": backup_path.name,
                "path": str(backup_path),
                "size_display": size_display,
                "message": f"Backup successfully created: {backup_path.name} ({size_display})",
            })
        except Exception as exc:
            logger.exception("Backup failed: %s", exc)
            return jsonify({"status": "error", "error": str(exc)}), 500

    @app.route("/api/backup/list", methods=["GET"])
    def api_backup_list():
        try:
            from orvia.app.ui import get_db
            db = get_db()
            backups = db.list_backups()
            return jsonify({"status": "ok", "backups": backups})
        except Exception as exc:
            return jsonify({"status": "error", "error": str(exc)}), 500

    # ── 404 handler ───────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html", active_page="", page_title="Not Found"), 404

    # ── 500 handler ───────────────────────────────────────────────────────────
    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Internal server error: %s", e)
        return render_template("500.html", active_page="", page_title="Error"), 500
