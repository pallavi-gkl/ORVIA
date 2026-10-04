"""
ConceptScorer — Phase 6 Concept Intelligence

Scores concepts by importance using explainable deterministic criteria.

Score components (all additive, always described):
  1. Frequency score         — raw occurrence count (log-scaled)
  2. Source coverage score   — fraction of total collection containing concept
  3. Title bonus             — appears in source title
  4. Phrase length bonus     — multi-word concepts often more specific

Scoring avoids decimals that look like magic numbers.
All components are labelled so the UI can explain them.

Design notes:
  - Score is a float in [0, 100] range (percentage-like, not a probability)
  - Scores are comparable across a collection but NOT globally calibrated
  - Trend classification is calculated separately (ConceptStatistics)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from orvia.app.analysis.concepts.normalizer import NormalizedCandidate


@dataclass
class ScoredConcept:
    """A concept candidate with a calculated importance score."""

    canonical: str
    display: str
    ngram_size: int
    total_frequency: int   # occurrences in this source
    source_count: int      # number of distinct sources containing this concept
    collection_size: int   # total sources in the collection
    in_title: bool

    # Score components (set by ConceptScorer)
    score: float = 0.0
    score_frequency: float = 0.0
    score_coverage: float = 0.0
    score_title: float = 0.0
    score_phrase: float = 0.0

    @property
    def coverage_pct(self) -> float:
        """Fraction of the collection that contains this concept (0–1)."""
        if self.collection_size == 0:
            return 0.0
        return self.source_count / self.collection_size

    @property
    def coverage_label(self) -> str:
        """Human-readable coverage description."""
        pct = self.coverage_pct * 100
        if pct >= 80:
            return "Widespread"
        if pct >= 50:
            return "Common"
        if pct >= 25:
            return "Present in many sources"
        if pct >= 10:
            return "Present in some sources"
        return "Rare"

    @property
    def score_explanation(self) -> str:
        """Plain-English explanation of the score components."""
        parts = []
        if self.score_frequency > 0:
            parts.append(f"frequency ×{self.total_frequency}")
        if self.score_coverage > 0:
            parts.append(f"seen in {self.source_count} source(s)")
        if self.score_title > 0:
            parts.append("appears in title")
        if self.score_phrase > 0:
            parts.append(f"{self.ngram_size}-word phrase")
        return " · ".join(parts) if parts else "low signal"


class ConceptScorer:
    """
    Assigns importance scores to concept candidates.

    Parameters
    ----------
    freq_weight : float
        Weight applied to the log-frequency component. Default 40.
    coverage_weight : float
        Weight applied to the source-coverage component. Default 40.
    title_weight : float
        Bonus for appearing in source title. Default 12.
    phrase_weight : float
        Bonus for multi-word phrases. Default 8.
    """

    def __init__(
        self,
        freq_weight: float = 40.0,
        coverage_weight: float = 40.0,
        title_weight: float = 12.0,
        phrase_weight: float = 8.0,
    ) -> None:
        self.freq_weight = freq_weight
        self.coverage_weight = coverage_weight
        self.title_weight = title_weight
        self.phrase_weight = phrase_weight

    def score(
        self,
        candidate: NormalizedCandidate,
        source_count: int,       # how many distinct sources contain this concept
        collection_size: int,    # total sources in the collection
        max_frequency: int = 1,  # max frequency observed in collection (for normalization)
    ) -> ScoredConcept:
        """
        Calculate and return a ScoredConcept.

        All arithmetic is simple and explainable:
        - freq_score: log1p(freq) / log1p(max_freq)  — normalized log frequency
        - coverage_score: source_count / collection_size
        - title_bonus: 1 if in title, else 0
        - phrase_bonus: 0.5 per extra n-gram word beyond 1
        """
        max_freq = max(max_frequency, candidate.total_frequency, 1)

        freq_score = (
            math.log1p(candidate.total_frequency) / math.log1p(max_freq)
            if max_freq > 0
            else 0.0
        )
        cov_score = source_count / max(collection_size, 1)
        title_bonus = 1.0 if candidate.in_title else 0.0
        phrase_bonus = min((candidate.ngram_size - 1) * 0.5, 1.0)

        sc = ScoredConcept(
            canonical=candidate.canonical,
            display=candidate.display,
            ngram_size=candidate.ngram_size,
            total_frequency=candidate.total_frequency,
            source_count=source_count,
            collection_size=collection_size,
            in_title=candidate.in_title,
        )
        sc.score_frequency = round(freq_score * self.freq_weight, 2)
        sc.score_coverage = round(cov_score * self.coverage_weight, 2)
        sc.score_title = round(title_bonus * self.title_weight, 2)
        sc.score_phrase = round(phrase_bonus * self.phrase_weight, 2)
        sc.score = round(
            sc.score_frequency + sc.score_coverage + sc.score_title + sc.score_phrase, 2
        )
        return sc
