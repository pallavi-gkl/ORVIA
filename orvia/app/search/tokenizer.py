"""
Search Tokenizer & Stemmer for ORVIA.
Provides pure-Python text tokenization, case-folding, stop word filtering,
position tracking, and deterministic suffix stemming (Porter Stemmer).
Zero external dependencies.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Token:
    """Represents an extracted token with character offsets and stem."""
    text: str              # Original token text (lowercased)
    stem: str              # Stemmed representation
    position: int          # Token index in sequence (0-indexed)
    start_char: int        # Character start offset in raw text
    end_char: int          # Character end offset in raw text


# Curated set of standard English stop words
STOP_WORDS: frozenset[str] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
})


class PorterStemmer:
    """
    Pure-Python implementation of Martin Porter's 1980 stemming algorithm.
    Reduces English morphological variants to a canonical base form.
    """

    def is_consonant(self, word: str, i: int) -> bool:
        """Check if character at index i is a consonant."""
        ch = word[i]
        if ch in "aeiou":
            return False
        if ch == "y":
            if i == 0:
                return True
            return not self.is_consonant(word, i - 1)
        return True

    def measure(self, word: str) -> int:
        """Measure the number of consonant sequences between vowels (VC patterns)."""
        n = 0
        i = 0
        length = len(word)
        while i < length:
            if not self.is_consonant(word, i):
                break
            i += 1
        i += 1
        while i < length:
            while i < length:
                if self.is_consonant(word, i):
                    break
                i += 1
            i += 1
            if i <= length:
                n += 1
            while i < length:
                if not self.is_consonant(word, i):
                    break
                i += 1
            i += 1
        return n

    def contains_vowel(self, stem: str) -> bool:
        """Check if the stem contains at least one vowel."""
        for i in range(len(stem)):
            if not self.is_consonant(stem, i):
                return True
        return False

    def ends_double_consonant(self, word: str) -> bool:
        """Check if the word ends with two identical consonants."""
        if len(word) < 2:
            return False
        return word[-1] == word[-2] and self.is_consonant(word, len(word) - 1)

    def cvc(self, word: str) -> bool:
        """Check if the word ends in consonant-vowel-consonant (not w, x, y)."""
        length = len(word)
        if length < 3:
            return False
        if (
            self.is_consonant(word, length - 1)
            and not self.is_consonant(word, length - 2)
            and self.is_consonant(word, length - 3)
        ):
            if word[-1] not in ("w", "x", "y"):
                return True
        return False

    def stem(self, word: str) -> str:
        """Apply Porter Stemming rules to convert word to base root."""
        w = word.lower()
        if len(w) <= 2:
            return w

        # Step 1a: Plurals and -ed / -ing
        if w.endswith("sses"):
            w = w[:-2]
        elif w.endswith("ies"):
            w = w[:-2]
        elif not w.endswith("ss") and w.endswith("s"):
            w = w[:-1]

        # Step 1b
        extra_step = False
        if w.endswith("eed"):
            stem = w[:-3]
            if self.measure(stem) > 0:
                w = stem + "ee"
        elif w.endswith("ed"):
            stem = w[:-2]
            if self.contains_vowel(stem):
                w = stem
                extra_step = True
        elif w.endswith("ing"):
            stem = w[:-3]
            if self.contains_vowel(stem):
                w = stem
                extra_step = True

        if extra_step:
            if w.endswith("at") or w.endswith("bl") or w.endswith("iz"):
                w = w + "e"
            elif self.ends_double_consonant(w) and w[-1] not in ("l", "s", "z"):
                w = w[:-1]
            elif self.measure(w) == 1 and self.cvc(w):
                w = w + "e"

        # Step 1c: y -> i
        if w.endswith("y"):
            stem = w[:-1]
            if self.contains_vowel(stem):
                w = stem + "i"

        # Step 2: Suffix replacements
        step2_rules = (
            ("ational", "ate"), ("tional", "tion"), ("enci", "ence"),
            ("anci", "ance"), ("izer", "ize"), ("abli", "able"),
            ("alli", "al"), ("entli", "ent"), ("eli", "e"),
            ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
            ("ator", "ate"), ("alism", "al"), ("iveness", "ive"),
            ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"),
            ("iviti", "ive"), ("biliti", "ble"),
        )
        for suffix, replacement in step2_rules:
            if w.endswith(suffix):
                stem = w[:-len(suffix)]
                if self.measure(stem) > 0:
                    w = stem + replacement
                break

        # Step 3
        step3_rules = (
            ("icate", "ic"), ("ative", ""), ("alize", "al"),
            ("iciti", "ic"), ("ical", "ic"), ("ful", ""),
            ("ness", ""),
        )
        for suffix, replacement in step3_rules:
            if w.endswith(suffix):
                stem = w[:-len(suffix)]
                if self.measure(stem) > 0:
                    w = stem + replacement
                break

        # Step 4
        step4_suffixes = (
            "al", "ance", "ence", "er", "ic", "able", "ible", "ant",
            "ement", "ment", "ent", "ou", "ism", "ate", "iti", "ous",
            "ive", "ize",
        )
        for suffix in step4_suffixes:
            if w.endswith(suffix):
                stem = w[:-len(suffix)]
                if self.measure(stem) > 1:
                    w = stem
                break
        else:
            if w.endswith("ion"):
                stem = w[:-3]
                if self.measure(stem) > 1 and (len(stem) > 0 and stem[-1] in ("s", "t")):
                    w = stem

        # Step 5a
        if w.endswith("e"):
            stem = w[:-1]
            m = self.measure(stem)
            if m > 1 or (m == 1 and not self.cvc(stem)):
                w = stem

        # Step 5b
        if self.measure(w) > 1 and self.ends_double_consonant(w) and w.endswith("l"):
            w = w[:-1]

        return w


class SearchTokenizer:
    """
    Extracts normalized, positional, and stemmed tokens from arbitrary text strings.
    """

    # Matches sequences of word characters and hyphens/underscores
    WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")

    def __init__(self, stop_words: frozenset[str] = STOP_WORDS) -> None:
        self.stop_words = stop_words
        self.stemmer = PorterStemmer()

    def normalize_unicode(self, text: str) -> str:
        """Apply Unicode canonical composition (NFC)."""
        return unicodedata.normalize("NFC", text or "")

    def tokenize(
        self,
        text: str,
        remove_stopwords: bool = True,
        stem: bool = True,
    ) -> list[Token]:
        """
        Tokenize raw text into rich Token dataclass instances containing
        original text, stem, position index, and character offsets.
        """
        normalized = self.normalize_unicode(text)
        tokens: list[Token] = []
        pos = 0

        for match in self.WORD_PATTERN.finditer(normalized):
            raw_word = match.group(0)
            lowered = raw_word.lower()

            if remove_stopwords and lowered in self.stop_words:
                continue

            # Minimum 2 chars or single digit
            if len(lowered) < 2 and not lowered.isdigit():
                continue

            stemmed = self.stemmer.stem(lowered) if stem else lowered

            tokens.append(
                Token(
                    text=lowered,
                    stem=stemmed,
                    position=pos,
                    start_char=match.start(),
                    end_char=match.end(),
                )
            )
            pos += 1

        return tokens

    def tokenize_terms(self, text: str, stem: bool = True) -> list[str]:
        """Convenience method returning a simple list of stemmed term strings."""
        return [t.stem if stem else t.text for t in self.tokenize(text, remove_stopwords=True, stem=stem)]

    def extract_query_terms(self, query: str) -> list[str]:
        """
        Extract searchable query terms preserving meaningful query tokens
        (including words that might be stop words if they appear inside exact phrases).
        """
        normalized = self.normalize_unicode(query)
        terms: list[str] = []
        for match in self.WORD_PATTERN.finditer(normalized):
            w = match.group(0).lower()
            if len(w) >= 2 or w.isdigit():
                terms.append(self.stemmer.stem(w))
        return terms
