"""
ConceptNormalizer — Phase 6 Concept Intelligence

Normalizes raw concept candidates:
  - Lowercasing (canonical form for equality checks)
  - Conservative deduplication (exact match only — no stemming)
  - Filtering out numeric-only and single-character candidates
  - Calculating display forms (Title Case, acronym preservation)
  - Preserving evidence offsets (first and last occurrence in source)

Design principles:
  - Never merges concepts unless they are identical strings (case-insensitive)
  - Does NOT use stemming (preserves natural readable names)
  - Does NOT make semantic assumptions about meaning
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from orvia.app.analysis.concepts.extractor import RawCandidate


@dataclass
class NormalizedCandidate:
    """A concept candidate after normalisation."""

    canonical: str          # Lowercase, deduplicated form
    display: str            # Best display form (title-cased for unigrams, natural for n-grams)
    ngram_size: int
    total_frequency: int
    in_title: bool
    source_id: str
    first_occurrence: int = 0
    last_occurrence: int = 0

    def __hash__(self) -> int:
        return hash(self.canonical)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NormalizedCandidate):
            return NotImplemented
        return self.canonical == other.canonical


_NUMERIC_ONLY = re.compile(r"^\d+$")
_HAS_ALPHA = re.compile(r"[a-z]")

# Known acronyms that should be formatted uppercase
_RECOGNIZED_ACRONYMS = frozenset({
    "ai", "rag", "llm", "api", "ml", "ui", "ux", "db", "os", "qa",
    "io", "cpu", "gpu", "sram", "hbm", "mqa", "gqa", "mha", "ip",
    "vr", "ar", "sql", "csv", "json", "xml", "html", "css", "url",
})


class ConceptNormalizer:
    """
    Deduplicates and normalises RawCandidates into NormalizedCandidates.

    Normalisation rules applied in order:
    1. Lowercase canonical form
    2. Strip leading/trailing punctuation and whitespace
    3. Filter: must contain at least one alphabetic character
    4. Filter: must not be purely numeric
    5. Deduplicate by canonical form — merge frequencies and evidence offsets
    6. Apply display form (Title Case for single words, uppercase for acronyms, natural for phrases)
    """

    def normalize(
        self,
        candidates: list[RawCandidate],
    ) -> list[NormalizedCandidate]:
        """
        Normalise and deduplicate a list of RawCandidates.

        Returns a list of NormalizedCandidate objects, sorted by
        total_frequency descending.
        """
        # Step 1: build canonical → accumulated candidate dict
        merged: dict[str, NormalizedCandidate] = {}

        for raw in candidates:
            canonical = self._canonicalize(raw.text)
            if not self._is_valid(canonical):
                continue

            first_occ = getattr(raw, "first_occurrence", 0)
            last_occ = getattr(raw, "last_occurrence", 0)

            if canonical in merged:
                existing = merged[canonical]
                merged[canonical] = NormalizedCandidate(
                    canonical=canonical,
                    display=existing.display,
                    ngram_size=existing.ngram_size,
                    total_frequency=existing.total_frequency + raw.total_frequency,
                    in_title=existing.in_title or raw.in_title,
                    source_id=existing.source_id,
                    first_occurrence=min(existing.first_occurrence, first_occ),
                    last_occurrence=max(existing.last_occurrence, last_occ),
                )
            else:
                merged[canonical] = NormalizedCandidate(
                    canonical=canonical,
                    display=self._display_form(canonical, raw.ngram_size),
                    ngram_size=raw.ngram_size,
                    total_frequency=raw.total_frequency,
                    in_title=raw.in_title,
                    source_id=raw.source_id,
                    first_occurrence=first_occ,
                    last_occurrence=last_occ,
                )

        result = list(merged.values())
        result.sort(key=lambda c: c.total_frequency, reverse=True)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _canonicalize(text: str) -> str:
        """Return the canonical (lowercase, stripped) form of *text*."""
        return text.lower().strip(" \t\n\r-'\"")

    @staticmethod
    def _is_valid(canonical: str) -> bool:
        """Return True if *canonical* should be retained."""
        if not canonical:
            return False
        if _NUMERIC_ONLY.match(canonical):
            return False
        if not _HAS_ALPHA.search(canonical):
            return False
        # Reject single character or short non-acronym tokens (< 3 chars unless in recognized technical terms)
        if len(canonical) < 3 and canonical not in _RECOGNIZED_ACRONYMS:
            return False
        return True

    @staticmethod
    def _display_form(canonical: str, ngram_size: int) -> str:
        """
        Compute a human-readable display form.

        - Acronyms: Uppercase (e.g. "ai" → "AI", "rag" → "RAG")
        - Single-word concepts: Title Case (e.g. "attention" → "Attention")
        - Multi-word concepts: natural canonical (e.g. "gradient descent")
        """
        if canonical in _RECOGNIZED_ACRONYMS:
            return canonical.upper()
        if ngram_size == 1:
            return canonical.title()
        return canonical
