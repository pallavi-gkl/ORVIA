"""
Query Processing & Parsing Subsystem for ORVIA Search Intelligence.
Provides deterministic parsing of user queries into single terms, multi-term conjunctions,
exact quoted phrases, boolean exclusions, and metadata filters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from orvia.app.search.tokenizer import SearchTokenizer


@dataclass
class ParsedQuery:
    """Structured representation of a parsed search query."""
    raw_query: str
    terms: list[str] = field(default_factory=list)              # Stemmed query terms
    raw_terms: list[str] = field(default_factory=list)          # Original unstemmed terms
    phrases: list[list[str]] = field(default_factory=list)      # Exact phrases (stemmed tokens)
    raw_phrases: list[str] = field(default_factory=list)        # Original quoted phrases
    excluded_terms: list[str] = field(default_factory=list)     # Stemmed terms preceded by '-'
    raw_excluded: list[str] = field(default_factory=list)       # Original unstemmed excluded terms
    field_filters: dict[str, str] = field(default_factory=dict) # e.g. {'format': 'csv'}
    is_empty: bool = False

    @property
    def all_search_terms(self) -> list[str]:
        """All search terms including phrase terms (stemmed)."""
        combined = list(self.terms)
        for phrase in self.phrases:
            for term in phrase:
                if term not in combined:
                    combined.append(term)
        return combined


class QueryParser:
    """
    Deterministic query parser extracting quoted phrases, negated terms,
    field filters, and free-text search terms.
    """

    PHRASE_REGEX = re.compile(r'"([^"]+)"')
    FILTER_REGEX = re.compile(r'\b(format|type|tag):([a-zA-Z0-9_\-]+)\b', re.IGNORECASE)
    EXCLUDE_REGEX = re.compile(r'(?:^|\s)-([a-zA-Z0-9_\-]+)\b')

    def __init__(self, tokenizer: Optional[SearchTokenizer] = None) -> None:
        self.tokenizer = tokenizer or SearchTokenizer()

    def parse(self, raw_query: str) -> ParsedQuery:
        """
        Parse raw user query into structured ParsedQuery components.
        """
        clean_text = (raw_query or "").strip()
        if not clean_text:
            return ParsedQuery(raw_query="", is_empty=True)

        working_query = clean_text

        # 1. Extract exact phrases in quotes: "self attention"
        raw_phrases: list[str] = []
        stemmed_phrases: list[list[str]] = []
        for match in self.PHRASE_REGEX.finditer(working_query):
            phrase_str = match.group(1).strip()
            if phrase_str:
                raw_phrases.append(phrase_str)
                # Tokenize phrase words without removing stop words so exact phrases like "to be or not to be" work
                phrase_tokens = self.tokenizer.tokenize(phrase_str, remove_stopwords=False, stem=True)
                if phrase_tokens:
                    stemmed_phrases.append([t.stem for t in phrase_tokens])
        working_query = self.PHRASE_REGEX.sub(" ", working_query)

        # 2. Extract field filters: format:csv or type:txt
        field_filters: dict[str, str] = {}
        for match in self.FILTER_REGEX.finditer(working_query):
            field_name = match.group(1).lower()
            field_val = match.group(2).lower()
            if field_name == "type":
                field_name = "format"
            field_filters[field_name] = field_val
        working_query = self.FILTER_REGEX.sub(" ", working_query)

        # 3. Extract boolean exclusions: -python
        excluded_terms: list[str] = []
        raw_excluded: list[str] = []
        for match in self.EXCLUDE_REGEX.finditer(working_query):
            neg_term = match.group(1).lower()
            raw_excluded.append(neg_term)
            stemmed_neg = self.tokenizer.stemmer.stem(neg_term)
            excluded_terms.append(stemmed_neg)
        working_query = self.EXCLUDE_REGEX.sub(" ", working_query)

        # 4. Remaining free text terms
        tokens = self.tokenizer.tokenize(working_query, remove_stopwords=True, stem=True)
        stemmed_terms = [t.stem for t in tokens]
        raw_terms = [t.text for t in tokens]

        is_empty = not stemmed_terms and not stemmed_phrases and not field_filters

        return ParsedQuery(
            raw_query=clean_text,
            terms=stemmed_terms,
            raw_terms=raw_terms,
            phrases=stemmed_phrases,
            raw_phrases=raw_phrases,
            excluded_terms=excluded_terms,
            raw_excluded=raw_excluded,
            field_filters=field_filters,
            is_empty=is_empty,
        )
