"""
Temporal analytics, time-bucketed event series, and deterministic trend detection.
Phase 9 — Research Analytics & Pattern Intelligence
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from orvia.app.analysis.analytics.models import (
    ConceptPatternMetrics,
    TemporalDataPoint,
    TemporalTrends,
    TrendStatus,
)
from orvia.app.core.database import DatabaseManager


class TemporalAnalyticsCalculator:
    """Computes time-bucketed event aggregations and deterministic concept trends."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get_temporal_trends(self, interval: str = "daily", limit: int = 30) -> TemporalTrends:
        """
        Aggregate sources, evidence, investigations, and concept observations over time.
        interval: 'daily' | 'weekly' | 'monthly'
        """
        date_format = "%Y-%m-%d"
        if interval == "monthly":
            date_format = "%Y-%m"
        elif interval == "weekly":
            date_format = "%Y-W%W"

        # 1. Sources timeline
        source_rows = self._db.fetchall(
            f"""
            SELECT strftime('{date_format}', created_at) AS period, COUNT(*) AS count
            FROM sources
            WHERE created_at IS NOT NULL AND created_at != ''
            GROUP BY period
            ORDER BY period ASC;
            """
        )

        # 2. Evidence timeline
        evidence_rows = self._db.fetchall(
            f"""
            SELECT strftime('{date_format}', created_at) AS period, COUNT(*) AS count
            FROM investigation_evidence
            WHERE created_at IS NOT NULL AND created_at != ''
            GROUP BY period
            ORDER BY period ASC;
            """
        )

        # 3. Investigations timeline
        inv_rows = self._db.fetchall(
            f"""
            SELECT strftime('{date_format}', created_at) AS period, COUNT(*) AS count
            FROM investigations
            WHERE created_at IS NOT NULL AND created_at != ''
            GROUP BY period
            ORDER BY period ASC;
            """
        )

        # 4. Concept observations timeline
        csl_rows = self._db.fetchall(
            f"""
            SELECT strftime('{date_format}', first_seen_at) AS period, COUNT(*) AS count
            FROM concept_source_links
            WHERE first_seen_at IS NOT NULL AND first_seen_at != ''
            GROUP BY period
            ORDER BY period ASC;
            """
        )

        # Merge into chronological periods
        all_periods = set()
        for r in source_rows + evidence_rows + inv_rows + csl_rows:
            p = r["period"]
            if p:
                all_periods.add(p)

        sorted_periods = sorted(all_periods)
        if limit and len(sorted_periods) > limit:
            sorted_periods = sorted_periods[-limit:]

        source_map = {r["period"]: int(r["count"]) for r in source_rows if r["period"]}
        ev_map = {r["period"]: int(r["count"]) for r in evidence_rows if r["period"]}
        inv_map = {r["period"]: int(r["count"]) for r in inv_rows if r["period"]}
        csl_map = {r["period"]: int(r["count"]) for r in csl_rows if r["period"]}

        data_points = []
        for p in sorted_periods:
            data_points.append(
                TemporalDataPoint(
                    period=p,
                    sources_added=source_map.get(p, 0),
                    evidence_recorded=ev_map.get(p, 0),
                    investigations_created=inv_map.get(p, 0),
                    concept_observations=csl_map.get(p, 0),
                )
            )

        summary = (
            f"Observed research activity across {len(data_points)} chronological intervals."
            if data_points
            else "No time-stamped events recorded in collection yet."
        )

        return TemporalTrends(
            interval=interval,
            data_points=data_points,
            summary=summary,
        )

    def calculate_concept_trend(
        self,
        concept_id: str,
        concept_source_ids: set[str],
        all_source_timestamps: dict[str, datetime],
    ) -> tuple[str, str, Optional[float]]:
        """
        Determines the directional frequency trend of a concept across the collection timeline.
        Returns: (trend_status, trend_description, ratio)

        Rule 18 / 44: If there is not enough historical data (e.g. fewer than 2 sources in collection,
        or timestamps span less than 1 second, or zero sources containing concept):
        Returns TrendStatus.INSUFFICIENT_HISTORY.
        """
        if len(all_source_timestamps) < 2 or not concept_source_ids:
            return (
                TrendStatus.INSUFFICIENT_HISTORY.value,
                "More time-based observations are required to calculate a meaningful trend.",
                None,
            )

        # Sort all sources chronologically
        sorted_sources = sorted(
            all_source_timestamps.keys(),
            key=lambda sid: all_source_timestamps[sid],
        )

        earliest = all_source_timestamps[sorted_sources[0]]
        latest = all_source_timestamps[sorted_sources[-1]]
        # If all sources have the exact same timestamp down to the second, cannot split time
        if (latest - earliest).total_seconds() < 1:
            return (
                TrendStatus.INSUFFICIENT_HISTORY.value,
                "More time-based observations are required to calculate a meaningful trend.",
                None,
            )

        midpoint_idx = len(sorted_sources) // 2
        older_half = set(sorted_sources[:midpoint_idx])
        newer_half = set(sorted_sources[midpoint_idx:])

        old_count = len(concept_source_ids & older_half)
        new_count = len(concept_source_ids & newer_half)

        old_rate = old_count / max(len(older_half), 1)
        new_rate = new_count / max(len(newer_half), 1)

        if old_rate == 0 and new_rate > 0:
            return (
                TrendStatus.RECENTLY_DETECTED.value,
                f"Observed in {new_count} recent source{'s' if new_count > 1 else ''}, not in earlier literature.",
                None,
            )

        if old_rate == 0 and new_rate == 0:
            return (
                TrendStatus.INSUFFICIENT_HISTORY.value,
                "No chronological distribution available.",
                None,
            )

        ratio = new_rate / old_rate
        if ratio >= 1.5:
            pct_inc = round((ratio - 1.0) * 100)
            return (
                TrendStatus.GROWING.value,
                f"Observed frequency increased by {pct_inc}% across recent research documents.",
                round(ratio, 2),
            )
        elif ratio <= 0.5:
            pct_dec = round((1.0 - ratio) * 100)
            return (
                TrendStatus.DECLINING.value,
                f"Observed frequency decreased by {pct_dec}% compared to earlier documents.",
                round(ratio, 2),
            )
        else:
            return (
                TrendStatus.STABLE.value,
                f"Consistently observed across older ({old_count}) and newer ({new_count}) sources.",
                round(ratio, 2),
            )
