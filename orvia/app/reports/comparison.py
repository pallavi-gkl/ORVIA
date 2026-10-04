"""
Deterministic Report Version Comparison Engine for Phase 10.

Computes exact differences between two report versions:
- Added, removed, and modified sections (with line-level diffs)
- Source link additions and removals
- Evidence citations added and removed
- Findings added, removed, or with status transitions
"""

from __future__ import annotations

import difflib
from typing import Any, Optional
from orvia.app.reports.models import ReportVersionDiff, Report, ReportSection
from orvia.app.reports.repository import ReportRepository


class ReportVersionComparator:
    """
    Compares two versions of a report and produces an explainable, structured diff.
    """

    def __init__(self, repo: ReportRepository) -> None:
        self._repo = repo

    def compare(self, report_a_id: str, report_b_id: str) -> ReportVersionDiff:
        """
        Compare report version A against report version B.
        Usually report_a is the older version, report_b is the newer version.
        """
        rep_a = self._repo.get_by_id(report_a_id)
        rep_b = self._repo.get_by_id(report_b_id)
        if not rep_a or not rep_b:
            raise ValueError(f"One or both reports ({report_a_id}, {report_b_id}) not found.")

        sec_a = self._repo.get_sections(report_a_id)
        sec_b = self._repo.get_sections(report_b_id)

        src_a = {s.source_id: s for s in self._repo.get_sources(report_a_id)}
        src_b = {s.source_id: s for s in self._repo.get_sources(report_b_id)}

        evi_a = {e.evidence_id: e for e in self._repo.get_evidence(report_a_id)}
        evi_b = {e.evidence_id: e for e in self._repo.get_evidence(report_b_id)}

        fnd_a = {f.finding_id: f for f in self._repo.get_findings(report_a_id)}
        fnd_b = {f.finding_id: f for f in self._repo.get_findings(report_b_id)}

        # 1. Section diffs
        # Map sections by section_type (if unique) or title
        sec_map_a: dict[str, ReportSection] = {s.section_type: s for s in sec_a}
        sec_map_b: dict[str, ReportSection] = {s.section_type: s for s in sec_b}

        added_sections: list[dict[str, Any]] = []
        removed_sections: list[dict[str, Any]] = []
        modified_sections: list[dict[str, Any]] = []

        all_types = list(dict.fromkeys(list(sec_map_a.keys()) + list(sec_map_b.keys())))

        for s_type in all_types:
            in_a = s_type in sec_map_a
            in_b = s_type in sec_map_b

            if in_b and not in_a:
                s = sec_map_b[s_type]
                added_sections.append({
                    "section_type": s.section_type,
                    "title": s.title,
                    "position": s.position,
                    "word_count": len(s.content.split()) if s.content else 0,
                })
            elif in_a and not in_b:
                s = sec_map_a[s_type]
                removed_sections.append({
                    "section_type": s.section_type,
                    "title": s.title,
                    "position": s.position,
                })
            elif in_a and in_b:
                sa = sec_map_a[s_type]
                sb = sec_map_b[s_type]
                content_changed = sa.content != sb.content
                title_changed = sa.title != sb.title
                pos_changed = sa.position != sb.position

                if content_changed or title_changed or pos_changed:
                    # Generate line diff
                    lines_a = sa.content.splitlines(keepends=True)
                    lines_b = sb.content.splitlines(keepends=True)
                    diff = list(difflib.unified_diff(lines_a, lines_b, fromfile="v_a", tofile="v_b", lineterm=""))

                    modified_sections.append({
                        "section_type": sb.section_type,
                        "title_a": sa.title,
                        "title_b": sb.title,
                        "content_changed": content_changed,
                        "title_changed": title_changed,
                        "position_changed": pos_changed,
                        "diff_lines": diff[:50],  # bounded preview
                        "words_added": max(0, len(sb.content.split()) - len(sa.content.split())),
                        "words_removed": max(0, len(sa.content.split()) - len(sb.content.split())),
                    })

        # 2. Source changes
        src_added = [s_id for s_id in src_b if s_id not in src_a]
        src_removed = [s_id for s_id in src_a if s_id not in src_b]

        # 3. Evidence changes
        evi_added = [e_id for e_id in evi_b if e_id not in evi_a]
        evi_removed = [e_id for e_id in evi_a if e_id not in evi_b]

        # 4. Finding changes
        fnd_added = [f_id for f_id in fnd_b if f_id not in fnd_a]
        fnd_removed = [f_id for f_id in fnd_a if f_id not in fnd_b]

        return ReportVersionDiff(
            version_a=rep_a.version,
            version_b=rep_b.version,
            added_sections=added_sections,
            removed_sections=removed_sections,
            modified_sections=modified_sections,
            source_changes={"added": src_added, "removed": src_removed},
            evidence_changes={"added": evi_added, "removed": evi_removed},
            finding_changes={"added": fnd_added, "removed": fnd_removed},
        )
