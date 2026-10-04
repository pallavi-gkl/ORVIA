"""
ReportSynthesisEngine — deterministic assembly of research reports for Phase 10.

Transforms an investigation's accumulated sources, concepts, evidence, findings,
questions, and analytics into structured, traceable report sections.

Strictly deterministic: Never uses LLMs, embeddings, or external AI APIs.
Never invents facts, citations, evidence, findings, sources, or conclusions.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from orvia.app.reports.models import (
    Report,
    ReportSection,
    ReportSectionType,
    ReportSource,
    ReportEvidence,
    ReportFinding,
    ReportStatus,
)
from orvia.app.reports.citations import CitationManager
from orvia.app.reports.quality import ReportQualityAnalyzer

logger = logging.getLogger(__name__)


class ReportSynthesisEngine:
    """
    Deterministically synthesizes a complete research report from an Investigation.
    Uses only data explicitly recorded in the ORVIA SQLite database.
    """

    def __init__(
        self,
        db: Any,
        investigation_repo: Any,
        source_repo: Any,
        concept_repo: Any,
        analytics_service: Optional[Any] = None,
    ) -> None:
        self._db = db
        self._inv_repo = investigation_repo
        self._src_repo = source_repo
        self._concept_repo = concept_repo
        self._analytics_svc = analytics_service

    def synthesize(
        self,
        investigation_id: str,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        selected_sections: Optional[list[str]] = None,
    ) -> tuple[Report, list[ReportSection], list[ReportSource], list[ReportEvidence], list[ReportFinding]]:
        """
        Assemble a complete report and all child components from the specified investigation.
        """
        inv = self._inv_repo.find_by_id(investigation_id)
        if not inv:
            raise ValueError(f"Investigation '{investigation_id}' not found.")

        # 1. Fetch all investigation components via actual repo method names
        inv_sources = self._inv_repo.get_sources(investigation_id)
        sources: list[Any] = []
        for isrc in inv_sources:
            s = self._src_repo.find_by_id(isrc.source_id)
            if s:
                sources.append(s)

        inv_concepts = self._inv_repo.get_concepts(investigation_id)
        concepts: list[Any] = []
        for icpt in inv_concepts:
            c = self._concept_repo.find_by_id(icpt.concept_id)
            if c:
                concepts.append(c)

        evidence_list = self._inv_repo.get_evidence_for_investigation(investigation_id)
        findings_list = self._inv_repo.get_findings(investigation_id)
        questions_list = self._inv_repo.get_questions(investigation_id)

        # Build finding -> evidence mapping
        finding_evidence_map: dict[str, list[str]] = {}
        for f in findings_list:
            evs = self._inv_repo.get_evidence_for_finding(f.id)
            finding_evidence_map[f.id] = [e.id for e in evs]

        # evidence id -> evidence object
        evidence_by_id: dict[str, Any] = {e.id: e for e in evidence_list}

        # 2. Assign stable citation labels to sources [1], [2], etc.
        source_citation_map = CitationManager.generate_source_citations(sources)

        # 3. Create Report Entity
        report_title = title.strip() if title and title.strip() else f"Research Report: {inv.title}"
        report_subtitle = (
            subtitle.strip()
            if subtitle and subtitle.strip()
            else f"Inquiry into: {inv.research_question}"
        )

        report = Report(
            investigation_id=inv.id,
            title=report_title,
            subtitle=report_subtitle,
            summary=(
                f"Synthesized research report examining {len(sources)} source(s), "
                f"{len(evidence_list)} evidence record(s), and {len(findings_list)} finding(s)."
            ),
            status=ReportStatus.DRAFT.value,
            version=1,
            metadata={"source_investigation_title": inv.title},
        )

        # 4. Build ReportSources
        report_sources: list[ReportSource] = []
        for idx, src in enumerate(sources):
            report_sources.append(
                ReportSource(
                    report_id=report.id,
                    source_id=src.id,
                    citation_label=source_citation_map.get(src.id, f"[{idx + 1}]"),
                    position=idx,
                )
            )

        # 5. Build ReportEvidence
        report_evidence: list[ReportEvidence] = []
        for idx, ev in enumerate(evidence_list):
            src_label = source_citation_map.get(ev.source_id, "[?]")
            cit_label = CitationManager.format_evidence_citation(src_label, ev.location)
            report_evidence.append(
                ReportEvidence(
                    report_id=report.id,
                    evidence_id=ev.id,
                    citation_label=cit_label,
                    position=idx,
                )
            )

        # 6. Build ReportFindings
        report_findings: list[ReportFinding] = []
        for idx, f in enumerate(findings_list):
            report_findings.append(
                ReportFinding(
                    report_id=report.id,
                    finding_id=f.id,
                    position=idx,
                )
            )

        # 7. Build Structured Sections (default order)
        all_section_types = [
            ReportSectionType.EXECUTIVE_SUMMARY.value,
            ReportSectionType.RESEARCH_QUESTION.value,
            ReportSectionType.SCOPE.value,
            ReportSectionType.SOURCES.value,
            ReportSectionType.KEY_CONCEPTS.value,
            ReportSectionType.EVIDENCE.value,
            ReportSectionType.FINDINGS.value,
            ReportSectionType.PATTERNS.value,
            ReportSectionType.COMPARISON.value,
            ReportSectionType.OPEN_QUESTIONS.value,
            ReportSectionType.LIMITATIONS.value,
            ReportSectionType.CONCLUSION.value,
            ReportSectionType.REFERENCES.value,
        ]
        active_types = selected_sections if selected_sections is not None else all_section_types
        sections: list[ReportSection] = []

        position = 0
        for s_type in active_types:
            sec = self._build_section(
                report_id=report.id,
                section_type=s_type,
                position=position,
                inv=inv,
                sources=sources,
                concepts=concepts,
                evidence_list=evidence_list,
                findings_list=findings_list,
                questions_list=questions_list,
                finding_evidence_map=finding_evidence_map,
                source_citation_map=source_citation_map,
                evidence_by_id=evidence_by_id,
            )
            if sec:
                sections.append(sec)
                position += 1

        return report, sections, report_sources, report_evidence, report_findings

    # -------------------------------------------------------------------------
    # Section routing dispatcher
    # -------------------------------------------------------------------------

    def _build_section(self, report_id, section_type, position, inv, sources,
                       concepts, evidence_list, findings_list, questions_list,
                       finding_evidence_map, source_citation_map, evidence_by_id):
        """Route to the correct section builder."""
        st = section_type
        if st == ReportSectionType.EXECUTIVE_SUMMARY.value:
            return self._build_executive_summary(report_id, position, inv, sources,
                                                 evidence_list, findings_list,
                                                 questions_list, finding_evidence_map)
        elif st == ReportSectionType.RESEARCH_QUESTION.value:
            return self._build_research_question(report_id, position, inv)
        elif st == ReportSectionType.SCOPE.value:
            return self._build_scope(report_id, position, inv, sources, concepts)
        elif st == ReportSectionType.SOURCES.value:
            return self._build_sources(report_id, position, sources, source_citation_map)
        elif st == ReportSectionType.KEY_CONCEPTS.value:
            return self._build_key_concepts(report_id, position, concepts, sources)
        elif st == ReportSectionType.EVIDENCE.value:
            return self._build_evidence(report_id, position, evidence_list, source_citation_map)
        elif st == ReportSectionType.FINDINGS.value:
            return self._build_findings(report_id, position, findings_list,
                                        finding_evidence_map, source_citation_map, evidence_by_id)
        elif st == ReportSectionType.PATTERNS.value:
            return self._build_patterns(report_id, position)
        elif st == ReportSectionType.COMPARISON.value:
            return self._build_comparison(report_id, position, sources)
        elif st == ReportSectionType.OPEN_QUESTIONS.value:
            return self._build_open_questions(report_id, position, questions_list)
        elif st == ReportSectionType.LIMITATIONS.value:
            return self._build_limitations(report_id, position, sources, evidence_list,
                                           findings_list, questions_list, finding_evidence_map, concepts)
        elif st == ReportSectionType.CONCLUSION.value:
            return self._build_conclusion(report_id, position, sources, evidence_list,
                                          findings_list, questions_list)
        elif st == ReportSectionType.REFERENCES.value:
            return self._build_references(report_id, position, sources, source_citation_map)
        return None

    # -------------------------------------------------------------------------
    # Individual Section Generators
    # -------------------------------------------------------------------------

    def _build_executive_summary(self, report_id, position, inv, sources,
                                  evidence_list, findings_list, questions_list,
                                  finding_evidence_map):
        supported = sum(1 for f in findings_list if len(finding_evidence_map.get(f.id, [])) > 0)
        unsupported = len(findings_list) - supported
        open_q = sum(1 for q in questions_list if (q.status or "OPEN").upper() != "RESOLVED")
        lines = [
            f"This research report documents empirical findings from the investigation **\"{inv.title}\"**.",
            "",
            f"**Guiding Inquiry:** {inv.research_question}",
            "",
            "### Evidentiary Summary",
            f"- **Sources Evaluated:** {len(sources)} primary document(s)",
            f"- **Evidence Items Recorded:** {len(evidence_list)} verified excerpt(s)",
            f"- **Findings Formulated:** {len(findings_list)} synthesized claim(s) "
            f"({supported} supported by linked evidence, {unsupported} requiring corroboration)",
            f"- **Open Questions Remaining:** {open_q} unresolved inquiry thread(s)",
            "",
        ]
        if not evidence_list:
            lines.append("> **Note on Evidence:** Limited evidence was recorded for this question. Conclusions remain preliminary.")
        elif supported == len(findings_list) and len(findings_list) > 0 and open_q == 0:
            lines.append("> **Research Maturity:** All current findings are backed by user-linked empirical evidence, and all tracked questions have been addressed.")
        else:
            lines.append("> **Research Maturity:** Active inquiry with evidence-supported observations alongside identified knowledge gaps.")
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.EXECUTIVE_SUMMARY.value,
            title="Executive Summary", position=position, content="\n".join(lines),
        )

    def _build_research_question(self, report_id, position, inv):
        lines = [
            "### Primary Research Question",
            f"> **{inv.research_question}**",
            "",
            "### Investigation Context",
            inv.description.strip() if (inv.description or "").strip() else "No detailed description was recorded for this investigation.",
        ]
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.RESEARCH_QUESTION.value,
            title="Research Question", position=position, content="\n".join(lines),
        )

    def _build_scope(self, report_id, position, inv, sources, concepts):
        lines = [
            "This investigation was conducted across a defined corpus of local research sources and conceptual domains.",
            "",
            f"- **Investigation Status:** `{inv.status.upper()}`",
            f"- **Attached Sources:** {len(sources)} document(s)",
            f"- **Tracked Domain Concepts:** {len(concepts)} concept(s)",
        ]
        if sources:
            src_types: dict[str, int] = {}
            for s in sources:
                st = (s.file_type or "TEXT").upper()
                src_types[st] = src_types.get(st, 0) + 1
            type_str = ", ".join(f"{count} {t}" for t, count in src_types.items())
            lines.append(f"- **Source Formats:** {type_str}")
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.SCOPE.value,
            title="Scope & Methodology", position=position, content="\n".join(lines),
        )

    def _build_sources(self, report_id, position, sources, source_citation_map):
        if not sources:
            content = "No sources are attached to this investigation."
        else:
            lines = [
                "The following primary documents form the evidentiary foundation of this report:",
                "",
                "| Citation | Document Title | Format | Word Count |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for s in sources:
                label = source_citation_map.get(s.id, "[?]")
                fmt = (s.file_type or "DOC").upper()
                wc = f"{s.word_count:,}" if s.word_count else "—"
                lines.append(f"| **{label}** | {s.title} | {fmt} | {wc} |")
            content = "\n".join(lines)
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.SOURCES.value,
            title="Evaluated Sources", position=position, content=content,
        )

    def _build_key_concepts(self, report_id, position, concepts, sources):
        if not concepts:
            content = "No concepts were explicitly tracked for this investigation."
        else:
            lines = [
                "Key conceptual entities observed across the evaluated corpus:",
                "",
                "| Concept | Frequency | Role |",
                "| :--- | :--- | :--- |",
            ]
            for c in concepts:
                freq = c.frequency if hasattr(c, "frequency") else "—"
                lines.append(f"| **{c.name}** | {freq} | — |")
            content = "\n".join(lines)
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.KEY_CONCEPTS.value,
            title="Key Concepts", position=position, content=content,
        )

    def _build_evidence(self, report_id, position, evidence_list, source_citation_map):
        if not evidence_list:
            content = "No empirical evidence items have been attached to this investigation yet."
        else:
            lines = ["Verified empirical extractions linked directly to primary documents:", ""]
            for ev in evidence_list:
                src_label = source_citation_map.get(ev.source_id, "[?]")
                cit_label = CitationManager.format_evidence_citation(src_label, ev.location)
                ev_type = (ev.evidence_type or "OBSERVATION").upper()
                lines.append(f"#### {ev.title or ev_type} — {cit_label}")
                lines.append(f"**Classification:** `{ev_type}` | **Confidence:** {ev.confidence:.1f}")
                lines.append(f"\n> \"{ev.statement}\"")
                if ev.excerpt and ev.excerpt.strip():
                    lines.append(f"\n*Primary Excerpt:* *\"{ev.excerpt.strip()}\"*")
                if ev.notes:
                    lines.append(f"\n*Analyst Notes:* {ev.notes}")
                lines.append("\n---\n")
            content = "\n".join(lines)
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.EVIDENCE.value,
            title="Evidence & Observations", position=position, content=content,
        )

    def _build_findings(self, report_id, position, findings_list, finding_evidence_map,
                         source_citation_map, evidence_by_id):
        if not findings_list:
            content = "No synthesized findings have been recorded for this investigation."
        else:
            lines = ["Synthesized analytical claims, classified by evidentiary support status:", ""]
            for f in findings_list:
                f_status = (f.status or "DRAFT").upper()
                ev_ids = finding_evidence_map.get(f.id, [])
                if f_status == "SUPPORTED":
                    status_display = "Supported by linked evidence"
                elif f_status == "NEEDS_EVIDENCE":
                    status_display = "Requires corroborating evidence"
                elif f_status == "REVISED":
                    status_display = "Revised claim"
                else:
                    status_display = "Draft finding"
                lines.append(f"### {f.title}")
                lines.append(f"**Status:** `{status_display}`\n")
                lines.append(f"{f.statement}\n")
                if ev_ids:
                    cit_labels = []
                    for eid in ev_ids:
                        ev = evidence_by_id.get(eid)
                        if ev:
                            s_label = source_citation_map.get(ev.source_id, "[?]")
                            cit_labels.append(CitationManager.format_evidence_citation(s_label, ev.location))
                    cit_str = ", ".join(cit_labels) if cit_labels else "Evidence linked"
                    lines.append(f"- **Supporting Evidence ({len(ev_ids)}):** {cit_str}")
                else:
                    lines.append("- **Supporting Evidence:** *None linked. This claim requires empirical validation.*")
                lines.append("\n---\n")
            content = "\n".join(lines)
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.FINDINGS.value,
            title="Findings & Synthesis", position=position, content=content,
        )

    def _build_patterns(self, report_id, position):
        if self._analytics_svc:
            try:
                patterns = self._analytics_svc.get_patterns(limit=6)
            except Exception:
                patterns = []
        else:
            patterns = []
        if not patterns:
            content = "No strong multi-source patterns met the detection thresholds for this dataset."
        else:
            lines = ["Deterministic structural patterns observed across the research collection:", ""]
            for p in patterns:
                lines.append(f"- **{p.title}** (`{p.severity}`)")
                lines.append(f"  {p.description}")
                lines.append(f"  *Basis:* {p.explanation}")
                lines.append("")
            content = "\n".join(lines)
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.PATTERNS.value,
            title="Observed Patterns", position=position, content=content,
        )

    def _build_comparison(self, report_id, position, sources):
        if len(sources) < 2:
            content = "Cross-source comparison requires at least two attached sources."
        else:
            s1, s2 = sources[0], sources[1]
            overlap = None
            if self._analytics_svc:
                try:
                    overlap = self._analytics_svc.compare_sources(s1.id, s2.id)
                except Exception:
                    pass
            if overlap:
                shared_str = ", ".join(overlap.shared_concepts[:10]) if overlap.shared_concepts else "None"
                uniq_a_str = ", ".join(overlap.unique_concepts_a[:6]) if overlap.unique_concepts_a else "None"
                uniq_b_str = ", ".join(overlap.unique_concepts_b[:6]) if overlap.unique_concepts_b else "None"
                lines = [
                    f"### Cross-Source Comparison: *{s1.title}* vs *{s2.title}*",
                    "",
                    f"- **Jaccard Concept Overlap:** **{overlap.jaccard_overlap * 100:.1f}%**",
                    f"- **Shared Concepts ({len(overlap.shared_concepts)}):** {shared_str}",
                    f"- **Unique to {s1.title} ({len(overlap.unique_concepts_a)}):** {uniq_a_str}",
                    f"- **Unique to {s2.title} ({len(overlap.unique_concepts_b)}):** {uniq_b_str}",
                    "",
                    "*Note: Overlap measures shared vocabulary concepts and does not infer semantic similarity.*",
                ]
                content = "\n".join(lines)
            else:
                content = f"Comparison between *{s1.title}* and *{s2.title}* could not be calculated with current data."
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.COMPARISON.value,
            title="Cross-Source Comparison", position=position, content=content,
        )

    def _build_open_questions(self, report_id, position, questions_list):
        if not questions_list:
            content = "No subsidiary research questions were logged for this inquiry."
        else:
            lines = ["Unresolved research gaps and ongoing inquiries:", ""]
            for q in questions_list:
                status = (q.status or "OPEN").upper()
                lines.append(f"- `[{status}]` **{q.question}**")
                if q.resolution_note:
                    lines.append(f"  *Resolution Note:* {q.resolution_note}")
            content = "\n".join(lines)
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.OPEN_QUESTIONS.value,
            title="Open Questions & Gaps", position=position, content=content,
        )

    def _build_limitations(self, report_id, position, sources, evidence_list,
                            findings_list, questions_list, finding_evidence_map, concepts):
        cpt_counts = {c.id: 1 for c in concepts}
        metrics = ReportQualityAnalyzer.analyze(
            sources=sources,
            evidence_list=evidence_list,
            findings_list=findings_list,
            finding_evidence_map=finding_evidence_map,
            questions=questions_list,
            concepts=concepts,
            concept_source_counts=cpt_counts,
        )
        lines = [
            "In accordance with research integrity principles, the following structural limitations are noted:",
            "",
        ]
        if metrics.gaps:
            for g in metrics.gaps:
                lines.append(f"- {g}")
        else:
            lines.append("- No critical evidence gaps were identified in this investigation.")
        lines.extend([
            "",
            "**Methodological Boundary:** All findings are strictly bounded by the ingested primary corpus. "
            "ORVIA does not interpolate facts or infer conclusions beyond the explicit records.",
        ])
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.LIMITATIONS.value,
            title="Limitations & Methodological Boundary", position=position,
            content="\n".join(lines),
        )

    def _build_conclusion(self, report_id, position, sources, evidence_list,
                           findings_list, questions_list):
        supported_count = sum(1 for f in findings_list if (f.status or "").upper() == "SUPPORTED")
        open_q = sum(1 for q in questions_list if (q.status or "OPEN").upper() != "RESOLVED")
        lines = [
            f"Based on the **{len(sources)} source(s)** and **{len(evidence_list)} evidence record(s)** evaluated, "
            f"**{supported_count} of {len(findings_list)} finding(s)** have established empirical grounding within this collection.",
            "",
            "These findings reflect verified observations within the provided literature. "
            "Remaining open questions require further primary source ingestion and corroboration before definitive closure.",
        ]
        if open_q > 0:
            lines.append(f"\n*{open_q} research question(s) remain unresolved and are documented in the Open Questions section.*")
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.CONCLUSION.value,
            title="Conclusion", position=position, content="\n".join(lines),
        )

    def _build_references(self, report_id, position, sources, source_citation_map):
        if not sources:
            content = "No sources referenced."
        else:
            lines = ["Primary literature and reference materials cited in this report:", ""]
            for s in sources:
                label = source_citation_map.get(s.id, "[?]")
                lines.append(f"- {CitationManager.format_reference_entry(label, s)}")
            content = "\n".join(lines)
        return ReportSection(
            report_id=report_id, section_type=ReportSectionType.REFERENCES.value,
            title="References", position=position, content=content,
        )
