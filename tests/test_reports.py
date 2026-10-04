"""
Unit and integration test suite for ORVIA Phase 10:
Research Reports & Evidence Synthesis System.

Tests:
- Report & ReportSection domain models, validation, and serialization
- ReportRepository CRUD, queries, and versioning
- Section ordering, addition, editing, and deletion
- CitationManager deterministic [1], [2], [1, location] formatting
- ReportSynthesisEngine deterministic assembly from investigation
- Evidence type integrity (OBSERVATION, FACT, CLAIM, STATISTIC, DEFINITION, EXAMPLE, CONTRAST)
- Finding status integrity (SUPPORTED rendered as "Supported by linked evidence", not "Proven")
- Quality metrics calculation (Evidence, Source, Finding, Citation completeness)
- Research gap detection (unsupported findings, open questions, isolated concepts)
- ReportVersionComparator deterministic diffs (added, removed, modified sections)
- ReportExportService Markdown export with full provenance preservation
- ResearchReportService facade operations
- Web routes (/reports, /reports/<id>) and REST API endpoints (/api/reports/*)
- Verification that unsupported claims are NEVER automatically fabricated
- Provenance chains from Report -> Section -> Finding -> Evidence -> Source
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from orvia.app.core.config import Config
from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import ValidationError
from orvia.app.investigations.models import (
    EvidenceType,
    FindingStatus,
    InvestigationEvidence,
    InvestigationFinding,
    InvestigationQuestion,
    InvestigationSource,
    QuestionStatus,
)
from orvia.app.investigations.repository import InvestigationRepository
from orvia.app.models.concept import Concept
from orvia.app.models.investigation import Investigation
from orvia.app.models.source import Source
from orvia.app.reports.citations import CitationManager
from orvia.app.reports.comparison import ReportVersionComparator
from orvia.app.reports.export import ReportExportService
from orvia.app.reports.models import (
    Report,
    ReportEvidence,
    ReportFinding,
    ReportQualityMetrics,
    ReportSection,
    ReportSectionType,
    ReportSource,
    ReportStatus,
    ReportVersionDiff,
)
from orvia.app.reports.quality import ReportQualityAnalyzer
from orvia.app.reports.repository import ReportRepository
from orvia.app.reports.service import ResearchReportService
from orvia.app.reports.synthesis import ReportSynthesisEngine
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.ui import create_app


class TestReportModelsAndCitations(unittest.TestCase):
    """Unit tests for models, validation, and citation generator."""

    def test_report_validation(self):
        # Valid report
        rep = Report(
            investigation_id="inv-123",
            title="Analysis of Transformers",
            status="DRAFT",
            version=1,
        )
        rep.validate()  # Should not raise

        # Missing title
        with self.assertRaises(ValidationError):
            bad_rep = Report(investigation_id="inv-123", title="", status="DRAFT")
            bad_rep.validate()

        # Missing investigation_id
        with self.assertRaises(ValidationError):
            bad_rep = Report(investigation_id="", title="Valid Title", status="DRAFT")
            bad_rep.validate()

        # Invalid status
        with self.assertRaises(ValidationError):
            bad_rep = Report(investigation_id="inv-123", title="Valid Title", status="MAGIC_STATUS")
            bad_rep.validate()

    def test_report_section_validation(self):
        sec = ReportSection(
            report_id="rep-1",
            section_type="EXECUTIVE_SUMMARY",
            title="Executive Summary",
            position=0,
            content="Summary content...",
        )
        sec.validate()

        # Invalid section type
        with self.assertRaises(ValidationError):
            bad_sec = ReportSection(
                report_id="rep-1",
                section_type="UNKNOWN_SECTION",
                title="Bad Type",
            )
            bad_sec.validate()

    def test_model_serialization_roundtrip(self):
        rep = Report(
            id="rep-roundtrip",
            investigation_id="inv-1",
            title="Roundtrip Test",
            subtitle="Subtitle Test",
            summary="Summary Test",
            status="FINAL",
            version=2,
            metadata={"analyst": "Dr. Smith"},
        )
        data = rep.to_dict()
        restored = Report.from_dict(data)
        self.assertEqual(restored.id, rep.id)
        self.assertEqual(restored.title, rep.title)
        self.assertEqual(restored.status, "FINAL")
        self.assertEqual(restored.version, 2)
        self.assertEqual(restored.metadata.get("analyst"), "Dr. Smith")

    def test_citation_manager(self):
        class DummySource:
            def __init__(self, id, title, author=""):
                self.id = id
                self.title = title
                self.author = author

        s1 = DummySource("s1", "Paper One")
        s2 = DummySource("s2", "Paper Two")
        citations = CitationManager.generate_source_citations([s1, s2])
        self.assertEqual(citations["s1"], "[1]")
        self.assertEqual(citations["s2"], "[2]")

        # Format evidence citations
        ev_cit_exact = CitationManager.format_evidence_citation("[1]", location="p. 14")
        self.assertEqual(ev_cit_exact, "[1, p. 14]")

        ev_cit_sec = CitationManager.format_evidence_citation("[2]", location="Section 3.1")
        self.assertEqual(ev_cit_sec, "[2, Section 3.1]")

        ev_cit_none = CitationManager.format_evidence_citation("[1]", location="")
        self.assertEqual(ev_cit_none, "[1]")

        # Reference entry
        ref = CitationManager.format_reference_entry("[1]", s1)
        self.assertIn("[1]", ref)
        self.assertIn("Paper One", ref)


class TestReportRepositoryAndVersioning(unittest.TestCase):
    """Unit tests for ReportRepository database operations and version branching."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_repo.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()

        self.inv_repo = InvestigationRepository(self.db)
        self.report_repo = ReportRepository(self.db)

        # Create dummy investigation
        self.inv = Investigation(
            id="inv-repo-test",
            title="Attention Mechanisms Inquiry",
            research_question="How does multi-head attention scale?",
            status="active",
        )
        self.inv_repo.save(self.inv)

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_report_crud(self):
        rep = Report(
            id="rep-crud-1",
            investigation_id=self.inv.id,
            title="Report 1",
            subtitle="Initial draft",
            status="DRAFT",
            version=1,
        )
        self.report_repo.create(rep)

        fetched = self.report_repo.get_by_id("rep-crud-1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "Report 1")

        # Update
        fetched.title = "Report 1 Updated"
        fetched.status = "IN_REVIEW"
        self.report_repo.update(fetched)

        updated = self.report_repo.get_by_id("rep-crud-1")
        self.assertEqual(updated.title, "Report 1 Updated")
        self.assertEqual(updated.status, "IN_REVIEW")

        # List & Count
        reps = self.report_repo.list()
        self.assertEqual(len(reps), 1)
        self.assertEqual(self.report_repo.count(), 1)
        self.assertEqual(self.report_repo.count(status="IN_REVIEW"), 1)
        self.assertEqual(self.report_repo.count(status="FINAL"), 0)

        # Delete
        deleted = self.report_repo.delete("rep-crud-1")
        self.assertTrue(deleted)
        self.assertIsNone(self.report_repo.get_by_id("rep-crud-1"))

    def test_section_management(self):
        rep = Report(
            id="rep-sec-test",
            investigation_id=self.inv.id,
            title="Section Test Report",
            status="DRAFT",
        )
        self.report_repo.create(rep)

        s1 = ReportSection(
            id="sec-1",
            report_id=rep.id,
            section_type="EXECUTIVE_SUMMARY",
            title="Executive Summary",
            position=0,
            content="Summary content",
        )
        s2 = ReportSection(
            id="sec-2",
            report_id=rep.id,
            section_type="FINDINGS",
            title="Findings",
            position=1,
            content="Findings content",
        )
        self.report_repo.add_section(s1)
        self.report_repo.add_section(s2)

        sections = self.report_repo.get_sections(rep.id)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].title, "Executive Summary")
        self.assertEqual(sections[1].title, "Findings")

        # Reorder
        self.report_repo.reorder_sections(rep.id, ["sec-2", "sec-1"])
        reordered = self.report_repo.get_sections(rep.id)
        self.assertEqual(reordered[0].id, "sec-2")
        self.assertEqual(reordered[1].id, "sec-1")

        # Delete section
        self.report_repo.delete_section("sec-1")
        remaining = self.report_repo.get_sections(rep.id)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].id, "sec-2")

    def test_versioning_and_snapshots(self):
        rep_v1 = Report(
            id="rep-ver-1",
            investigation_id=self.inv.id,
            title="Base Version",
            status="FINAL",
            version=1,
        )
        self.report_repo.create(rep_v1)
        sec = ReportSection(
            id="sec-v1",
            report_id=rep_v1.id,
            section_type="EXECUTIVE_SUMMARY",
            title="Summary v1",
            position=0,
            content="Original content",
        )
        self.report_repo.add_section(sec)

        # Create version snapshot
        rep_v2 = self.report_repo.create_version("rep-ver-1", new_status="DRAFT")
        self.assertEqual(rep_v2.version, 2)
        self.assertEqual(rep_v2.parent_report_id, rep_v1.id)
        self.assertEqual(rep_v2.status, "DRAFT")

        # Check that sections were cloned independently
        v2_sections = self.report_repo.get_sections(rep_v2.id)
        self.assertEqual(len(v2_sections), 1)
        self.assertNotEqual(v2_sections[0].id, sec.id)
        self.assertEqual(v2_sections[0].content, "Original content")

        # Modify v2 section without affecting v1
        v2_sections[0].content = "Updated in version 2"
        self.report_repo.update_section(v2_sections[0])

        orig_sec = self.report_repo.get_section_by_id(sec.id)
        self.assertEqual(orig_sec.content, "Original content")

        # List all versions
        versions = self.report_repo.get_versions(rep_v2.id)
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].version, 1)
        self.assertEqual(versions[1].version, 2)


class TestReportSynthesisAndIntegrity(unittest.TestCase):
    """Unit tests verifying deterministic synthesis and scientific integrity rules."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_synth.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()

        self.src_repo = SourceRepository(self.db)
        self.concept_repo = ConceptRepository(self.db)
        self.inv_repo = InvestigationRepository(self.db)
        self.report_repo = ReportRepository(self.db)

        self.synth_engine = ReportSynthesisEngine(
            db=self.db,
            investigation_repo=self.inv_repo,
            source_repo=self.src_repo,
            concept_repo=self.concept_repo,
        )

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_synthesis_empty_investigation(self):
        inv = Investigation(
            id="inv-empty",
            title="Empty Investigation",
            research_question="What about zero sources?",
            status="draft",
        )
        self.inv_repo.save(inv)

        report, sections, sources, evidence, findings = self.synth_engine.synthesize("inv-empty")
        self.assertEqual(report.title, "Research Report: Empty Investigation")
        self.assertEqual(len(sources), 0)
        self.assertEqual(len(evidence), 0)
        self.assertEqual(len(findings), 0)
        self.assertGreaterEqual(len(sections), 10)

        # Check explicit absence language
        sec_map = {s.section_type: s.content for s in sections}
        self.assertIn("No sources are attached", sec_map["SOURCES"])
        self.assertIn("No empirical evidence items have been attached", sec_map["EVIDENCE"])
        self.assertIn("No synthesized findings have been recorded", sec_map["FINDINGS"])
        self.assertIn("Limited evidence was recorded", sec_map["EXECUTIVE_SUMMARY"])

    def test_synthesis_with_evidence_and_integrity_rules(self):
        # 1. Add Source
        now = datetime.now(timezone.utc)
        src = Source(
            id="src-attn",
            title="Attention Is All You Need",
            source_type="file",
            file_type="pdf",
            word_count=4500,
            created_at=now,
            updated_at=now,
        )
        self.src_repo.save(src)

        # 2. Add Investigation & attach source
        inv = Investigation(
            id="inv-attn",
            title="Transformer Scaling",
            research_question="How does attention scale with sequence length?",
            status="active",
        )
        self.inv_repo.save(inv)
        self.inv_repo.add_source(inv.id, src.id, relationship_type="PRIMARY_EVIDENCE")

        # 3. Add Evidence
        ev1 = InvestigationEvidence(
            id="ev-1",
            investigation_id=inv.id,
            source_id=src.id,
            statement="Multi-head attention has quadratic computational complexity in sequence length.",
            excerpt="Computational complexity per layer is O(n^2 * d).",
            location="Section 3.2, p. 5",
            evidence_type=EvidenceType.FACT.value,
            confidence=1.0,
        )
        self.inv_repo.save_evidence(ev1)

        # 4. Add Finding & link to evidence
        finding1 = InvestigationFinding(
            id="fnd-1",
            investigation_id=inv.id,
            title="Attention Complexity Scaling",
            statement="Standard attention mechanisms exhibit O(n^2) scaling relative to context window.",
            status=FindingStatus.SUPPORTED.value,
        )
        self.inv_repo.save_finding(finding1)
        self.inv_repo.link_finding_evidence(finding1.id, ev1.id)

        # 5. Add an unsupported finding
        finding_unsupported = InvestigationFinding(
            id="fnd-unsupported",
            investigation_id=inv.id,
            title="Theoretical Linear Attention Limit",
            statement="Linear attention always sacrifices recall on needle-in-haystack tasks.",
            status=FindingStatus.NEEDS_EVIDENCE.value,
        )
        self.inv_repo.save_finding(finding_unsupported)

        # Synthesize report
        report, sections, rep_sources, rep_evidence, rep_findings = self.synth_engine.synthesize("inv-attn")

        self.assertEqual(len(rep_sources), 1)
        self.assertEqual(rep_sources[0].citation_label, "[1]")
        self.assertEqual(len(rep_evidence), 1)
        self.assertEqual(rep_evidence[0].citation_label, "[1, Section 3.2, p. 5]")
        self.assertEqual(len(rep_findings), 2)

        sec_map = {s.section_type: s.content for s in sections}

        # Check Finding status display integrity (NEVER calls it "Proven")
        findings_content = sec_map["FINDINGS"]
        self.assertIn("Supported by linked evidence", findings_content)
        self.assertIn("Requires corroborating evidence", findings_content)
        self.assertIn("[1, Section 3.2, p. 5]", findings_content)
        self.assertIn("None linked. This claim requires empirical validation", findings_content)

        # Check References section contains source [1]
        self.assertIn("[1]", sec_map["REFERENCES"])
        self.assertIn("Attention Is All You Need", sec_map["REFERENCES"])

    def test_report_quality_analyzer_metrics(self):
        class DummyObj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        sources = [DummyObj(id="s1"), DummyObj(id="s2")]
        evidence = [DummyObj(id="e1", source_id="s1", location="p. 1")]
        findings = [
            DummyObj(id="f1", status="SUPPORTED"),
            DummyObj(id="f2", status="NEEDS_EVIDENCE"),
        ]
        finding_ev_map = {"f1": ["e1"], "f2": []}
        questions = [DummyObj(id="q1", status="OPEN", question="Open Q?")]
        concepts = [DummyObj(id="c1", name="Transformers")]

        metrics = ReportQualityAnalyzer.analyze(
            sources=sources,
            evidence_list=evidence,
            findings_list=findings,
            finding_evidence_map=finding_ev_map,
            questions=questions,
            concepts=concepts,
            concept_source_counts={"c1": 1},
        )

        self.assertEqual(metrics.evidence_coverage_pct, 50.0)  # 1 of 2 findings supported
        self.assertEqual(metrics.source_coverage_pct, 50.0)    # 1 of 2 sources cited
        self.assertEqual(metrics.finding_coverage_pct, 50.0)   # 1 of 2 marked SUPPORTED
        self.assertEqual(metrics.citation_completeness_pct, 100.0)
        self.assertEqual(metrics.open_questions_count, 1)
        self.assertEqual(metrics.unsupported_findings_count, 1)
        self.assertEqual(metrics.single_source_concepts_count, 1)

        # Verify gaps
        self.assertTrue(any("1 finding(s) currently have no linked evidence" in g for g in metrics.gaps))
        self.assertTrue(any("1 investigation question(s) remain unresolved" in g for g in metrics.gaps))


class TestReportComparisonAndExport(unittest.TestCase):
    """Unit tests for version comparator and markdown export."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_comp.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()

        self.report_repo = ReportRepository(self.db)
        self.inv_repo = InvestigationRepository(self.db)
        self.comparator = ReportVersionComparator(self.report_repo)
        self.export_svc = ReportExportService(self.report_repo, self.inv_repo)

        # Base investigation
        self.inv = Investigation(
            id="inv-comp",
            title="Comparison Base Investigation",
            research_question="What is the diff?",
            status="active",
        )
        self.inv_repo.save(self.inv)

        # Base report v1
        self.rep_v1 = Report(
            id="rep-diff-v1",
            investigation_id="inv-comp",
            title="Comparison Base",
            status="FINAL",
            version=1,
        )
        self.report_repo.create(self.rep_v1)
        self.report_repo.add_section(
            ReportSection(
                id="sec-diff-1",
                report_id=self.rep_v1.id,
                section_type="EXECUTIVE_SUMMARY",
                title="Executive Summary",
                content="Line 1\nLine 2\nLine 3",
            )
        )

        # Base report v2 (cloned and modified)
        self.rep_v2 = self.report_repo.create_version(self.rep_v1.id, new_status="DRAFT")
        v2_sections = self.report_repo.get_sections(self.rep_v2.id)
        v2_sections[0].content = "Line 1\nLine 2 Modified\nLine 3\nLine 4 Added"
        self.report_repo.update_section(v2_sections[0])

        # Add a new section to v2
        self.report_repo.add_section(
            ReportSection(
                id="sec-diff-new",
                report_id=self.rep_v2.id,
                section_type="CONCLUSION",
                title="Conclusion",
                content="New conclusion content.",
            )
        )

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_version_comparator(self):
        diff = self.comparator.compare(self.rep_v1.id, self.rep_v2.id)
        self.assertEqual(diff.version_a, 1)
        self.assertEqual(diff.version_b, 2)

        # Check modified section
        self.assertEqual(len(diff.modified_sections), 1)
        mod_sec = diff.modified_sections[0]
        self.assertEqual(mod_sec["section_type"], "EXECUTIVE_SUMMARY")
        self.assertTrue(mod_sec["content_changed"])

        # Check added section
        self.assertEqual(len(diff.added_sections), 1)
        self.assertEqual(diff.added_sections[0]["section_type"], "CONCLUSION")

    def test_markdown_export(self):
        md = self.export_svc.export_markdown(self.rep_v2.id)
        self.assertIn("# Comparison Base", md)
        self.assertIn("## Table of Contents", md)
        self.assertIn("Executive Summary", md)
        self.assertIn("Conclusion", md)
        self.assertIn("Line 2 Modified", md)
        self.assertIn("Provenance Custody:", md)


class TestReportServiceAndUIIntegration(unittest.TestCase):
    """End-to-end integration tests with the Flask web shell and REST endpoints."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_web.db"
        self.config = Config(
            app_name="ORVIA",
            version="0.1.0",
            database_path=self.db_path,
            log_level="ERROR",
            debug=False,
        )
        self.config.ensure_directories()
        self.app = create_app(self.config)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Connect DB instance for test setup
        self.db = DatabaseManager(self.config.DATABASE_PATH)
        self.db.connect()
        self.inv_repo = InvestigationRepository(self.db)
        self.src_repo = SourceRepository(self.db)

        now = datetime.now(timezone.utc)
        src = Source(
            id="src-ui-1",
            title="Evaluation in Modern AI",
            source_type="file",
            file_type="txt",
            word_count=1200,
            created_at=now,
            updated_at=now,
        )
        self.src_repo.save(src)

        self.inv = Investigation(
            id="inv-ui-1",
            title="Evaluation Standards",
            research_question="How should deterministic systems be tested?",
            status="active",
        )
        self.inv_repo.save(self.inv)
        self.inv_repo.add_source(self.inv.id, src.id)

    def tearDown(self):
        if hasattr(self, "db") and self.db:
            self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reports_page_render(self):
        resp = self.client.get("/reports")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Research Reports & Synthesis", html)

    def test_report_api_lifecycle(self):
        # 1. Create Report via API
        resp = self.client.post(
            "/api/reports",
            json={
                "investigation_id": self.inv.id,
                "title": "API Test Report",
                "subtitle": "Synthesized via API",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        rep_id = data["report"]["id"]

        # 2. Get Report Workspace via API
        resp_get = self.client.get(f"/api/reports/{rep_id}")
        self.assertEqual(resp_get.status_code, 200)
        ws = resp_get.get_json()["workspace"]
        self.assertEqual(ws["report"]["title"], "API Test Report")
        self.assertGreater(len(ws["sections"]), 0)

        # 3. View Report Detail Page HTML
        resp_page = self.client.get(f"/reports/{rep_id}")
        self.assertEqual(resp_page.status_code, 200)
        self.assertIn("API Test Report", resp_page.data.decode("utf-8"))

        # 4. Update Report status
        resp_stat = self.client.post(f"/api/reports/{rep_id}/status", json={"status": "IN_REVIEW"})
        self.assertEqual(resp_stat.status_code, 200)
        self.assertEqual(resp_stat.get_json()["report"]["status"], "IN_REVIEW")

        # 5. Quality endpoint
        resp_qual = self.client.get(f"/api/reports/{rep_id}/quality")
        self.assertEqual(resp_qual.status_code, 200)
        self.assertIn("evidence_coverage_pct", resp_qual.get_json()["quality"])

        # 6. Export Markdown
        resp_exp = self.client.get(f"/api/reports/{rep_id}/export/markdown")
        self.assertEqual(resp_exp.status_code, 200)
        self.assertIn("API Test Report", resp_exp.data.decode("utf-8"))

        # 7. Create Version
        resp_ver = self.client.post(f"/api/reports/{rep_id}/version", json={"status": "DRAFT"})
        self.assertEqual(resp_ver.status_code, 201)
        ver2_id = resp_ver.get_json()["report"]["id"]

        # 8. Compare Versions
        resp_comp = self.client.get(f"/api/reports/{rep_id}/compare/{ver2_id}")
        self.assertEqual(resp_comp.status_code, 200)
        self.assertEqual(resp_comp.get_json()["diff"]["version_a"], 1)
        self.assertEqual(resp_comp.get_json()["diff"]["version_b"], 2)

        # 9. Sections API: Add custom section
        resp_sec = self.client.post(
            f"/api/reports/{rep_id}/sections",
            json={
                "section_type": "LIMITATIONS",
                "title": "Custom Analysis Limitation",
                "content": "Custom note regarding experimental constraints.",
            },
        )
        self.assertEqual(resp_sec.status_code, 201)
        sec_id = resp_sec.get_json()["section"]["id"]

        # 10. Update section
        resp_up = self.client.post(
            f"/api/reports/{rep_id}/sections/{sec_id}",
            json={"title": "Updated Limitation", "content": "Refined content."},
        )
        self.assertEqual(resp_up.status_code, 200)
        self.assertEqual(resp_up.get_json()["section"]["title"], "Updated Limitation")

        # 11. Delete section
        resp_sdel = self.client.post(f"/api/reports/{rep_id}/sections/{sec_id}/delete")
        self.assertEqual(resp_sdel.status_code, 200)

        # 12. Delete Report
        resp_del = self.client.post(f"/api/reports/{ver2_id}/delete")
        self.assertEqual(resp_del.status_code, 200)

    def test_report_api_error_handling(self):
        # 404 on missing report
        resp_404 = self.client.get("/api/reports/non-existent-report-id")
        self.assertEqual(resp_404.status_code, 404)

        # 400 on missing investigation_id
        resp_400 = self.client.post("/api/reports", json={})
        self.assertEqual(resp_400.status_code, 400)

        # 400 on invalid status
        resp_bad_stat = self.client.post(
            "/api/reports/some-id/status",
            json={"status": "INVALID_STATE"},
        )
        self.assertEqual(resp_bad_stat.status_code, 400)

    def test_report_provenance_chain(self):
        # Add finding and evidence to inv
        ev = InvestigationEvidence(
            id="ev-prov-1",
            investigation_id=self.inv.id,
            source_id="src-ui-1",
            statement="Evaluation requires deterministic reproducible baselines.",
            evidence_type=EvidenceType.OBSERVATION.value,
        )
        self.inv_repo.save_evidence(ev)

        fnd = InvestigationFinding(
            id="fnd-prov-1",
            investigation_id=self.inv.id,
            title="Reproducibility In Evaluation",
            statement="Evaluation baselines must be deterministic.",
            status=FindingStatus.SUPPORTED.value,
        )
        self.inv_repo.save_finding(fnd)
        self.inv_repo.link_finding_evidence(fnd.id, ev.id)

        # Create report
        resp_cr = self.client.post("/api/reports", json={"investigation_id": self.inv.id})
        rep_id = resp_cr.get_json()["report"]["id"]

        # Fetch provenance chain
        resp_prov = self.client.get(f"/api/reports/{rep_id}/provenance/{fnd.id}")
        self.assertEqual(resp_prov.status_code, 200)
        chain = resp_prov.get_json()["provenance"]
        self.assertEqual(chain["finding"]["title"], "Reproducibility In Evaluation")
        self.assertEqual(len(chain["evidence_chain"]), 1)
        self.assertEqual(chain["evidence_chain"][0]["evidence"]["statement"], ev.statement)
        self.assertEqual(chain["evidence_chain"][0]["source"]["title"], "Evaluation in Modern AI")

    def test_cross_reference_counts(self):
        service = ResearchReportService(
            db=self.db,
            investigation_repo=self.inv_repo,
            source_repo=self.src_repo,
            concept_repo=ConceptRepository(self.db),
        )
        # Create a report
        ws = service.create_report(self.inv.id)
        rep_id = ws["report"]["id"]

        count_src = service.count_reports_using_source("src-ui-1")
        self.assertGreaterEqual(count_src, 1)


if __name__ == "__main__":
    unittest.main()
