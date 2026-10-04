"""
ORVIA Search Intelligence Subsystem.
Modular, explainable, pure-Python search subsystem featuring:
- Query processing and parsing (QueryParser, ParsedQuery)
- Inverted indexing with positional postings (SearchIndex, InvertedIndex)
- Explainable BM25 and proximity ranking (RankingEngine, MatchExplanation)
- Contextual snippet highlighting (SnippetHighlighter)
- Search history & analytics (SearchHistoryManager)
- Zero-result intelligence & deterministic vocabulary suggestions (ZeroResultSuggestion)
- Term exploration & co-occurrence (TermExploration)
- Unified orchestrator (SearchEngine, SearchService)
"""
from orvia.app.search.document_processor import DocumentProcessor
from orvia.app.search.engine import SearchEngine, SearchService
from orvia.app.search.highlighter import SnippetHighlighter
from orvia.app.search.history import SearchHistoryManager
from orvia.app.search.index import IndexEntry, InvertedIndex, Posting, SearchIndex
from orvia.app.search.query import ParsedQuery, QueryParser
from orvia.app.search.ranking import MatchExplanation, RankingEngine
from orvia.app.search.result import (
    SearchResult,
    SearchResultSet,
    TermExploration,
    ZeroResultSuggestion,
)
from orvia.app.search.tokenizer import PorterStemmer, SearchTokenizer, Token, STOP_WORDS

__all__ = [
    "DocumentProcessor",
    "IndexEntry",
    "InvertedIndex",
    "MatchExplanation",
    "ParsedQuery",
    "PorterStemmer",
    "Posting",
    "QueryParser",
    "RankingEngine",
    "SearchEngine",
    "SearchHistoryManager",
    "SearchIndex",
    "SearchResult",
    "SearchResultSet",
    "SearchService",
    "SearchTokenizer",
    "SnippetHighlighter",
    "STOP_WORDS",
    "TermExploration",
    "Token",
    "ZeroResultSuggestion",
]
