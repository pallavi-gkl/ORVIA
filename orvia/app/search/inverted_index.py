"""
Inverted Index & BM25 Scoring Engine for ORVIA.
Implements an in-memory inverted postings index with positional tracking,
phrase querying, boolean operators, field boosting, and Robertson-Spärck Jones BM25 ranking.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from orvia.app.search.tokenizer import SearchTokenizer, Token


@dataclass
class Posting:
    """A single posting entry for a term inside a document."""
    doc_id: str
    term_frequency: int
    positions: list[int] = field(default_factory=list)
    in_title: bool = False
    in_tags: bool = False


@dataclass
class IndexEntry:
    """Metadata for an indexed research document or source."""
    id: str
    title: str
    content: str
    source_id: Optional[str] = None
    filename: Optional[str] = None
    file_type: str = "txt"
    word_count: int = 0
    token_count: int = 0
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    summary: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoredHit:
    """A scored search hit returned from the index."""
    entry: IndexEntry
    score: float
    matched_terms: list[str] = field(default_factory=list)
    phrase_matched: bool = False


class InvertedIndex:
    """
    Inverted Index with positional postings, BM25 scoring, and rich query parsing.
    """

    def __init__(
        self,
        tokenizer: Optional[SearchTokenizer] = None,
        k1: float = 1.5,
        b: float = 0.75,
        title_boost: float = 2.5,
        tag_boost: float = 1.8,
        phrase_boost: float = 3.0,
    ) -> None:
        self.tokenizer = tokenizer or SearchTokenizer()
        self.k1 = k1
        self.b = b
        self.title_boost = title_boost
        self.tag_boost = tag_boost
        self.phrase_boost = phrase_boost

        # postings: term -> {doc_id: Posting}
        self.postings: dict[str, dict[str, Posting]] = {}
        # entries: doc_id -> IndexEntry
        self.entries: dict[str, IndexEntry] = {}
        # doc_lengths: doc_id -> token_count
        self.doc_lengths: dict[str, int] = {}
        self.total_tokens: int = 0

    @property
    def total_docs(self) -> int:
        return len(self.entries)

    @property
    def avg_doc_length(self) -> float:
        if not self.entries:
            return 0.0
        return self.total_tokens / len(self.entries)

    @property
    def avg_doc_len(self) -> float:
        return self.avg_doc_length

    def add_document(
        self,
        id: str,
        title: str,
        content: str,
        source_id: Optional[str] = None,
        filename: Optional[str] = None,
        file_type: str = "txt",
        word_count: int = 0,
        tags: Optional[list[str]] = None,
        created_at: str = "",
        summary: Optional[str] = None,
    ) -> None:
        """Index or re-index a research item."""
        if id in self.entries:
            self.remove_document(id)

        tag_list = tags or []
        body_tokens = self.tokenizer.tokenize(content, remove_stopwords=True, stem=True)
        title_tokens = self.tokenizer.tokenize(title, remove_stopwords=False, stem=True)
        tag_tokens = self.tokenizer.tokenize(" ".join(tag_list), remove_stopwords=False, stem=True)

        token_count = len(body_tokens) + len(title_tokens)
        entry = IndexEntry(
            id=id,
            title=title,
            content=content,
            source_id=source_id,
            filename=filename,
            file_type=file_type.lower(),
            word_count=word_count or len(content.split()),
            token_count=token_count,
            tags=tag_list,
            created_at=created_at,
            summary=summary,
        )

        self.entries[id] = entry
        self.doc_lengths[id] = token_count
        self.total_tokens += token_count

        # Build term mappings for this doc
        doc_term_map: dict[str, Posting] = {}

        # 1. Process body tokens
        for tok in body_tokens:
            stem = tok.stem
            if stem not in doc_term_map:
                doc_term_map[stem] = Posting(
                    doc_id=id,
                    term_frequency=1,
                    positions=[tok.position],
                    in_title=False,
                    in_tags=False,
                )
            else:
                p = doc_term_map[stem]
                p.term_frequency += 1
                p.positions.append(tok.position)

        # 2. Process title tokens
        for tok in title_tokens:
            stem = tok.stem
            if stem not in doc_term_map:
                doc_term_map[stem] = Posting(
                    doc_id=id,
                    term_frequency=1,
                    positions=[],
                    in_title=True,
                    in_tags=False,
                )
            else:
                doc_term_map[stem].in_title = True

        # 3. Process tag tokens
        for tok in tag_tokens:
            stem = tok.stem
            if stem not in doc_term_map:
                doc_term_map[stem] = Posting(
                    doc_id=id,
                    term_frequency=1,
                    positions=[],
                    in_title=False,
                    in_tags=True,
                )
            else:
                doc_term_map[stem].in_tags = True

        # Commit to global postings
        for stem, posting in doc_term_map.items():
            if stem not in self.postings:
                self.postings[stem] = {}
            self.postings[stem][id] = posting

    def remove_document(self, id: str) -> None:
        """Remove a document from postings and registry."""
        if id not in self.entries:
            return

        old_len = self.doc_lengths.pop(id, 0)
        self.total_tokens = max(0, self.total_tokens - old_len)
        del self.entries[id]

        # Clean from postings
        empty_stems = []
        for stem, doc_map in self.postings.items():
            if id in doc_map:
                del doc_map[id]
                if not doc_map:
                    empty_stems.append(stem)

        for stem in empty_stems:
            del self.postings[stem]

    def remove_by_source_id(self, source_id: str) -> None:
        """Remove a source document and all entries associated with that source_id."""
        to_remove = [
            doc_id
            for doc_id, entry in list(self.entries.items())
            if doc_id == source_id or entry.source_id == source_id
        ]
        for doc_id in to_remove:
            self.remove_document(doc_id)

    def clear(self) -> None:
        """Reset the in-memory index entirely."""
        self.postings.clear()
        self.entries.clear()
        self.doc_lengths.clear()
        self.total_tokens = 0

    def idf(self, term: str) -> float:
        """Calculate Robertson-Spärck Jones Inverse Document Frequency with smoothing."""
        doc_count = len(self.postings.get(term, {}))
        if doc_count == 0:
            return 0.0
        n = doc_count
        N = self.total_docs
        # Standard BM25 IDF: ln(1 + (N - n + 0.5) / (n + 0.5))
        return math.log(1.0 + (N - n + 0.5) / (n + 0.5))

    def _parse_query_components(self, raw_query: str) -> dict[str, Any]:
        """
        Parse raw query string into phrases, excluded terms, field filters, and general terms.
        Examples:
          "flash attention" -python format:csv scalable
        """
        clean = raw_query.strip()
        phrases: list[list[str]] = []
        excluded_terms: list[str] = []
        field_filters: dict[str, str] = {}
        general_terms: list[str] = []

        # 1. Extract exact phrases in quotes: "phrase text"
        phrase_matches = re.findall(r'"([^"]+)"', clean)
        for p in phrase_matches:
            toks = [t.stem for t in self.tokenizer.tokenize(p, remove_stopwords=False, stem=True)]
            if toks:
                phrases.append(toks)
        # Strip extracted phrases from query
        clean = re.sub(r'"[^"]+"', " ", clean)

        # 2. Extract tokens and prefixes
        raw_words = clean.split()
        for w in raw_words:
            # Field filters: e.g. format:txt, type:json, tag:rag
            if ":" in w and not w.startswith("-"):
                parts = w.split(":", 1)
                f_name = parts[0].lower().strip()
                f_val = parts[1].lower().strip()
                field_filters[f_name] = f_val
                continue

            # Excluded terms: e.g. -python, -cuda
            if w.startswith("-") and len(w) > 1:
                stems = [t.stem for t in self.tokenizer.tokenize(w[1:], remove_stopwords=False, stem=True)]
                excluded_terms.extend(stems)
                continue

            # Regular terms
            stems = [t.stem for t in self.tokenizer.tokenize(w, remove_stopwords=True, stem=True)]
            general_terms.extend(stems)

        return {
            "phrases": phrases,
            "excluded_terms": set(excluded_terms),
            "field_filters": field_filters,
            "general_terms": list(dict.fromkeys(general_terms)),  # deduplicate preserving order
        }

    def _matches_phrase(self, doc_id: str, phrase_stems: list[str]) -> bool:
        """Check if consecutive tokens in a phrase appear consecutively in document positions."""
        if not phrase_stems:
            return True
        first_stem = phrase_stems[0]
        first_post = self.postings.get(first_stem, {}).get(doc_id)
        if not first_post or not first_post.positions:
            return False

        # For each occurrence of the first word, check if subsequent words follow at pos + offset
        for start_pos in first_post.positions:
            match = True
            for offset, next_stem in enumerate(phrase_stems[1:], start=1):
                next_post = self.postings.get(next_stem, {}).get(doc_id)
                if not next_post or (start_pos + offset) not in next_post.positions:
                    match = False
                    break
            if match:
                return True
        return False

    def search(
        self,
        query: str,
        filter_type: Optional[str] = None,
        sort_by: str = "relevance",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ScoredHit], int]:
        """
        Execute ranked BM25 search across the inverted index.
        Returns (list[ScoredHit], total_hit_count).
        """
        parsed = self._parse_query_components(query)
        general_terms = parsed["general_terms"]
        phrases = parsed["phrases"]
        excluded = parsed["excluded_terms"]
        field_filters = parsed["field_filters"]

        all_query_stems = list(general_terms)
        for p in phrases:
            all_query_stems.extend(p)
        all_query_stems = list(dict.fromkeys(all_query_stems))

        if not all_query_stems and not field_filters:
            # Empty query: return all matching filter_type sorted by newest
            candidates = list(self.entries.values())
            if filter_type and filter_type.lower() != "all":
                candidates = [c for c in candidates if c.file_type == filter_type.lower()]
            hits = [ScoredHit(entry=c, score=1.0) for c in candidates]
            # Default sort newest
            hits.sort(key=lambda h: h.entry.created_at, reverse=True)
            total = len(hits)
            return hits[offset : offset + limit], total

        # Find candidate documents containing at least one positive term or matching field filter
        candidate_ids: set[str] = set()

        if all_query_stems:
            for term in all_query_stems:
                if term in self.postings:
                    candidate_ids.update(self.postings[term].keys())
        elif field_filters:
            candidate_ids = set(self.entries.keys())

        # Filter out excluded documents
        for ex in excluded:
            if ex in self.postings:
                candidate_ids.difference_update(self.postings[ex].keys())

        # Apply format filters (e.g. filter_type parameter or format: field)
        target_type = field_filters.get("format") or field_filters.get("type") or filter_type
        if target_type and target_type.lower() != "all":
            candidate_ids = {
                did for did in candidate_ids
                if self.entries[did].file_type == target_type.lower()
            }

        # Apply tag filter: tag:...
        if "tag" in field_filters:
            req_tag = field_filters["tag"].lower()
            candidate_ids = {
                did for did in candidate_ids
                if any(req_tag in t.lower() for t in self.entries[did].tags)
            }

        # Apply phrase filters (if phrases were specified, must contain the phrase)
        for phrase in phrases:
            candidate_ids = {
                did for did in candidate_ids
                if self._matches_phrase(did, phrase)
            }

        if not candidate_ids:
            return [], 0

        # Score candidates with BM25
        avgdl = self.avg_doc_length or 1.0
        scored_hits: list[ScoredHit] = []

        for doc_id in candidate_ids:
            entry = self.entries[doc_id]
            doc_len = self.doc_lengths.get(doc_id, 1)
            score = 0.0
            matched_terms: list[str] = []
            has_phrase_match = False

            for term in all_query_stems:
                post = self.postings.get(term, {}).get(doc_id)
                if not post:
                    continue

                matched_terms.append(term)
                tf = post.term_frequency
                idf_val = self.idf(term)

                # Standard BM25 calculation
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / avgdl))
                term_score = idf_val * (numerator / denominator)

                # Title boost
                if post.in_title:
                    term_score *= self.title_boost

                # Tag boost
                if post.in_tags:
                    term_score *= self.tag_boost

                score += term_score

            # Phrase bonus
            for phrase in phrases:
                if self._matches_phrase(doc_id, phrase):
                    score *= self.phrase_boost
                    has_phrase_match = True

            scored_hits.append(
                ScoredHit(
                    entry=entry,
                    score=round(score, 3),
                    matched_terms=matched_terms,
                    phrase_matched=has_phrase_match,
                )
            )

        # Sort results
        if sort_by == "newest":
            scored_hits.sort(key=lambda h: h.entry.created_at, reverse=True)
        elif sort_by == "oldest":
            scored_hits.sort(key=lambda h: h.entry.created_at)
        elif sort_by == "title":
            scored_hits.sort(key=lambda h: h.entry.title.lower())
        else:
            # Default: relevance descending, then newest
            scored_hits.sort(key=lambda h: (h.score, h.entry.created_at), reverse=True)

        total_hits = len(scored_hits)
        paginated = scored_hits[offset : offset + limit]
        return paginated, total_hits
