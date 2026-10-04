"""
ConceptStatistics — Phase 6 Concept Intelligence

Computes collection-level statistics for concepts:
  - Source × Concept matrix (which sources contain which concepts)
  - Coverage percentage per concept
  - Trend classification: Emerging / Growing / Stable / Declining
  - Collection-wide summary metrics

Trend classification algorithm:
  - Sort sources by created_at timestamp.
  - Divide sources into two halves (older half / newer half).
  - Compare occurrence rates in each half.
  - Classify based on ratio of new-half rate to old-half rate.

No external APIs. No ML. Fully deterministic and explainable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# Trend thresholds (ratio of new-half-rate / old-half-rate)
_EMERGING_THRESHOLD = 5.0    # 5× more in newer sources  → Emerging
_GROWING_THRESHOLD = 1.5     # 1.5× more                 → Growing
_DECLINING_THRESHOLD = 0.5   # < 0.5× rate               → Declining
# Otherwise: Stable


@dataclass
class ConceptTrend:
    """Trend information for a concept over the collection timeline."""

    concept_id: str
    label: str          # "Emerging" | "Growing" | "Stable" | "Declining"
    old_half_count: int # sources in older half that contain concept
    new_half_count: int # sources in newer half that contain concept
    ratio: float        # new_rate / old_rate (or inf if old_rate == 0)

    @property
    def trend_description(self) -> str:
        """Human-readable trend description for the UI."""
        if self.label == "Emerging":
            return f"Observed in {self.new_half_count} recent sources, rarely in earlier ones"
        if self.label == "Growing":
            return f"Frequency increased from {self.old_half_count} to {self.new_half_count} sources"
        if self.label == "Declining":
            return f"Appeared in {self.old_half_count} older sources, less in recent ones"
        return f"Consistently detected across {self.old_half_count + self.new_half_count} sources"


@dataclass
class CollectionSummary:
    """Summary statistics for the concept collection as a whole."""

    total_concepts: int = 0
    total_sources_analyzed: int = 0
    avg_concepts_per_source: float = 0.0
    top_concepts: list[dict] = field(default_factory=list)   # [{id, name, source_count}]
    emerging_concepts: list[dict] = field(default_factory=list)
    recently_detected: list[dict] = field(default_factory=list)


class ConceptStatistics:
    """
    Calculates collection-level statistics for detected concepts.

    Usage::

        stats = ConceptStatistics()
        # concept_source_map: {concept_id: set[source_id]}
        # source_timestamps: {source_id: datetime}
        trends = stats.calculate_trends(concept_source_map, source_timestamps)
        summary = stats.collection_summary(concept_source_map, concept_names)
    """

    def calculate_trends(
        self,
        concept_source_map: dict[str, set[str]],
        source_timestamps: dict[str, datetime],
    ) -> dict[str, ConceptTrend]:
        """
        Calculate trend labels for each concept.

        Parameters
        ----------
        concept_source_map : dict[str, set[str]]
            concept_id → set of source_ids.
        source_timestamps : dict[str, datetime]
            source_id → created_at datetime.

        Returns
        -------
        dict[str, ConceptTrend]
            concept_id → ConceptTrend
        """
        # Sort all sources by timestamp
        all_sources = sorted(
            source_timestamps.keys(),
            key=lambda sid: source_timestamps.get(sid, datetime.min),
        )
        if len(all_sources) < 2:
            # Not enough data to classify trends
            return {
                cid: ConceptTrend(
                    concept_id=cid,
                    label="Stable",
                    old_half_count=0,
                    new_half_count=len(sids),
                    ratio=1.0,
                )
                for cid, sids in concept_source_map.items()
            }

        mid = len(all_sources) // 2
        older_half = set(all_sources[:mid])
        newer_half = set(all_sources[mid:])

        trends: dict[str, ConceptTrend] = {}
        for cid, source_ids in concept_source_map.items():
            old_count = len(source_ids & older_half)
            new_count = len(source_ids & newer_half)

            old_rate = old_count / max(len(older_half), 1)
            new_rate = new_count / max(len(newer_half), 1)

            if old_rate == 0 and new_rate > 0:
                ratio = float("inf")
                label = "Emerging"
            elif old_rate == 0 and new_rate == 0:
                ratio = 1.0
                label = "Stable"
            else:
                ratio = new_rate / old_rate if old_rate > 0 else 0.0
                if ratio >= _EMERGING_THRESHOLD:
                    label = "Emerging"
                elif ratio >= _GROWING_THRESHOLD:
                    label = "Growing"
                elif ratio < _DECLINING_THRESHOLD:
                    label = "Declining"
                else:
                    label = "Stable"

            trends[cid] = ConceptTrend(
                concept_id=cid,
                label=label,
                old_half_count=old_count,
                new_half_count=new_count,
                ratio=round(ratio, 3) if ratio != float("inf") else 999.0,
            )
        return trends

    def collection_summary(
        self,
        concept_source_map: dict[str, set[str]],
        concept_names: dict[str, str],      # concept_id → display name
        total_sources: int = 0,
        analyzed_sources: int = 0,
        limit_top: int = 10,
        limit_recent: int = 5,
        trends: Optional[dict[str, "ConceptTrend"]] = None,
    ) -> CollectionSummary:
        """
        Build a CollectionSummary for the Overview page.

        Parameters
        ----------
        concept_source_map : dict[str, set[str]]
        concept_names : dict[str, str]
            Maps concept_id → display name.
        total_sources : int
        analyzed_sources : int
        limit_top : int
        limit_recent : int
        trends : optional dict[str, ConceptTrend]
        """
        summary = CollectionSummary(
            total_concepts=len(concept_source_map),
            total_sources_analyzed=analyzed_sources,
        )

        if analyzed_sources > 0:
            total_links = sum(len(v) for v in concept_source_map.values())
            summary.avg_concepts_per_source = round(
                total_links / analyzed_sources, 1
            )

        # Top concepts by source_count
        sorted_by_coverage = sorted(
            concept_source_map.items(),
            key=lambda kv: len(kv[1]),
            reverse=True,
        )
        summary.top_concepts = [
            {
                "id": cid,
                "name": concept_names.get(cid, cid),
                "source_count": len(sids),
            }
            for cid, sids in sorted_by_coverage[:limit_top]
        ]

        # Emerging concepts
        if trends:
            emerging = [
                cid for cid, t in trends.items()
                if t.label in ("Emerging", "Growing")
            ]
            # Sort emerging by new_half_count descending
            emerging.sort(
                key=lambda cid: trends[cid].new_half_count, reverse=True
            )
            summary.emerging_concepts = [
                {
                    "id": cid,
                    "name": concept_names.get(cid, cid),
                    "trend": trends[cid].label,
                    "new_count": trends[cid].new_half_count,
                }
                for cid in emerging[:limit_recent]
            ]

        # Recently detected = top_concepts (already sorted by coverage)
        summary.recently_detected = [
            {
                "id": cid,
                "name": concept_names.get(cid, cid),
                "source_count": len(sids),
            }
            for cid, sids in sorted_by_coverage[:limit_recent]
        ]

        return summary
