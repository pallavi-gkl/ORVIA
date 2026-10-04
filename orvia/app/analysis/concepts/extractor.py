"""
ConceptExtractor — Phase 6 Concept Intelligence

Extracts single-word and multi-word (bi-gram / tri-gram) concept candidates
from source content using pure deterministic frequency analysis.

No external APIs. No LLMs. No embeddings.
Results are frequency-counted over the full text content of each source.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Stop-word lists
# ---------------------------------------------------------------------------

# Pure grammar function words — articles, prepositions, conjunctions, pronouns,
# auxiliary verbs, and discourse markers. These must NEVER be standalone concepts
# and must NEVER start or end an n-gram phrase.
_GRAMMAR_STOP_WORDS: frozenset[str] = frozenset(
    {
        # Articles / determiners
        "a", "an", "the", "this", "that", "these", "those", "my", "your",
        "our", "their", "its", "his", "her",
        # Prepositions
        "in", "on", "at", "to", "for", "of", "from", "with", "by", "as",
        "into", "through", "during", "before", "after", "above", "below",
        "between", "about", "against", "along", "around", "among", "within",
        "without", "towards", "toward", "upon", "per", "via", "over", "under",
        # Conjunctions
        "and", "or", "but", "nor", "so", "yet", "both", "either", "neither",
        "not", "no",
        # Pronouns
        "i", "me", "we", "us", "you", "he", "she", "it", "they", "them",
        "who", "whom", "which", "what", "where", "when", "how", "why",
        # Common verbs (bare)
        "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "shall", "must", "can", "need", "dare", "ought",
        "used", "get", "got", "make", "made", "use", "see", "know", "think",
        "take", "come", "go", "give", "find", "tell", "ask", "seem", "feel",
        "try", "leave", "call", "keep", "let", "begin", "show", "hear",
        "play", "run", "move", "live", "believe", "hold", "bring", "happen",
        "write", "provide", "sit", "stand", "lose", "pay", "meet", "include",
        "continue", "set", "learn", "change", "lead", "understand", "watch",
        "follow", "stop", "create", "spend", "grow", "open", "walk", "win",
        "allow", "add", "require", "consider", "become", "involve", "suggest",
        "mean", "put", "turn", "start", "appear", "want",
        # Adverbs / misc
        "also", "just", "very", "more", "most", "some", "any", "all", "each",
        "every", "few", "many", "other", "same", "such", "only",
        "than", "then", "there", "here", "now", "well", "even",
        "still", "back", "way", "up", "out", "if", "else", "whether",
        "however", "thus", "therefore", "hence", "since", "because",
        "although", "though", "while", "whereas", "once",
        "already", "often", "always", "never", "sometimes",
        "usually", "generally", "typically", "approximately",
        "much", "little", "less", "quite", "rather", "again",
        "further", "too", "enough", "soon",
    }
)

# Words that should not be standalone unigrams, but CAN be modifiers in multi-word phrases
_MODIFIER_STOP_WORDS: frozenset[str] = frozenset(
    {
        "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "first", "second", "third", "last", "next",
        "new", "old", "high", "low", "good", "bad", "big", "small",
        "large", "long", "short", "different", "specific", "certain",
        "important", "possible", "based", "given", "following", "related",
        "example", "note", "type", "way", "case", "part", "form", "work",
        "number", "place", "point", "time", "day", "year",
    }
)

# Backward-compatible complete stop words list
_STOP_WORDS: frozenset[str] = _GRAMMAR_STOP_WORDS | _MODIFIER_STOP_WORDS

# Minimum lengths and thresholds (allow 2-letter tokens like "ai", "ml", "ui", "os", "db")
_MIN_WORD_LEN = 2
_MIN_NGRAM_WORD_LEN = 2
_MIN_UNIGRAM_FREQ = 2   # must appear ≥ N times to be considered a concept
_MIN_BIGRAM_FREQ = 2
_MIN_TRIGRAM_FREQ = 2


@dataclass
class RawCandidate:
    """A candidate concept term before normalisation and scoring."""

    text: str                   # The candidate string (lowercased, stripped)
    ngram_size: int             # 1 = unigram, 2 = bigram, 3 = trigram
    total_frequency: int        # Total occurrences across the source
    in_title: bool              # True if found verbatim in source title
    source_id: str
    first_occurrence: int = 0   # Character offset of first occurrence
    last_occurrence: int = 0    # Character offset of last occurrence


class ConceptExtractor:
    """
    Extracts raw concept candidates from a source's content and title.

    Algorithm:
      1. Segment content into clauses bounded by punctuation and line breaks.
      2. Tokenize words within clauses (keeping 2+ letter words).
      3. Extract unigrams (filtering _STOP_WORDS).
      4. Extract bigrams/trigrams within clause boundaries (ensuring endpoints
         are not in _GRAMMAR_STOP_WORDS).
      5. Prune subsumed n-gram fragments where longer phrases capture the entity.
      6. Calculate deterministic occurrences and start/end character offsets.
    """

    def __init__(
        self,
        min_unigram_freq: int = _MIN_UNIGRAM_FREQ,
        min_bigram_freq: int = _MIN_BIGRAM_FREQ,
        min_trigram_freq: int = _MIN_TRIGRAM_FREQ,
    ) -> None:
        self.min_unigram_freq = min_unigram_freq
        self.min_bigram_freq = min_bigram_freq
        self.min_trigram_freq = min_trigram_freq

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        source_id: str,
        title: str,
        content: str,
    ) -> list[RawCandidate]:
        """
        Extract concept candidates from *content* (and *title*).

        Returns a list of RawCandidate objects, one per unique candidate term.
        """
        title_lower = (title or "").lower()
        content_text = content or ""

        # Segment content and title into clauses
        clauses = [
            c.strip()
            for c in re.split(r'[\n\r.?!;:,()\[\]"“”—–\t]+', content_text)
            if c.strip()
        ]
        title_clauses = [
            c.strip()
            for c in re.split(r'[\n\r.?!;:,()\[\]"“”—–\t]+', title or "")
            if c.strip()
        ]

        unigram_counts: Counter = Counter()
        bigram_counts: Counter = Counter()
        trigram_counts: Counter = Counter()

        for clause in clauses:
            raw_words = [
                w.lower().strip("-'")
                for w in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'-]*", clause)
            ]
            words = [w for w in raw_words if len(w) >= _MIN_WORD_LEN]

            # Unigrams: filter against full stop words (grammar + generic modifiers)
            for w in words:
                if w not in _STOP_WORDS:
                    unigram_counts[w] += 1

            # Bigrams: strictly within clause, endpoints cannot be grammar stop words
            for i in range(len(words) - 1):
                g = words[i : i + 2]
                if g[0] not in _GRAMMAR_STOP_WORDS and g[1] not in _GRAMMAR_STOP_WORDS:
                    bigram_counts[" ".join(g)] += 1

            # Trigrams: strictly within clause, endpoints cannot be grammar stop words
            for i in range(len(words) - 2):
                g = words[i : i + 3]
                if g[0] not in _GRAMMAR_STOP_WORDS and g[2] not in _GRAMMAR_STOP_WORDS:
                    trigram_counts[" ".join(g)] += 1

        # Build sets of title words and phrases for fast lookup
        title_words: set[str] = set()
        title_phrases: set[str] = set()
        for t_clause in title_clauses:
            t_raw = [
                w.lower().strip("-'")
                for w in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'-]*", t_clause)
            ]
            t_words = [w for w in t_raw if len(w) >= _MIN_WORD_LEN]
            for w in t_words:
                if w not in _STOP_WORDS:
                    title_words.add(w)
            for i in range(len(t_words) - 1):
                if t_words[i] not in _GRAMMAR_STOP_WORDS and t_words[i + 1] not in _GRAMMAR_STOP_WORDS:
                    title_phrases.add(f"{t_words[i]} {t_words[i + 1]}")
            for i in range(len(t_words) - 2):
                if t_words[i] not in _GRAMMAR_STOP_WORDS and t_words[i + 2] not in _GRAMMAR_STOP_WORDS:
                    title_phrases.add(f"{t_words[i]} {t_words[i + 1]} {t_words[i + 2]}")

        # Filter trigrams
        valid_trigrams: dict[str, int] = {}
        for phrase, freq in trigram_counts.items():
            if freq >= self.min_trigram_freq:
                valid_trigrams[phrase] = freq

        # Filter bigrams with subsumption pruning (e.g. "large language" subsumed by "large language models")
        valid_bigrams: dict[str, int] = {}
        for phrase, freq in bigram_counts.items():
            if freq >= self.min_bigram_freq:
                subsumed = False
                for t, t_freq in valid_trigrams.items():
                    if (t.startswith(phrase + " ") or t.endswith(" " + phrase)) and freq <= t_freq:
                        subsumed = True
                        break
                if not subsumed:
                    valid_bigrams[phrase] = freq

        # Filter unigrams
        valid_unigrams: dict[str, int] = {}
        for word, freq in unigram_counts.items():
            if freq >= self.min_unigram_freq:
                valid_unigrams[word] = freq

        # Helper to compute character offsets
        def find_offsets(term: str) -> tuple[int, int]:
            pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            matches = list(pattern.finditer(content_text))
            if matches:
                return matches[0].start(), matches[-1].start()
            t_match = pattern.search(title)
            if t_match:
                return 0, 0
            return 0, 0

        candidates: list[RawCandidate] = []

        for word, freq in valid_unigrams.items():
            first_occ, last_occ = find_offsets(word)
            candidates.append(
                RawCandidate(
                    text=word,
                    ngram_size=1,
                    total_frequency=freq,
                    in_title=(word in title_words),
                    source_id=source_id,
                    first_occurrence=first_occ,
                    last_occurrence=last_occ,
                )
            )

        for phrase, freq in valid_bigrams.items():
            first_occ, last_occ = find_offsets(phrase)
            candidates.append(
                RawCandidate(
                    text=phrase,
                    ngram_size=2,
                    total_frequency=freq,
                    in_title=(phrase in title_phrases or phrase in title_lower),
                    source_id=source_id,
                    first_occurrence=first_occ,
                    last_occurrence=last_occ,
                )
            )

        for phrase, freq in valid_trigrams.items():
            first_occ, last_occ = find_offsets(phrase)
            candidates.append(
                RawCandidate(
                    text=phrase,
                    ngram_size=3,
                    total_frequency=freq,
                    in_title=(phrase in title_phrases or phrase in title_lower),
                    source_id=source_id,
                    first_occurrence=first_occ,
                    last_occurrence=last_occ,
                )
            )

        return candidates

    # ------------------------------------------------------------------
    # Internal helpers (retained for backward compatibility)
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """
        Tokenize *text* into lowercase alphabetic words.
        Returns words of minimum length that are not stop words.
        """
        if not text:
            return []
        raw = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'-]*", text)
        return [
            w.lower().strip("-'")
            for w in raw
            if len(w) >= _MIN_WORD_LEN and w.lower() not in _STOP_WORDS
        ]

    def _build_unigrams(self, tokens: list[str]) -> Counter:
        """Build a frequency Counter from filtered tokens."""
        filtered = [
            t for t in tokens
            if len(t) >= _MIN_WORD_LEN and t not in _STOP_WORDS
        ]
        return Counter(filtered)

    def _build_ngrams(self, tokens: list[str], n: int) -> Counter:
        """
        Build a frequency Counter for n-grams.
        """
        ngrams: Counter = Counter()
        for i in range(len(tokens) - n + 1):
            gram = tokens[i : i + n]
            if any(len(w) < _MIN_NGRAM_WORD_LEN for w in gram):
                continue
            phrase = " ".join(gram)
            ngrams[phrase] += 1
        return ngrams
