"""
Inverted Index & Local Persistence Subsystem for ORVIA Search Intelligence.
Provides in-memory fast retrieval, positional tracking, co-occurrence tracking,
zero-result vocabulary suggestions, and SQLite persistence.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.models.source import Source
from orvia.app.search.tokenizer import SearchTokenizer, Token

logger = logging.getLogger(__name__)


@dataclass
class ScoredHit:
    """A scored search hit returned from the index."""
    entry: IndexEntry
    score: float
    matched_terms: list[str] = field(default_factory=list)
    phrase_matched: bool = False


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
    """Metadata for an indexed research source or document."""
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


class SearchIndex:
    """
    High-performance inverted index with positional tracking, co-occurrence graph,
    vocabulary-based fuzzy zero-result suggestions, and SQLite persistence.
    """

    def __init__(
        self,
        tokenizer: Optional[SearchTokenizer] = None,
        db: Optional[DatabaseManager] = None,
        k1: float = 1.5,
        b: float = 0.75,
        title_boost: float = 2.5,
        tag_boost: float = 1.5,
        phrase_boost: float = 3.0,
    ) -> None:
        self.tokenizer = tokenizer or SearchTokenizer()
        self.db = db
        self.k1 = k1
        self.b = b
        self.title_boost = title_boost
        self.tag_boost = tag_boost
        self.phrase_boost = phrase_boost

        # Core index structures
        # postings[stem][doc_id] -> Posting
        self.postings: dict[str, dict[str, Posting]] = defaultdict(dict)
        # entries[doc_id] -> IndexEntry
        self.entries: dict[str, IndexEntry] = {}
        # doc_lengths[doc_id] -> int
        self.doc_lengths: dict[str, int] = {}
        # total_tokens across collection
        self.total_tokens: int = 0

        # Co-occurrence tracking: (term_a, term_b) -> count
        # where term_a < term_b alphabetically
        self.cooccurrences: dict[tuple[str, str], int] = defaultdict(int)

        # Distinct vocabulary stems set for zero-result suggestions
        self.vocabulary: set[str] = set()

    @property
    def total_docs(self) -> int:
        return len(self.entries)

    @property
    def avg_doc_len(self) -> float:
        if self.total_docs == 0:
            return 0.0
        return self.total_tokens / self.total_docs

    @property
    def avg_doc_length(self) -> float:
        return self.avg_doc_len

    # ──────────────────────────────────────────────────────────────────────────
    # Document / Source Indexing
    # ──────────────────────────────────────────────────────────────────────────

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
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Index or re-index a research item (Source or Document) into postings.
        """
        if id in self.entries:
            self.remove_document(id)

        tag_list = tags or []
        body_tokens = self.tokenizer.tokenize(content, remove_stopwords=True, stem=True)
        title_tokens = self.tokenizer.tokenize(title, remove_stopwords=False, stem=True)
        tag_tokens = self.tokenizer.tokenize(" ".join(tag_list), remove_stopwords=False, stem=True)

        token_len = len(body_tokens) + len(title_tokens)
        self.doc_lengths[id] = token_len
        self.total_tokens += token_len

        entry = IndexEntry(
            id=id,
            title=title,
            content=content,
            source_id=source_id or id,
            filename=filename,
            file_type=file_type,
            word_count=word_count or len(content.split()),
            token_count=token_len,
            tags=tag_list,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
            summary=summary,
            metadata=metadata or {},
        )
        self.entries[id] = entry

        # Accumulate postings for this document
        doc_term_map: dict[str, Posting] = {}

        # 1. Body tokens
        for tok in body_tokens:
            stem = tok.stem
            self.vocabulary.add(stem)
            if len(tok.text) >= 3:
                self.vocabulary.add(tok.text.lower())
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

        # 2. Title tokens
        for tok in title_tokens:
            stem = tok.stem
            self.vocabulary.add(stem)
            if len(tok.text) >= 3:
                self.vocabulary.add(tok.text.lower())
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

        # 3. Tag tokens
        for tok in tag_tokens:
            stem = tok.stem
            self.vocabulary.add(stem)
            if len(tok.text) >= 3:
                self.vocabulary.add(tok.text.lower())
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
            self.postings[stem][id] = posting

        # 4. Compute co-occurrence within sliding window of 8 tokens
        self._record_cooccurrences(body_tokens)

    def _record_cooccurrences(self, tokens: list[Token], window_size: int = 8) -> None:
        """
        Record pairwise co-occurrences of terms within a sliding window.
        """
        n = len(tokens)
        for i in range(n):
            term_a = tokens[i].stem
            for j in range(i + 1, min(i + window_size, n)):
                term_b = tokens[j].stem
                if term_a != term_b:
                    pair = (min(term_a, term_b), max(term_a, term_b))
                    self.cooccurrences[pair] += 1

    def remove_document(self, id: str) -> None:
        """
        Remove a document from postings and memory registry.
        """
        if id not in self.entries:
            return

        old_len = self.doc_lengths.pop(id, 0)
        self.total_tokens = max(0, self.total_tokens - old_len)
        del self.entries[id]

        empty_stems = []
        for stem, doc_map in self.postings.items():
            if id in doc_map:
                del doc_map[id]
                if not doc_map:
                    empty_stems.append(stem)

        for stem in empty_stems:
            del self.postings[stem]

    def remove_by_source_id(self, source_id: str) -> None:
        """
        Remove a source and all associated document entries from the index.
        """
        to_remove = [
            doc_id
            for doc_id, entry in list(self.entries.items())
            if doc_id == source_id or entry.source_id == source_id
        ]
        for doc_id in to_remove:
            self.remove_document(doc_id)

        # Also purge from SQLite persistence if db is configured
        if self.db:
            try:
                self.db.execute("DELETE FROM search_postings WHERE source_id = ?;", (source_id,))
                self.db.execute("DELETE FROM search_source_stats WHERE source_id = ?;", (source_id,))
            except Exception as e:
                logger.warning("Error removing source %s from search_postings: %s", source_id, e)

    def clear(self) -> None:
        """Reset the in-memory index entirely."""
        self.postings.clear()
        self.entries.clear()
        self.doc_lengths.clear()
        self.cooccurrences.clear()
        self.vocabulary.clear()
        self.total_tokens = 0

    # ──────────────────────────────────────────────────────────────────────────
    # Term Exploration & Co-occurrence
    # ──────────────────────────────────────────────────────────────────────────

    def get_related_terms(self, term: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Return the top terms that deterministically co-occur with the given term.
        """
        stemmed = self.tokenizer.stemmer.stem((term or "").lower().strip())
        if not stemmed:
            return []

        scored_pairs: list[tuple[str, int]] = []
        for (term_a, term_b), count in self.cooccurrences.items():
            if term_a == stemmed:
                scored_pairs.append((term_b, count))
            elif term_b == stemmed:
                scored_pairs.append((term_a, count))

        scored_pairs.sort(key=lambda x: x[1], reverse=True)
        return [
            {"term": t, "cooccurrences": count}
            for t, count in scored_pairs[:limit]
        ]

    def get_term_stats(self, term: str) -> tuple[int, int]:
        """
        Return (source_count, total_occurrences) for a given term.
        """
        stemmed = self.tokenizer.stemmer.stem((term or "").lower().strip())
        if stemmed not in self.postings:
            return 0, 0

        postings_map = self.postings[stemmed]
        source_count = len(postings_map)
        total_occurrences = sum(p.term_frequency for p in postings_map.values())
        return source_count, total_occurrences

    # ──────────────────────────────────────────────────────────────────────────
    # Zero-Result Intelligence: Deterministic Vocabulary Suggestions
    # ──────────────────────────────────────────────────────────────────────────

    def get_zero_result_suggestions(self, query: str, limit: int = 4) -> list[str]:
        """
        Generate deterministic suggestions for misspelled or missing query terms
        based exclusively on the actual vocabulary present in the indexed collection.
        Uses Levenshtein edit distance and prefix matching.
        """
        clean = (query or "").lower().strip()
        if not clean or not self.vocabulary:
            return []

        tokens = self.tokenizer.tokenize(clean, remove_stopwords=False, stem=False)
        query_words = [t.text for t in tokens if len(t.text) >= 3]
        if not query_words:
            query_words = [clean]

        suggestions: list[tuple[str, float]] = []

        for target_word in query_words:
            target_stem = self.tokenizer.stemmer.stem(target_word)

            for vocab_term in self.vocabulary:
                stem_term = self.tokenizer.stemmer.stem(vocab_term)
                doc_freq = len(self.postings.get(vocab_term, {})) or len(self.postings.get(stem_term, {}))

                dist_word = self._levenshtein_distance(target_word, vocab_term)
                dist_stem = self._levenshtein_distance(target_stem, vocab_term)
                min_d = min(dist_word, dist_stem)

                # Prioritize natural words over truncated stems (e.g. 'flashattention' over 'flashattent')
                is_full_word = len(vocab_term) > len(stem_term) or vocab_term not in self.postings

                # 1. Exact prefix match
                if vocab_term.startswith(target_word[:4]) and len(vocab_term) >= 3:
                    len_diff = abs(len(vocab_term) - len(target_word))
                    score = (14.0 - min(len_diff, 8)) + (3.0 if is_full_word else 0.0) + math.log(doc_freq + 1.0)
                    suggestions.append((vocab_term, score))
                    continue

                # 2. Levenshtein edit distance
                max_d = 2 if len(target_word) <= 6 else 3
                if min_d <= max_d:
                    len_diff = abs(len(vocab_term) - len(target_word))
                    score = (12.0 - min_d * 2.0 - (len_diff * 0.5)) + (3.0 if is_full_word else 0.0) + math.log(doc_freq + 1.0)
                    suggestions.append((vocab_term, score))
                    continue

                # 3. Substring match
                if len(target_word) >= 4 and (target_word in vocab_term or vocab_term in target_word):
                    score = (6.0 - abs(len(vocab_term) - len(target_word))) + (2.0 if is_full_word else 0.0) + math.log(doc_freq + 1.0)
                    suggestions.append((vocab_term, score))
                    continue

        # Sort by score descending and deduplicate
        suggestions.sort(key=lambda x: x[1], reverse=True)
        seen: set[str] = set()
        final_suggestions: list[str] = []
        for word, _ in suggestions:
            if word not in seen and word != clean:
                seen.add(word)
                final_suggestions.append(word)
                if len(final_suggestions) >= limit:
                    break

        return final_suggestions

    @staticmethod
    def _levenshtein_distance(s1: str, s2: str) -> int:
        """Compute standard Levenshtein edit distance between two strings."""
        if len(s1) < len(s2):
            return SearchIndex._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    # ──────────────────────────────────────────────────────────────────────────
    # SQLite Index Persistence (Section 25)
    # ──────────────────────────────────────────────────────────────────────────

    def save_to_sqlite(self) -> None:
        """
        Persist current index postings, source statistics, and co-occurrences
        into SQLite tables for fast restore across restarts.
        """
        if not self.db:
            return

        try:
            # 1. Persist source stats
            stats_params = []
            for entry in self.entries.values():
                stats_params.append((
                    entry.id,
                    entry.token_count,
                    entry.title,
                    entry.file_type,
                    entry.created_at,
                ))

            if stats_params:
                self.db.execute("DELETE FROM search_source_stats;")
                sql_stats = """
                INSERT INTO search_source_stats (source_id, token_count, title, file_type, updated_at)
                VALUES (?, ?, ?, ?, ?);
                """
                self.db.executemany(sql_stats, stats_params)

            # 2. Persist postings
            postings_params = []
            for term, doc_map in self.postings.items():
                for doc_id, p in doc_map.items():
                    postings_params.append((
                        term,
                        doc_id,
                        p.term_frequency,
                        json.dumps(p.positions),
                        1 if p.in_title else 0,
                    ))

            if postings_params:
                self.db.execute("DELETE FROM search_postings;")
                sql_post = """
                INSERT INTO search_postings (term, source_id, term_frequency, positions_json, in_title)
                VALUES (?, ?, ?, ?, ?);
                """
                self.db.executemany(sql_post, postings_params)

            # 3. Persist top co-occurrences
            cooc_params = [
                (term_a, term_b, count)
                for (term_a, term_b), count in self.cooccurrences.items()
            ]
            if cooc_params:
                self.db.execute("DELETE FROM term_cooccurrences;")
                sql_cooc = """
                INSERT INTO term_cooccurrences (term_a, term_b, cooccurrence_count)
                VALUES (?, ?, ?);
                """
                self.db.executemany(sql_cooc, cooc_params)

            logger.info("Persisted search index to SQLite (%d postings, %d sources)", len(postings_params), len(stats_params))
        except Exception as exc:
            logger.warning("Failed to persist search index to SQLite: %s", exc)

    def load_from_sqlite(self, sources_map: dict[str, Source]) -> bool:
        """
        Load postings, source statistics, and co-occurrences directly from SQLite tables.
        Returns True if index was successfully restored from SQLite.
        """
        if not self.db:
            return False

        try:
            # Check if postings exist in SQLite
            post_rows = self.db.fetchall("SELECT term, source_id, term_frequency, positions_json, in_title FROM search_postings;")
            if not post_rows:
                return False

            self.clear()

            # Restore postings
            for r in post_rows:
                term = r["term"]
                source_id = r["source_id"]
                positions = json.loads(r["positions_json"]) if r["positions_json"] else []
                posting = Posting(
                    doc_id=source_id,
                    term_frequency=r["term_frequency"],
                    positions=positions,
                    in_title=bool(r["in_title"]),
                )
                self.postings[term][source_id] = posting
                self.vocabulary.add(term)

            # Restore source stats & entries from sources_map
            stats_rows = self.db.fetchall("SELECT source_id, token_count, title, file_type, updated_at FROM search_source_stats;")
            for r in stats_rows:
                sid = r["source_id"]
                src = sources_map.get(sid)
                if src:
                    self.entries[sid] = IndexEntry(
                        id=sid,
                        title=src.title,
                        content=src.content or "",
                        source_id=sid,
                        filename=src.filename,
                        file_type=src.file_type or "txt",
                        word_count=src.word_count,
                        token_count=r["token_count"],
                        created_at=r["updated_at"],
                    )
                    self.doc_lengths[sid] = r["token_count"]
                    self.total_tokens += r["token_count"]
                    # Populate vocabulary with original words from title & content
                    text_sample = f"{src.title} {src.content or ''}"
                    for tok in self.tokenizer.tokenize(text_sample, remove_stopwords=False, stem=False):
                        if len(tok.text) >= 3:
                            self.vocabulary.add(tok.text.lower())

            # Restore co-occurrences
            cooc_rows = self.db.fetchall("SELECT term_a, term_b, cooccurrence_count FROM term_cooccurrences;")
            for r in cooc_rows:
                self.cooccurrences[(r["term_a"], r["term_b"])] = r["cooccurrence_count"]

            logger.info("Restored search index from SQLite: %d items, %d terms", len(self.entries), len(self.postings))
            return len(self.entries) > 0
        except Exception as exc:
            logger.warning("Failed to load search index from SQLite: %s", exc)
            return False

    def idf(self, term: str) -> float:
        """
        Calculate Robertson-Spärck Jones Inverse Document Frequency with smoothing.
        """
        doc_count = len(self.postings.get(term, {}))
        if doc_count == 0:
            return 0.0
        n = doc_count
        N = self.total_docs
        return math.log(1.0 + (N - n + 0.5) / (n + 0.5))

    def _parse_query_components(self, raw_query: str) -> dict[str, Any]:
        """
        Parse raw query string into phrases, excluded terms, field filters, and general terms.
        """
        clean = (raw_query or "").strip()
        phrases: list[list[str]] = []
        excluded_terms: list[str] = []
        field_filters: dict[str, str] = {}
        general_terms: list[str] = []

        phrase_matches = re.findall(r'"([^"]+)"', clean)
        for p in phrase_matches:
            toks = [t.stem for t in self.tokenizer.tokenize(p, remove_stopwords=False, stem=True)]
            if toks:
                phrases.append(toks)
        clean = re.sub(r'"[^"]+"', " ", clean)

        raw_words = clean.split()
        for w in raw_words:
            if ":" in w and not w.startswith("-"):
                parts = w.split(":", 1)
                f_name = parts[0].lower().strip()
                f_val = parts[1].lower().strip()
                field_filters[f_name] = f_val
                continue

            if w.startswith("-") and len(w) > 1:
                stems = [t.stem for t in self.tokenizer.tokenize(w[1:], remove_stopwords=False, stem=True)]
                excluded_terms.extend(stems)
                continue

            stems = [t.stem for t in self.tokenizer.tokenize(w, remove_stopwords=True, stem=True)]
            general_terms.extend(stems)

        return {
            "phrases": phrases,
            "excluded_terms": set(excluded_terms),
            "field_filters": field_filters,
            "general_terms": list(dict.fromkeys(general_terms)),
        }

    def _matches_phrase(self, doc_id: str, phrase_stems: list[str]) -> bool:
        """Check if consecutive tokens in a phrase appear consecutively in document positions."""
        if not phrase_stems:
            return True
        first_stem = phrase_stems[0]
        first_post = self.postings.get(first_stem, {}).get(doc_id)
        if not first_post or not first_post.positions:
            return False

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
            candidates = list(self.entries.values())
            if filter_type and filter_type.lower() != "all":
                candidates = [c for c in candidates if c.file_type == filter_type.lower()]
            hits = [ScoredHit(entry=c, score=1.0) for c in candidates]
            hits.sort(key=lambda h: h.entry.created_at, reverse=True)
            total = len(hits)
            return hits[offset : offset + limit], total

        candidate_ids: set[str] = set()

        if all_query_stems:
            for term in all_query_stems:
                if term in self.postings:
                    candidate_ids.update(self.postings[term].keys())
        elif field_filters:
            candidate_ids = set(self.entries.keys())

        for ex in excluded:
            if ex in self.postings:
                candidate_ids.difference_update(self.postings[ex].keys())

        target_type = field_filters.get("format") or field_filters.get("type") or filter_type
        if target_type and target_type.lower() != "all":
            candidate_ids = {
                did for did in candidate_ids
                if self.entries[did].file_type == target_type.lower()
            }

        if "tag" in field_filters:
            req_tag = field_filters["tag"].lower()
            candidate_ids = {
                did for did in candidate_ids
                if any(req_tag in t.lower() for t in self.entries[did].tags)
            }

        for phrase in phrases:
            candidate_ids = {
                did for did in candidate_ids
                if self._matches_phrase(did, phrase)
            }

        if not candidate_ids:
            return [], 0

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

                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / avgdl))
                term_score = idf_val * (numerator / denominator)

                if post.in_title:
                    term_score *= self.title_boost

                if post.in_tags:
                    term_score *= self.tag_boost

                score += term_score

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

        if sort_by == "newest":
            scored_hits.sort(key=lambda h: h.entry.created_at, reverse=True)
        elif sort_by == "oldest":
            scored_hits.sort(key=lambda h: h.entry.created_at)
        elif sort_by == "largest":
            scored_hits.sort(key=lambda h: h.entry.word_count, reverse=True)
        else:
            scored_hits.sort(key=lambda h: h.score, reverse=True)

        return scored_hits[offset : offset + limit], len(scored_hits)


# Backward compatibility alias
InvertedIndex = SearchIndex
