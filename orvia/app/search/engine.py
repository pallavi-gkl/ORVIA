"""
Search Engine Orchestration Subsystem for ORVIA Search Intelligence.
Coordinates QueryParser, SearchIndex, RankingEngine, SnippetHighlighter,
and SearchHistoryManager to deliver explainable, fast, research-grade retrieval.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.models.source import Source
from orvia.app.repositories.document_repository import DocumentRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.search.document_processor import DocumentProcessor
from orvia.app.search.highlighter import SnippetHighlighter
from orvia.app.search.history import SearchHistoryManager
from orvia.app.search.index import IndexEntry, Posting, SearchIndex
from orvia.app.search.query import ParsedQuery, QueryParser
from orvia.app.search.ranking import MatchExplanation, RankingEngine
from orvia.app.search.result import (
    SearchResult,
    SearchResultSet,
    TermExploration,
    ZeroResultSuggestion,
)
from orvia.app.search.tokenizer import SearchTokenizer

logger = logging.getLogger(__name__)


class SearchEngine:
    """
    Central search intelligence orchestrator for ORVIA.
    Provides multi-source indexing, BM25 scoring, exact phrase matching,
    term proximity calculation, search history tracking, and zero-result intelligence.
    """

    def __init__(
        self,
        source_repo: SourceRepository,
        document_repo: DocumentRepository,
        index: Optional[SearchIndex] = None,
        ranking_engine: Optional[RankingEngine] = None,
        highlighter: Optional[SnippetHighlighter] = None,
        query_parser: Optional[QueryParser] = None,
        history_manager: Optional[SearchHistoryManager] = None,
        db: Optional[DatabaseManager] = None,
    ) -> None:
        self.source_repo = source_repo
        self.document_repo = document_repo
        self.db = db or getattr(source_repo, "db", None)

        self.tokenizer = SearchTokenizer()
        self.index = index or SearchIndex(tokenizer=self.tokenizer, db=self.db)
        self.ranking = ranking_engine or RankingEngine()
        self.highlighter = highlighter or SnippetHighlighter()
        self.parser = query_parser or QueryParser(tokenizer=self.tokenizer)
        self.processor = DocumentProcessor(document_repo)

        if history_manager:
            self.history = history_manager
        elif self.db:
            self.history = SearchHistoryManager(self.db)
        else:
            self.history = None

        self._is_indexed = False

    def ensure_indexed(self, force: bool = False) -> int:
        """
        Ensure all sources and documents in SQLite are loaded into the search index.
        First tries restoring persisted postings from SQLite; if none exist or force=True,
        rebuilds from raw sources.
        """
        if self._is_indexed and not force:
            return self.index.total_docs

        start_t = time.perf_counter()
        sources = self.source_repo.find_all(limit=2000)
        sources_map = {src.id: src for src in sources}

        # 1. Try restoring from SQLite postings if not forced
        if not force and self.db:
            loaded = self.index.load_from_sqlite(sources_map)
            if loaded and self.index.total_docs >= len(sources):
                self._is_indexed = True
                elapsed = (time.perf_counter() - start_t) * 1000
                logger.info("SearchEngine restored index from SQLite in %.2f ms", elapsed)
                return self.index.total_docs

        # 2. Otherwise index all sources and child documents from scratch
        self.index.clear()
        total_items = 0

        for src in sources:
            # Index source
            self.index.add_document(
                id=src.id,
                title=src.title,
                content=src.content or "",
                source_id=src.id,
                filename=src.filename,
                file_type=src.file_type or "txt",
                word_count=src.word_count,
                tags=["origin:source", f"format:{src.file_type or 'txt'}"],
                created_at=src.imported_at or src.created_at.isoformat(),
            )
            total_items += 1

            # Check or extract child documents
            child_docs = self.document_repo.find_by_source(src.id)
            if not child_docs and src.content:
                child_docs = self.processor.process_source(src)

            for doc in child_docs:
                self.index.add_document(
                    id=doc.id,
                    title=doc.title,
                    content=doc.content,
                    source_id=doc.source_id,
                    filename=src.filename,
                    file_type=src.file_type or "txt",
                    word_count=doc.word_count,
                    tags=doc.tags,
                    created_at=doc.created_at.isoformat(),
                    summary=doc.summary,
                )
                total_items += 1

        # Persist to SQLite
        if self.db:
            self.index.save_to_sqlite()

        self._is_indexed = True
        elapsed = (time.perf_counter() - start_t) * 1000
        logger.info("SearchEngine indexed %d items in %.2f ms", total_items, elapsed)
        return total_items

    def index_source(self, source: Source) -> None:
        """
        Add a freshly imported or modified Source and its extracted Documents to the index.
        """
        self.ensure_indexed()

        # Remove existing index entries for this source
        self.index.remove_by_source_id(source.id)

        # Index source
        self.index.add_document(
            id=source.id,
            title=source.title,
            content=source.content or "",
            source_id=source.id,
            filename=source.filename,
            file_type=source.file_type or "txt",
            word_count=source.word_count,
            tags=["origin:source", f"format:{source.file_type or 'txt'}"],
            created_at=source.imported_at or source.created_at.isoformat(),
        )

        # Process and index child documents
        child_docs = self.processor.process_source(source)
        for doc in child_docs:
            self.index.add_document(
                id=doc.id,
                title=doc.title,
                content=doc.content,
                source_id=doc.source_id,
                filename=source.filename,
                file_type=source.file_type or "txt",
                word_count=doc.word_count,
                tags=doc.tags,
                created_at=doc.created_at.isoformat(),
                summary=doc.summary,
            )

        if self.db:
            self.index.save_to_sqlite()

    def update_source(self, source: Source) -> None:
        """Alias for updating an indexed source."""
        self.index_source(source)

    def remove_source(self, source_id: str) -> None:
        """
        Remove a source and all associated documents from the index, SQLite postings, and repository.
        """
        self.ensure_indexed()

        # Remove from in-memory index & SQLite search_postings
        self.index.remove_by_source_id(source_id)

        # Remove child documents from repository
        child_docs = self.document_repo.find_by_source(source_id)
        for doc in child_docs:
            self.document_repo.delete(doc.id)

        if self.db:
            self.index.save_to_sqlite()

    def rebuild_index(self) -> int:
        """Force a complete rebuild and re-synchronization of the search index."""
        return self.ensure_indexed(force=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Search Execution
    # ──────────────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        filter_type: str = "all",
        sort_by: str = "relevance",
        limit: int = 25,
        offset: int = 0,
    ) -> SearchResultSet:
        """
        Execute an explainable ranked search across all sources and documents.
        """
        self.ensure_indexed()
        t0 = time.perf_counter()

        clean_query = (query or "").strip()
        total_sources_in_workspace = self.source_repo.count()

        if not clean_query:
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            return SearchResultSet(
                query="",
                total_hits=0,
                duration_ms=duration_ms,
                results=[],
                filter_type=filter_type,
                sort_by=sort_by,
                total_sources_in_workspace=total_sources_in_workspace,
            )

        parsed: ParsedQuery = self.parser.parse(clean_query)

        # Determine target file type filter
        active_filter_type = filter_type.lower()
        if "format" in parsed.field_filters:
            active_filter_type = parsed.field_filters["format"]

        # Collect candidate document IDs that match at least one query term or phrase
        candidate_docs: set[str] = set()
        search_terms = parsed.all_search_terms

        for stem in search_terms:
            if stem in self.index.postings:
                candidate_docs.update(self.index.postings[stem].keys())

        # Discard candidate docs containing excluded terms (-term)
        for neg_stem in parsed.excluded_terms:
            if neg_stem in self.index.postings:
                excluded_docs = set(self.index.postings[neg_stem].keys())
                candidate_docs.difference_update(excluded_docs)

        # Score and rank candidates
        scored_results: list[SearchResult] = []
        avg_len = self.index.avg_doc_len

        for doc_id in candidate_docs:
            entry = self.index.entries.get(doc_id)
            if not entry:
                continue

            # Apply file type filter if specified
            if active_filter_type != "all" and entry.file_type.lower() != active_filter_type:
                continue

            doc_len = self.index.doc_lengths.get(doc_id, 0)
            score = 0.0
            matched_terms_for_doc: list[str] = []
            term_occurrences = 0
            title_matches = 0
            doc_positions_map: dict[str, list[int]] = {}

            # 1. BM25 term scoring & title match detection
            for term in search_terms:
                if term in self.index.postings and doc_id in self.index.postings[term]:
                    p: Posting = self.index.postings[term][doc_id]
                    idf = self.index.idf(term)
                    tf_comp = self.ranking.calculate_bm25_tf_component(
                        tf=p.term_frequency,
                        doc_len=doc_len,
                        avg_doc_len=avg_len,
                        in_title=p.in_title,
                        in_tags=p.in_tags,
                    )
                    score += idf * tf_comp
                    matched_terms_for_doc.append(term)
                    term_occurrences += p.term_frequency
                    if p.in_title:
                        title_matches += 1
                    if p.positions:
                        doc_positions_map[term] = p.positions

            if not matched_terms_for_doc and not parsed.phrases:
                continue

            # 2. Exact phrase matching
            phrase_matches = 0
            for phrase in parsed.phrases:
                matches_found = self.ranking.detect_phrase_matches(phrase, doc_positions_map)
                if matches_found > 0:
                    phrase_matches += matches_found
                    score += self.ranking.phrase_boost * matches_found * 2.0
                elif len(parsed.phrases) == 1 and not parsed.terms:
                    # Query is solely an exact phrase and this doc didn't match the phrase
                    score = 0.0

            if len(parsed.phrases) > 0 and not parsed.terms and phrase_matches == 0:
                # Quoted phrase was required but didn't match sequentially
                continue

            # 3. Positional proximity bonus (when >= 2 terms present)
            proximity_bonus = 0.0
            if len(doc_positions_map) >= 2:
                proximity_bonus, _ = self.ranking.calculate_proximity(doc_positions_map)
                score += proximity_bonus

            # Build explainable match reason
            explanation: MatchExplanation = self.ranking.build_explanation(
                score=score,
                term_occurrences=term_occurrences,
                title_matches=title_matches,
                phrase_matches=phrase_matches,
                proximity_bonus=proximity_bonus,
                matched_terms=matched_terms_for_doc,
            )

            # Generate contextual snippet with highlight marks
            snippet = self.highlighter.generate_snippet(
                content=entry.content,
                query_terms=parsed.raw_terms or parsed.raw_phrases or matched_terms_for_doc,
                window_chars=220,
            )

            # Resolve parent source title
            parent_title = entry.title
            if entry.source_id and entry.source_id in self.index.entries:
                parent_title = self.index.entries[entry.source_id].title

            # Collect positions
            all_positions = []
            for pos_list in doc_positions_map.values():
                all_positions.extend(pos_list)

            scored_results.append(
                SearchResult(
                    source_id=entry.source_id or entry.id,
                    source_title=entry.title,
                    file_type=entry.file_type,
                    score=explanation.score,
                    relevance_label=explanation.relevance_label,
                    matched_terms=matched_terms_for_doc,
                    match_count=term_occurrences,
                    snippet=snippet,
                    match_positions=sorted(all_positions),
                    match_reason=explanation.summary_text,
                    word_count=entry.word_count,
                    created_at=entry.created_at[:10] if entry.created_at else "",
                    filename=entry.filename,
                    tags=entry.tags,
                    source_metadata=getattr(entry, "metadata", {}) or {},
                )
            )

        # Sorting
        if sort_by == "newest":
            scored_results.sort(key=lambda r: r.created_at, reverse=True)
        elif sort_by == "oldest":
            scored_results.sort(key=lambda r: r.created_at)
        elif sort_by == "largest":
            scored_results.sort(key=lambda r: r.word_count, reverse=True)
        else:
            # Default: relevance
            scored_results.sort(key=lambda r: r.score, reverse=True)

        total_hits = len(scored_results)
        paginated_results = scored_results[offset : offset + limit]

        # 4. Term Exploration (Section 22)
        term_exploration = None
        if len(parsed.terms) == 1 and not parsed.phrases and hasattr(self.index, "get_term_stats"):
            single_term = parsed.raw_terms[0] if parsed.raw_terms else parsed.terms[0]
            src_count, occurrences = self.index.get_term_stats(single_term)
            if occurrences > 0:
                related = self.index.get_related_terms(single_term, limit=5) if hasattr(self.index, "get_related_terms") else []
                term_exploration = TermExploration(
                    term=single_term,
                    source_count=src_count,
                    total_occurrences=occurrences,
                    related_terms=related,
                )

        # 5. Zero-Result Intelligence (Section 21)
        zero_result_suggestion = None
        if total_hits == 0 and hasattr(self.index, "get_zero_result_suggestions"):
            suggestions = self.index.get_zero_result_suggestions(clean_query, limit=4)
            if suggestions:
                zero_result_suggestion = ZeroResultSuggestion(
                    query=clean_query,
                    suggestions=suggestions,
                    message="No direct matches found. Try searching for related concepts:",
                )

        duration_ms = round((time.perf_counter() - t0) * 1000, 2)

        # 6. Record search history (Section 18)
        if self.history:
            self.history.record_search(clean_query, total_hits)

        return SearchResultSet(
            query=clean_query,
            total_hits=total_hits,
            duration_ms=duration_ms,
            results=paginated_results,
            term_exploration=term_exploration,
            zero_result_suggestion=zero_result_suggestion,
            filter_type=active_filter_type,
            sort_by=sort_by,
            total_sources_in_workspace=total_sources_in_workspace,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # History & Analytics Helpers (Section 18, 19, 20)
    # ──────────────────────────────────────────────────────────────────────────

    def get_search_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve recent searches from local history log."""
        if not self.history:
            return []
        return self.history.get_recent_searches(limit)

    def get_popular_searches(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve popular search queries from actual history."""
        if not self.history:
            return []
        return self.history.get_popular_searches(limit)

    def get_search_analytics(self) -> dict[str, Any]:
        """Compile deterministic search insights for research gaps."""
        if not self.history:
            return {"recent": [], "popular": [], "zero_results": []}
        return {
            "recent": self.history.get_recent_searches(10),
            "popular": self.history.get_popular_searches(5),
            "zero_results": self.history.get_zero_result_queries(5),
        }

    def clear_search_history(self) -> bool:
        """Clear local search query history."""
        if not self.history:
            return False
        return self.history.clear_history()


# Backward compatibility alias
SearchService = SearchEngine
