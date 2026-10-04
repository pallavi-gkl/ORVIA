"""
RelationshipCalculator — Phase 6 Concept Intelligence

Calculates pairwise relationship strength between concepts based on
how many sources they co-occur in.

Algorithm:
  - For each pair of concept IDs (A, B) where A < B:
    - shared_sources = number of sources containing BOTH A and B
    - strength = shared_sources / sqrt(sources_A * sources_B)   (Jaccard-like)

This is explainable:
  - "Concepts A and B appear together in N of your sources."
  - Strength of 1.0 = they always co-occur; 0.0 = never co-occur.

No embeddings. No semantic vectors. No external APIs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ConceptRelationship:
    """Pairwise co-occurrence relationship between two concepts."""

    concept_a_id: str
    concept_b_id: str
    shared_sources: int
    strength: float             # 0.0 – 1.0

    @property
    def strength_label(self) -> str:
        """Human-readable strength description."""
        if self.strength >= 0.75:
            return "Strongly co-occurs"
        if self.strength >= 0.40:
            return "Frequently co-occurs"
        if self.strength >= 0.20:
            return "Sometimes co-occurs"
        return "Rarely co-occurs"

    @property
    def strength_pct(self) -> int:
        """Strength as an integer percentage (0–100) for display."""
        return round(self.strength * 100)


class RelationshipCalculator:
    """
    Calculates pairwise concept relationship strengths.

    Usage::

        calc = RelationshipCalculator()
        # concept_source_map: {concept_id: set[source_id]}
        relationships = calc.calculate(concept_source_map, min_shared=1)
    """

    def calculate(
        self,
        concept_source_map: dict[str, set[str]],
        min_shared: int = 1,
    ) -> list[ConceptRelationship]:
        """
        Return pairwise ConceptRelationship objects for all concept pairs.

        Parameters
        ----------
        concept_source_map : dict[str, set[str]]
            Mapping from concept_id → set of source_ids containing that concept.
        min_shared : int
            Minimum number of shared sources to be considered a relationship.
            Default: 1 (any overlap).

        Returns
        -------
        list[ConceptRelationship]
            Sorted by strength descending.
        """
        concept_ids = list(concept_source_map.keys())
        relationships: list[ConceptRelationship] = []

        for i in range(len(concept_ids)):
            for j in range(i + 1, len(concept_ids)):
                a_id = concept_ids[i]
                b_id = concept_ids[j]
                sources_a = concept_source_map[a_id]
                sources_b = concept_source_map[b_id]

                shared = sources_a & sources_b
                shared_count = len(shared)
                if shared_count < min_shared:
                    continue

                # Geometric-mean normalised Jaccard-like strength
                denominator = math.sqrt(len(sources_a) * len(sources_b))
                strength = shared_count / denominator if denominator > 0 else 0.0
                strength = min(1.0, round(strength, 4))

                # Canonical ordering: smaller id first for consistent PK
                if a_id < b_id:
                    rel = ConceptRelationship(
                        concept_a_id=a_id,
                        concept_b_id=b_id,
                        shared_sources=shared_count,
                        strength=strength,
                    )
                else:
                    rel = ConceptRelationship(
                        concept_a_id=b_id,
                        concept_b_id=a_id,
                        shared_sources=shared_count,
                        strength=strength,
                    )
                relationships.append(rel)

        relationships.sort(key=lambda r: r.strength, reverse=True)
        return relationships

    def get_related_for(
        self,
        concept_id: str,
        all_relationships: list[ConceptRelationship],
        limit: int = 10,
    ) -> list[ConceptRelationship]:
        """Filter and return relationships involving *concept_id*, strongest first."""
        related = [
            r for r in all_relationships
            if r.concept_a_id == concept_id or r.concept_b_id == concept_id
        ]
        related.sort(key=lambda r: r.strength, reverse=True)
        return related[:limit]
