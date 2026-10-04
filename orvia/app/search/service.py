"""
SearchService compatibility layer.
Re-exports SearchEngine as SearchService and SearchResult/SearchResultSet from engine and result modules.
"""
from orvia.app.search.engine import SearchEngine, SearchService
from orvia.app.search.result import (
    SearchResult,
    SearchResultSet,
    TermExploration,
    ZeroResultSuggestion,
)

__all__ = [
    "SearchEngine",
    "SearchService",
    "SearchResult",
    "SearchResultSet",
    "TermExploration",
    "ZeroResultSuggestion",
]
