"""
Search Result Models & Data Transfer Objects for ORVIA Search Intelligence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SearchResult:
    """
    Rich structured search result model for research display.
    """
    source_id: str
    source_title: str
    file_type: str
    score: float
    relevance_label: str                                   # 'High relevance', 'Strong match', etc.
    matched_terms: list[str] = field(default_factory=list) # List of matched search terms
    match_count: int = 0                                   # Total term occurrences in document
    snippet: str = ""                                      # Contextual HTML snippet with <mark> tags
    match_positions: list[int] = field(default_factory=list) # Matched token positions
    match_reason: str = ""                                 # Human-readable explanation
    word_count: int = 0
    created_at: str = ""
    filename: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)

    # Backward compatibility alias for id
    @property
    def id(self) -> str:
        return self.source_id

    @property
    def title(self) -> str:
        return self.source_title


@dataclass
class TermExploration:
    """
    Exploration metadata for a queried concept or term based on collection co-occurrence.
    """
    term: str
    source_count: int
    total_occurrences: int
    related_terms: list[dict[str, Any]] = field(default_factory=list)  # list of {'term': str, 'cooccurrences': int}


@dataclass
class ZeroResultSuggestion:
    """
    Deterministic vocabulary-derived query suggestions when 0 direct matches are found.
    """
    query: str
    suggestions: list[str] = field(default_factory=list)
    message: str = "No direct matches found."


@dataclass
class SearchResultSet:
    """
    Comprehensive search response containing scored items, query metadata,
    term exploration signals, zero-result intelligence, and search latency.
    """
    query: str
    total_hits: int
    duration_ms: float
    results: list[SearchResult] = field(default_factory=list)
    term_exploration: Optional[TermExploration] = None
    zero_result_suggestion: Optional[ZeroResultSuggestion] = None
    filter_type: str = "all"
    sort_by: str = "relevance"
    total_sources_in_workspace: int = 0
