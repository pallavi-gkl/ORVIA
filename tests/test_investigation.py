"""
Unit and integration test suite for ORVIA Phase 8: Investigation Workspace.
Covers:
- Investigation lifecycle, models, and status transitions (DRAFT, ACTIVE, PAUSED, COMPLETED, ARCHIVED)
- Repository CRUD for sources, concepts, evidence, notes, questions, findings, activities
- Provenance linking (Finding -> Evidence -> Source)
- Deterministic research gap detection
- Investigation-scoped knowledge graph generation
- Workspace stats and empty/completed states
- Flask web routes and REST API endpoints
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from orvia.app.core.config import Config
from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import NotFoundError, ValidationError
from orvia.app.investigations.models import (
    ActivityType,
    ConceptRole,
    EvidenceType,
    FindingStatus,
    InvestigationActivity,
    InvestigationConcept,
    InvestigationEvidence,
    InvestigationFinding,
    InvestigationNote,
    InvestigationQuestion,
    InvestigationSource,
    InvestigationStats,
    InvestigationStatus,
    NoteType,
    QuestionStatus,
    SourceRelationshipType,
    VALID_STATUS_TRANSITIONS,
)
from orvia.app.investigations.repository import InvestigationRepository
from orvia.app.investigations.service import InvestigationService
from orvia.app.knowledge.graph.service import KnowledgeGraphService
from orvia.app.models.concept import Concept
from orvia.app.models.investigation import Investigation
from orvia.app.models.source import Source
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.ui import create_app


class TestInvestigationCore(unittest.TestCase):
    """Unit tests for Phase 8 Investigation workspace models, repository, and service."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_orvia.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.db.initialize_schema()

        self.source_repo = SourceRepository(self.db)
        self.concept_repo = ConceptRepository(self.db)
        self.inv_repo = InvestigationRepository(self.db)
        self.inv_svc = InvestigationService(
            db=self.db,
            investigation_repo=self.inv_repo,
            source_repo=self.source_repo,
            concept_repo=self.concept_repo,
        )
        self.kg_svc = KnowledgeGraphService(
            db=self.db,
            concept_repo=self.concept_repo,
            source_repo=self.source_repo,
        )

    def tearDown(self):
        self.db.disconnect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_source(self, title: str, content: str = "") -> Source:
        src = Source(
            id=f"src-{title.lower().replace(' ', '-')}",
            title=title,
            source_type="file",
            file_type="txt",
            content=content or f"Content for source {title}. Explores cognitive representation learning.",
        )
        self.source_repo.save(src)
        return src

    def _make_concept(self, name: str) -> Concept:
        cpt = Concept(
            id=f"cpt-{name.lower().replace(' ', '-')}",
            name=name,
        )
        self.concept_repo.save(cpt)
        return cpt

    # 1. Investigation creation
    def test_investigation_creation(self):
        inv = self.inv_svc.create_investigation(
            title="Transformer Interpretability",
            research_question="How do self-attention layers encode syntax trees?",
            description="Investigating attention head behavior across deep linguistic representations.",
            initial_status="active",
        )
        self.assertIsNotNone(inv.id)
        self.assertEqual(inv.title, "Transformer Interpretability")
        self.assertEqual(inv.research_question, "How do self-attention layers encode syntax trees?")
        self.assertEqual(inv.status, "active")

    # 2. Investigation retrieval
    def test_investigation_retrieval(self):
        inv = self.inv_svc.create_investigation(
            title="Sparse Attention Mechanisms",
            research_question="Does linear attention compromise recall accuracy?",
        )
        fetched = self.inv_svc.get_investigation(inv.id)
        self.assertEqual(fetched.id, inv.id)
        self.assertEqual(fetched.title, "Sparse Attention Mechanisms")
        self.assertEqual(fetched.research_question, "Does linear attention compromise recall accuracy?")

    # 3. Investigation update
    def test_investigation_update(self):
        inv = self.inv_svc.create_investigation(
            title="Draft Title",
            research_question="Initial Question?",
        )
        updated = self.inv_svc.update_investigation(
            inv.id,
            title="Refined Title",
            research_question="Refined Question?",
            description="Added scope description.",
        )
        self.assertEqual(updated.title, "Refined Title")
        self.assertEqual(updated.research_question, "Refined Question?")
        self.assertEqual(updated.description, "Added scope description.")

    # 4. Status transition DRAFT -> ACTIVE
    def test_status_transition_draft_to_active(self):
        inv = self.inv_svc.create_investigation(
            title="Draft Exploration",
            research_question="Preliminary query?",
            initial_status="draft",
        )
        self.assertEqual(inv.status, "draft")
        transitioned, warning = self.inv_svc.transition_status(inv.id, "active")
        self.assertEqual(transitioned.status, "active")
        self.assertIsNone(warning)

    # 5. Status transition ACTIVE -> PAUSED
    def test_status_transition_active_to_paused(self):
        inv = self.inv_svc.create_investigation(
            title="Active Research",
            research_question="Is active?",
            initial_status="active",
        )
        transitioned, _ = self.inv_svc.transition_status(inv.id, "paused")
        self.assertEqual(transitioned.status, "paused")

    # 6. Status transition PAUSED -> ACTIVE
    def test_status_transition_paused_to_active(self):
        inv = self.inv_svc.create_investigation(
            title="Paused Study",
            research_question="Can resume?",
            initial_status="active",
        )
        self.inv_svc.transition_status(inv.id, "paused")
        resumed, _ = self.inv_svc.transition_status(inv.id, "active")
        self.assertEqual(resumed.status, "active")

    # 7. Status transition ACTIVE -> COMPLETED
    def test_status_transition_active_to_completed(self):
        inv = self.inv_svc.create_investigation(
            title="Completed Study",
            research_question="Has finished?",
            initial_status="active",
        )
        completed, _ = self.inv_svc.transition_status(inv.id, "completed")
        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(completed.completed_at)

    # 8. Status transition COMPLETED -> ARCHIVED
    def test_status_transition_completed_to_archived(self):
        inv = self.inv_svc.create_investigation(
            title="Archived Study",
            research_question="Can archive?",
            initial_status="active",
        )
        self.inv_svc.transition_status(inv.id, "completed")
        archived, _ = self.inv_svc.transition_status(inv.id, "archived")
        self.assertEqual(archived.status, "archived")

    # 9. Invalid status transition raises ValidationError
    def test_invalid_status_transition_raises(self):
        inv = self.inv_svc.create_investigation(
            title="Draft Study",
            research_question="Direct jump?",
            initial_status="draft",
        )
        with self.assertRaises(ValidationError):
            self.inv_svc.transition_status(inv.id, "completed")

    # 10. Investigation delete
    def test_investigation_delete(self):
        inv = self.inv_svc.create_investigation(
            title="To be deleted",
            research_question="Will disappear?",
        )
        self.assertTrue(self.inv_svc.delete_investigation(inv.id))
        self.assertIsNone(self.inv_repo.find_by_id(inv.id))

    # 11. Source attachment
    def test_source_attachment(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        src = self._make_source("Source Alpha")
        inv_src = self.inv_svc.attach_source(
            inv.id, src.id, relationship_type="PRIMARY_EVIDENCE", notes="Key paper"
        )
        self.assertEqual(inv_src.source_id, src.id)
        self.assertTrue(self.inv_repo.has_source(inv.id, src.id))
        sources = self.inv_repo.get_sources(inv.id)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].source_title, "Source Alpha")

    # 12. Source removal
    def test_source_removal(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        src = self._make_source("Source Beta")
        self.inv_svc.attach_source(inv.id, src.id)
        self.assertTrue(self.inv_repo.has_source(inv.id, src.id))
        removed = self.inv_svc.detach_source(inv.id, src.id)
        self.assertTrue(removed)
        self.assertFalse(self.inv_repo.has_source(inv.id, src.id))

    # 13. Concept tracking
    def test_concept_tracking(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        cpt = self._make_concept("Attention Mechanism")
        inv_cpt = self.inv_svc.track_concept(
            inv.id, cpt.id, role="KEY_CONCEPT", notes="Core focus"
        )
        self.assertEqual(inv_cpt.concept_id, cpt.id)
        self.assertEqual(inv_cpt.role, "KEY_CONCEPT")
        tracked = self.inv_repo.get_concepts(inv.id)
        self.assertEqual(len(tracked), 1)
        self.assertEqual(tracked[0].concept_name, "Attention Mechanism")

    # 14. Evidence creation
    def test_evidence_creation(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        src = self._make_source("Empirical Paper")
        ev = self.inv_svc.record_evidence(
            investigation_id=inv.id,
            source_id=src.id,
            statement="Attention layers exhibit 40% head redundancy.",
            excerpt="We found that up to 40% of heads can be pruned without loss.",
            location="Section 4.2",
            evidence_type="STATISTIC",
            confidence=0.9,
        )
        self.assertIsNotNone(ev.id)
        self.assertEqual(ev.statement, "Attention layers exhibit 40% head redundancy.")
        self.assertEqual(ev.evidence_type, "STATISTIC")
        self.assertEqual(ev.confidence, 0.9)

    # 15. Evidence provenance (joined source metadata)
    def test_evidence_provenance(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        src = self._make_source("Transformer Pruning 2024")
        ev = self.inv_svc.record_evidence(
            investigation_id=inv.id,
            source_id=src.id,
            statement="Observation regarding parameter reduction.",
        )
        fetched = self.inv_repo.get_evidence(ev.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.source_title, "Transformer Pruning 2024")

    # 16. Note creation
    def test_note_creation(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        note = self.inv_svc.add_note(
            inv.id,
            title="Hypothesis Note",
            content="Perhaps multi-query attention alters head redundancy distributions.",
            note_type="HYPOTHESIS",
        )
        self.assertIsNotNone(note.id)
        self.assertEqual(note.note_type, "HYPOTHESIS")
        notes = self.inv_repo.get_notes(inv.id)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].content, note.content)

    # 17. Question creation
    def test_question_creation(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        q = self.inv_svc.add_question(
            inv.id,
            question="What is the impact of sliding window attention on long context retrieval?",
        )
        self.assertIsNotNone(q.id)
        self.assertEqual(q.status, "OPEN")
        questions = self.inv_repo.get_questions(inv.id)
        self.assertEqual(len(questions), 1)

    # 18. Question resolution
    def test_question_resolution(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        q = self.inv_svc.add_question(inv.id, question="Does flash attention change numerical outputs?")
        resolved = self.inv_svc.update_question_status(
            q.id,
            status="RESOLVED",
            resolution_note="Numerical difference is within standard fp16 precision bounds.",
        )
        self.assertEqual(resolved.status, "RESOLVED")
        self.assertIsNotNone(resolved.resolved_at)
        self.assertIn("fp16", resolved.resolution_note)

    # 19. Finding creation
    def test_finding_creation(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        finding = self.inv_svc.record_finding(
            investigation_id=inv.id,
            title="Attention Head Redundancy",
            statement="Substantial proportion of attention heads can be removed post-training.",
            status="DRAFT",
        )
        self.assertIsNotNone(finding.id)
        self.assertEqual(finding.title, "Attention Head Redundancy")
        self.assertEqual(finding.status, "DRAFT")

    # 20. Finding-evidence linking
    def test_finding_evidence_relationship(self):
        inv = self.inv_svc.create_investigation("Inv", "Q?")
        src = self._make_source("Source Gamma")
        ev = self.inv_svc.record_evidence(inv.id, src.id, "Empirical head pruning metric.")
        finding = self.inv_svc.record_finding(inv.id, "Head Pruning Finding", "Pruning works.")
        self.assertEqual(finding.supporting_evidence_count, 0)

        linked = self.inv_svc.link_evidence_to_finding(finding.id, ev.id)
        self.assertTrue(linked)

        refreshed = self.inv_repo.get_finding(finding.id)
        self.assertEqual(refreshed.supporting_evidence_count, 1)

        findings_for_ev = self.inv_repo.get_findings_for_evidence(ev.id)
        self.assertEqual(len(findings_for_ev), 1)
        self.assertEqual(findings_for_ev[0], finding.id)

    # 21. Activity log on creation
    def test_activity_creation(self):
        inv = self.inv_svc.create_investigation("Logged Study", "Q?")
        acts = self.inv_repo.get_activities(inv.id)
        self.assertGreaterEqual(len(acts), 1)
        created_acts = [a for a in acts if a.activity_type == ActivityType.INVESTIGATION_CREATED.value]
        self.assertEqual(len(created_acts), 1)

    # 22. Investigation statistics
    def test_investigation_statistics(self):
        inv = self.inv_svc.create_investigation("Stats Study", "Q?")
        src = self._make_source("Stats Source")
        self.inv_svc.attach_source(inv.id, src.id)
        cpt = self._make_concept("Stats Concept")
        self.inv_svc.track_concept(inv.id, cpt.id)
        self.inv_svc.record_evidence(inv.id, src.id, "Statement 1")
        self.inv_svc.add_question(inv.id, "Question 1?")
        self.inv_svc.record_finding(inv.id, "Finding 1", "Statement 1")
        self.inv_svc.add_note(inv.id, "Note 1", "Content 1")

        stats = self.inv_repo.get_stats(inv.id)
        self.assertEqual(stats.source_count, 1)
        self.assertEqual(stats.concept_count, 1)
        self.assertEqual(stats.evidence_count, 1)
        self.assertEqual(stats.open_questions_count, 1)
        self.assertEqual(stats.findings_count, 1)
        self.assertEqual(stats.notes_count, 1)

    # 23. Investigation-scoped graph
    def test_investigation_scoped_graph(self):
        inv = self.inv_svc.create_investigation("Graph Study", "Q?")
        src = self._make_source("Graph Source")
        cpt = self._make_concept("Graph Concept")
        self.inv_svc.attach_source(inv.id, src.id)
        self.inv_svc.track_concept(inv.id, cpt.id)

        graph_dict = self.kg_svc.get_investigation_graph(inv.id)
        self.assertIn("nodes", graph_dict)
        self.assertIn("edges", graph_dict)
        self.assertIn("metadata", graph_dict)

    # 24. Empty investigation state
    def test_empty_investigation_state(self):
        inv = self.inv_svc.create_investigation("Empty Study", "Q?")
        stats = self.inv_repo.get_stats(inv.id)
        self.assertEqual(stats.source_count, 0)
        self.assertEqual(stats.evidence_count, 0)
        self.assertEqual(stats.open_questions_count, 0)
        self.assertEqual(stats.findings_count, 0)
        self.assertEqual(stats.concept_count, 0)

    # 25. Completed investigation state
    def test_completed_investigation_state(self):
        inv = self.inv_svc.create_investigation("Completion Study", "Q?")
        completed, _ = self.inv_svc.transition_status(inv.id, "completed")
        self.assertIsNotNone(completed.completed_at)
        refetched = self.inv_repo.find_by_id(inv.id)
        self.assertIsNotNone(refetched.completed_at)

    # 26. Cascade delete
    def test_data_integrity_cascade_delete(self):
        inv = self.inv_svc.create_investigation("Cascade Study", "Q?")
        src = self._make_source("Cascade Source")
        ev = self.inv_svc.record_evidence(inv.id, src.id, "Cascade Statement")

        self.inv_svc.delete_investigation(inv.id)
        self.assertIsNone(self.inv_repo.get_evidence(ev.id))
        self.assertEqual(len(self.inv_repo.get_sources(inv.id)), 0)

    # 27. Duplicate source attachment is idempotent
    def test_duplicate_source_attachment_is_idempotent(self):
        inv = self.inv_svc.create_investigation("Idempotent Study", "Q?")
        src = self._make_source("Same Source")
        self.inv_svc.attach_source(inv.id, src.id)
        self.inv_svc.attach_source(inv.id, src.id)
        sources = self.inv_repo.get_sources(inv.id)
        self.assertEqual(len(sources), 1)

    # 28. Research gaps on empty investigation
    def test_research_gaps_empty_sources(self):
        inv = self.inv_svc.create_investigation("Gaps Study", "Q?")
        gaps = self.inv_svc.calculate_research_gaps(inv.id)
        gap_types = [g["type"] for g in gaps]
        self.assertIn("empty_sources", gap_types)


class TestInvestigationUI(unittest.TestCase):
    """Integration tests for web views and REST APIs for Phase 8 Investigation workspace."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_orvia.db"
        self.config = Config(
            app_name="ORVIA",
            version="0.1.0",
            database_path=self.db_path,
            log_level="ERROR",
            debug=False,
        )
        self.config.ensure_directories()
        self.app = create_app(self.config)
        self.client = self.app.test_client()

        with self.app.app_context():
            from orvia.app.ui import get_db
            db = get_db()
            repo = SourceRepository(db)
            s = Source(
                id="src-ui-1",
                title="UI Research Document",
                source_type="file",
                file_type="txt",
                content="Empirical validation of sparse multi-head self-attention.",
            )
            repo.save(s)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. GET /investigations
    def test_investigations_list_route(self):
        res = self.client.get("/investigations")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Research Investigations", res.get_data(as_text=True))

    # 2. GET /investigations/new
    def test_investigation_new_route(self):
        res = self.client.get("/investigations/new")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Start Your Research", res.get_data(as_text=True))

    # 3. POST /api/investigations
    def test_api_create_investigation(self):
        payload = {
            "title": "API Investigation",
            "research_question": "Does the REST API function correctly?",
            "description": "Validation test for endpoint creation.",
            "status": "active",
        }
        res = self.client.post("/api/investigations", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("id", data["investigation"])
        self.assertEqual(data["investigation"]["title"], "API Investigation")

    # 4. POST /api/investigations missing fields
    def test_api_create_investigation_missing_fields(self):
        res = self.client.post("/api/investigations", json={"title": "Missing Question"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["status"], "error")

    # 5. GET /investigations/<id>
    def test_investigation_detail_route(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Detail View Study", "research_question": "Can render workspace?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.get(f"/investigations/{inv_id}")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Detail View Study", res.get_data(as_text=True))

    # 6. GET /api/investigations/<id>
    def test_api_get_investigation(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "API Get Study", "research_question": "Can fetch by id?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.get(f"/api/investigations/{inv_id}")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["investigation"]["title"], "API Get Study")

    # 7. POST /api/investigations/<id>/status
    def test_api_update_investigation_status(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Status Study", "research_question": "Can pause?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.post(f"/api/investigations/{inv_id}/status", json={"status": "paused"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["investigation"]["status"], "paused")

    # 8. POST /api/investigations/<id>/status invalid transition
    def test_api_invalid_status_transition(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Draft Study", "research_question": "Jump?", "status": "draft"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.post(f"/api/investigations/{inv_id}/status", json={"status": "completed"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["status"], "error")

    # 9. POST /api/investigations/<id>/sources
    def test_api_attach_source(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Source Attach Study", "research_question": "Attach?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.post(
            f"/api/investigations/{inv_id}/sources",
            json={"source_id": "src-ui-1", "relationship_type": "PRIMARY_EVIDENCE"},
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")

    # 10. POST /api/investigations/<id>/evidence
    def test_api_record_evidence(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Evidence Study", "research_question": "Record?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.post(
            f"/api/investigations/{inv_id}/evidence",
            json={
                "source_id": "src-ui-1",
                "statement": "Recorded evidence statement.",
                "evidence_type": "OBSERVATION",
                "confidence": 1.0,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["evidence"]["statement"], "Recorded evidence statement.")

    # 11. POST /api/investigations/<id>/questions
    def test_api_add_question(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Question Study", "research_question": "Ask?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.post(
            f"/api/investigations/{inv_id}/questions",
            json={"question": "What is the computational complexity of sparse attention?"},
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["question"]["status"], "OPEN")

    # 12. POST /api/investigations/<id>/findings
    def test_api_record_finding(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Finding Study", "research_question": "Conclude?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.post(
            f"/api/investigations/{inv_id}/findings",
            json={"title": "Complexity Finding", "statement": "Attention scales quadratically.", "status": "DRAFT"},
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["finding"]["title"], "Complexity Finding")

    # 13. GET /api/investigations/<id>/stats
    def test_api_investigation_stats(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Stats Study", "research_question": "Check counts?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.get(f"/api/investigations/{inv_id}/stats")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("stats", data)
        self.assertIn("source_count", data["stats"])

    # 14. GET /api/investigations/<id>/activity
    def test_api_investigation_activity(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Activity Study", "research_question": "Check log?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.get(f"/api/investigations/{inv_id}/activity")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("activities", data)
        self.assertGreaterEqual(len(data["activities"]), 1)

    # 15. GET /api/investigations/<id>/graph
    def test_api_investigation_graph(self):
        post_res = self.client.post(
            "/api/investigations",
            json={"title": "Graph Study", "research_question": "Check graph?"},
        )
        inv_id = post_res.get_json()["investigation"]["id"]
        res = self.client.get(f"/api/investigations/{inv_id}/graph")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("graph", data)
        self.assertIn("nodes", data["graph"])
        self.assertIn("edges", data["graph"])


if __name__ == "__main__":
    unittest.main()
