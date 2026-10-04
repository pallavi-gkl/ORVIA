"""
Search Ranking & Relevance Engine for ORVIA Search Intelligence.
Calculates explainable BM25 / TF-IDF ranking scores incorporating title boost,
exact phrase alignment, positional proximity signals, and human-readable match explanations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MatchExplanation:
    """Detailed explainable breakdown of why a result matched and its score."""
    score: float
    relevance_label: str       # e.g. 'High relevance', 'Strong match', 'Moderate relevance'
    summary_text: str          # e.g. 'Title match + 12 term occurrences + 2 phrase matches'
    term_occurrences: int = 0
    title_matches: int = 0
    phrase_matches: int = 0
    proximity_bonus: float = 0.0
    matched_terms: list[str] = field(default_factory=list)


class RankingEngine:
    """
    Deterministic scoring and ranking engine with explainability.
    Combines Robertson-Spärck Jones BM25 with title boosting, phrase detection,
    and n-gram positional proximity bonuses.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        title_boost: float = 2.5,
        tag_boost: float = 1.8,
        phrase_boost: float = 3.0,
        proximity_boost_weight: float = 1.5,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.title_boost = title_boost
        self.tag_boost = tag_boost
        self.phrase_boost = phrase_boost
        self.proximity_boost_weight = proximity_boost_weight

    def calculate_bm25_tf_component(
        self,
        tf: int,
        doc_len: int,
        avg_doc_len: float,
        in_title: bool = False,
        in_tags: bool = False,
    ) -> float:
        """
        Calculate BM25 term frequency saturation component with field boosts.
        """
        if tf <= 0:
            return 0.0

        effective_tf = float(tf)
        if in_title:
            effective_tf *= self.title_boost
        if in_tags:
            effective_tf *= self.tag_boost

        if avg_doc_len <= 0:
            norm_len = 1.0
        else:
            norm_len = (1.0 - self.b) + self.b * (doc_len / avg_doc_len)

        return (effective_tf * (self.k1 + 1.0)) / (effective_tf + self.k1 * norm_len)

    def calculate_proximity(
        self,
        term_positions_map: dict[str, list[int]],
    ) -> tuple[float, int]:
        """
        Calculate positional proximity of multiple query terms.
        Finds the smallest span containing at least one occurrence of all query terms.
        Returns: (proximity_score, min_span)
        """
        if len(term_positions_map) < 2:
            return 0.0, 0

        # Extract sorted position lists for each term
        pos_lists = [sorted(positions) for positions in term_positions_map.values() if positions]
        if len(pos_lists) < 2:
            return 0.0, 0

        # Find minimum window covering at least one position from each list
        indices = [0] * len(pos_lists)
        min_span = float("inf")

        while True:
            current_positions = [pos_lists[i][indices[i]] for i in range(len(pos_lists))]
            span = max(current_positions) - min(current_positions)
            if span < min_span:
                min_span = span

            # Advance pointer pointing to the minimum value
            min_val = min(current_positions)
            min_idx = current_positions.index(min_val)
            indices[min_idx] += 1
            if indices[min_idx] >= len(pos_lists[min_idx]):
                break

        if min_span == float("inf"):
            return 0.0, 0

        # Compact span gives higher bonus (e.g. span of 2 words is highest bonus)
        num_terms = len(pos_lists)
        ideal_span = num_terms - 1
        effective_span = max(0, int(min_span) - ideal_span)

        proximity_score = self.proximity_boost_weight * (10.0 / (effective_span + 5.0))
        return round(proximity_score, 3), int(min_span)

    def detect_phrase_matches(
        self,
        phrase: list[str],
        doc_term_positions: dict[str, list[int]],
    ) -> int:
        """
        Determine exact sequential occurrences of a multi-word phrase
        using token position arrays.
        """
        if not phrase or len(phrase) < 2:
            return 0

        first_term = phrase[0]
        if first_term not in doc_term_positions:
            return 0

        match_count = 0
        for start_pos in doc_term_positions[first_term]:
            seq_matches = True
            for offset, next_term in enumerate(phrase[1:], start=1):
                expected_pos = start_pos + offset
                if next_term not in doc_term_positions or expected_pos not in doc_term_positions[next_term]:
                    seq_matches = False
                    break
            if seq_matches:
                match_count += 1

        return match_count

    def build_explanation(
        self,
        score: float,
        term_occurrences: int,
        title_matches: int,
        phrase_matches: int,
        proximity_bonus: float,
        matched_terms: list[str],
    ) -> MatchExplanation:
        """
        Produce a human-readable, non-technical explanation for why a result matched.
        """
        reasons: list[str] = []

        if title_matches > 0:
            reasons.append("Title match")

        if phrase_matches > 0:
            reasons.append(f"{phrase_matches} exact phrase match{'es' if phrase_matches > 1 else ''}")

        if term_occurrences > 0:
            reasons.append(f"{term_occurrences} term occurrence{'s' if term_occurrences != 1 else ''}")

        if proximity_bonus > 0.5:
            reasons.append("Terms occur close together")

        if not reasons:
            reasons.append("Contextual match")

        # Assign friendly label
        if score >= 5.0 or (title_matches > 0 and term_occurrences >= 3):
            label = "High relevance"
        elif score >= 2.5 or phrase_matches > 0:
            label = "Strong match"
        elif score >= 1.0 or term_occurrences >= 2:
            label = "Moderate relevance"
        else:
            label = "Contextual match"

        summary = " · ".join(reasons)

        return MatchExplanation(
            score=round(score, 3),
            relevance_label=label,
            summary_text=summary,
            term_occurrences=term_occurrences,
            title_matches=title_matches,
            phrase_matches=phrase_matches,
            proximity_bonus=proximity_bonus,
            matched_terms=matched_terms,
        )
