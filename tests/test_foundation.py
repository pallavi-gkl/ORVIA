"""
tests/test_foundation.py

Unit tests for the ORVIA Phase 1 foundation.
Uses Python's built-in unittest and an in-memory SQLite database.
All tests are designed to pass without any external dependencies.
"""

import sys
import unittest
from pathlib import Path

# Ensure the project root is on the Python path so the `orvia` package
# can be imported when running: python -m pytest  OR  python -m unittest
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import (
    DatabaseError,
    DuplicateError,
    NotFoundError,
    OrviaError,
    RepositoryError,
    ValidationError,
)
from orvia.app.models.concept import Concept
from orvia.app.models.document import Document
from orvia.app.models.evidence import Evidence
from orvia.app.models.investigation import Investigation
from orvia.app.models.relationship import Relationship
from orvia.app.models.source import Source
from orvia.app.models.topic import Topic
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.document_repository import DocumentRepository
from orvia.app.repositories.investigation_repository import InvestigationRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.topic_repository import TopicRepository
from orvia.app.services.workspace_service import WorkspaceService


# ---------------------------------------------------------------------------
# Helper: in-memory DatabaseManager
# ---------------------------------------------------------------------------

def _make_db() -> DatabaseManager:
    """Return a fully initialised in-memory DatabaseManager for testing."""
    db = DatabaseManager(db_path=Path(":memory:"))
    db.connect()
    db.initialize_schema()
    return db


# ===========================================================================
# TestDatabaseManager
# ===========================================================================

class TestDatabaseManager(unittest.TestCase):
    """Tests for DatabaseManager connection, schema, and query helpers."""

    def setUp(self) -> None:
        self.db = _make_db()

    def tearDown(self) -> None:
        self.db.disconnect()

    # --- connectivity -------------------------------------------------------

    def test_connect_creates_connection(self) -> None:
        self.assertIsNotNone(self.db._connection)

    def test_disconnect_clears_connection(self) -> None:
        self.db.disconnect()
        self.assertIsNone(self.db._connection)
        # Re-connect so tearDown works
        self.db.connect()

    def test_context_manager(self) -> None:
        db2 = DatabaseManager(db_path=Path(":memory:"))
        with db2 as ctx:
            self.assertIsNotNone(ctx._connection)
        self.assertIsNone(db2._connection)

    # --- schema -------------------------------------------------------------

    def test_all_tables_created(self) -> None:
        expected_tables = {
            "sources", "documents", "topics", "concepts",
            "relationships", "evidences", "investigations",
            "investigation_documents",
        }
        rows = self.db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )
        actual = {r["name"] for r in rows}
        self.assertTrue(expected_tables.issubset(actual), f"Missing tables: {expected_tables - actual}")

    def test_schema_is_idempotent(self) -> None:
        """initialize_schema() should not raise when called a second time."""
        self.db.initialize_schema()

    # --- query helpers ------------------------------------------------------

    def test_execute_and_fetchall(self) -> None:
        self.db.execute(
            "INSERT INTO sources (id, title, source_type, reliability_score, "
            "metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?);",
            ("s1", "Test Source", "web", 0.8, "{}", "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
        )
        rows = self.db.fetchall("SELECT * FROM sources WHERE id='s1';")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Test Source")

    def test_fetchone_returns_none_for_missing(self) -> None:
        result = self.db.fetchone("SELECT * FROM sources WHERE id='nonexistent';")
        self.assertIsNone(result)

    def test_fetchall_returns_list_of_dicts(self) -> None:
        rows = self.db.fetchall("SELECT * FROM sources;")
        self.assertIsInstance(rows, list)
        # Insert one row and check dict structure
        self.db.execute(
            "INSERT INTO sources (id, title, source_type, reliability_score, "
            "metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?);",
            ("s2", "Dict Test", "manual", 0.5, "{}", "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
        )
        rows = self.db.fetchall("SELECT * FROM sources WHERE id='s2';")
        self.assertIsInstance(rows[0], dict)
        self.assertIn("title", rows[0])

    def test_executemany(self) -> None:
        params = [
            ("s3", "Bulk A", "api", 0.5, "{}", "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
            ("s4", "Bulk B", "file", 0.5, "{}", "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
        ]
        self.db.executemany(
            "INSERT OR IGNORE INTO sources (id, title, source_type, reliability_score, "
            "metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?);",
            params,
        )
        count_row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM sources WHERE id IN ('s3','s4');")
        self.assertEqual(count_row["cnt"], 2)


# ===========================================================================
# TestModels
# ===========================================================================

class TestModels(unittest.TestCase):
    """Tests for domain model creation, serialisation, and validation."""

    # --- Document -----------------------------------------------------------

    def test_document_auto_word_count(self) -> None:
        doc = Document(title="Test", content="one two three four five")
        self.assertEqual(doc.word_count, 5)

    def test_document_auto_content_hash(self) -> None:
        doc = Document(title="Hash Test", content="hello world")
        self.assertIsNotNone(doc.content_hash)
        self.assertEqual(len(doc.content_hash), 64)  # SHA-256 hex

    def test_document_to_dict_and_from_dict(self) -> None:
        doc = Document(title="Round-trip", content="some content", tags=["ai", "nlp"])
        d = doc.to_dict()
        self.assertIn("tags", d)
        doc2 = Document.from_dict(d)
        self.assertEqual(doc2.id, doc.id)
        self.assertEqual(doc2.tags, ["ai", "nlp"])

    def test_document_validation_empty_title(self) -> None:
        doc = Document(title="", content="valid content")
        with self.assertRaises(ValidationError) as ctx:
            doc.validate()
        self.assertEqual(ctx.exception.field, "title")

    def test_document_validation_empty_content(self) -> None:
        doc = Document(title="Valid", content="")
        with self.assertRaises(ValidationError) as ctx:
            doc.validate()
        self.assertEqual(ctx.exception.field, "content")

    # --- Source -------------------------------------------------------------

    def test_source_valid(self) -> None:
        src = Source(title="OpenAI Blog", source_type="web", url="https://openai.com")
        src.validate()  # should not raise

    def test_source_invalid_type(self) -> None:
        src = Source(title="Bad Type", source_type="unknown")
        with self.assertRaises(ValidationError) as ctx:
            src.validate()
        self.assertEqual(ctx.exception.field, "source_type")

    def test_source_invalid_reliability_score(self) -> None:
        src = Source(title="Out of range", source_type="web", reliability_score=1.5)
        with self.assertRaises(ValidationError) as ctx:
            src.validate()
        self.assertEqual(ctx.exception.field, "reliability_score")

    def test_source_from_dict_roundtrip(self) -> None:
        src = Source(title="RT Source", source_type="api", metadata={"key": "value"})
        d = src.to_dict()
        src2 = Source.from_dict(d)
        self.assertEqual(src2.metadata, {"key": "value"})

    # --- Investigation ------------------------------------------------------

    def test_investigation_valid(self) -> None:
        inv = Investigation(
            title="AI Safety Research",
            research_question="How do we align AGI?",
        )
        inv.validate()  # should not raise

    def test_investigation_invalid_status(self) -> None:
        inv = Investigation(
            title="Test",
            research_question="Q?",
            status="unknown",
        )
        with self.assertRaises(ValidationError) as ctx:
            inv.validate()
        self.assertEqual(ctx.exception.field, "status")

    def test_investigation_empty_title(self) -> None:
        inv = Investigation(title="", research_question="Q?")
        with self.assertRaises(ValidationError) as ctx:
            inv.validate()
        self.assertEqual(ctx.exception.field, "title")

    # --- Topic --------------------------------------------------------------

    def test_topic_to_dict_excludes_updated_at(self) -> None:
        topic = Topic(name="Machine Learning")
        d = topic.to_dict()
        self.assertNotIn("updated_at", d)
        self.assertIn("created_at", d)

    def test_topic_validation_name_too_long(self) -> None:
        topic = Topic(name="x" * 201)
        with self.assertRaises(ValidationError):
            topic.validate()

    # --- Relationship -------------------------------------------------------

    def test_relationship_self_loop_raises(self) -> None:
        rel = Relationship(
            source_concept_id="abc",
            target_concept_id="abc",
            relationship_type="related_to",
        )
        with self.assertRaises(ValidationError) as ctx:
            rel.validate()
        self.assertEqual(ctx.exception.field, "source_concept_id")

    def test_relationship_to_dict_excludes_updated_at(self) -> None:
        rel = Relationship(
            source_concept_id="a",
            target_concept_id="b",
            relationship_type="supports",
        )
        d = rel.to_dict()
        self.assertNotIn("updated_at", d)

    # --- Evidence -----------------------------------------------------------

    def test_evidence_to_dict_excludes_updated_at(self) -> None:
        ev = Evidence(document_id="d1", concept_id="c1", excerpt="Some text")
        d = ev.to_dict()
        self.assertNotIn("updated_at", d)

    def test_evidence_validation_empty_excerpt(self) -> None:
        ev = Evidence(document_id="d1", concept_id="c1", excerpt="")
        with self.assertRaises(ValidationError) as ctx:
            ev.validate()
        self.assertEqual(ctx.exception.field, "excerpt")

    # --- Concept ------------------------------------------------------------

    def test_concept_aliases_round_trip(self) -> None:
        c = Concept(name="NLP", aliases=["Natural Language Processing", "NLU"])
        d = c.to_dict()
        c2 = Concept.from_dict(d)
        self.assertEqual(c2.aliases, ["Natural Language Processing", "NLU"])


# ===========================================================================
# TestRepositories
# ===========================================================================

class TestRepositories(unittest.TestCase):
    """Integration-style tests using an in-memory DB."""

    def setUp(self) -> None:
        self.db = _make_db()
        self.source_repo = SourceRepository(self.db)
        self.document_repo = DocumentRepository(self.db)
        self.topic_repo = TopicRepository(self.db)
        self.concept_repo = ConceptRepository(self.db)
        self.investigation_repo = InvestigationRepository(self.db)

    def tearDown(self) -> None:
        self.db.disconnect()

    # --- SourceRepository ---------------------------------------------------

    def test_source_save_and_find_by_id(self) -> None:
        src = Source(title="Nature Journal", source_type="web", url="https://nature.com")
        self.source_repo.save(src)
        retrieved = self.source_repo.find_by_id(src.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, "Nature Journal")
        self.assertEqual(retrieved.url, "https://nature.com")

    def test_source_find_by_id_missing(self) -> None:
        result = self.source_repo.find_by_id("nonexistent-id")
        self.assertIsNone(result)

    def test_source_delete(self) -> None:
        src = Source(title="Delete Me", source_type="manual")
        self.source_repo.save(src)
        deleted = self.source_repo.delete(src.id)
        self.assertTrue(deleted)
        self.assertIsNone(self.source_repo.find_by_id(src.id))

    def test_source_delete_nonexistent(self) -> None:
        result = self.source_repo.delete("ghost-id")
        self.assertFalse(result)

    def test_source_count(self) -> None:
        initial = self.source_repo.count()
        self.source_repo.save(Source(title="A", source_type="api"))
        self.source_repo.save(Source(title="B", source_type="file"))
        self.assertEqual(self.source_repo.count(), initial + 2)

    def test_source_find_all(self) -> None:
        for i in range(3):
            self.source_repo.save(Source(title=f"Source {i}", source_type="web"))
        results = self.source_repo.find_all(limit=10)
        self.assertGreaterEqual(len(results), 3)
        self.assertIsInstance(results[0], Source)

    def test_source_search_by_title(self) -> None:
        self.source_repo.save(Source(title="Quantum Computing Today", source_type="web"))
        self.source_repo.save(Source(title="Classical Physics", source_type="web"))
        results = self.source_repo.search_by_title("Quantum")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Quantum Computing Today")

    def test_source_find_by_source_type(self) -> None:
        self.source_repo.save(Source(title="API Feed 1", source_type="api"))
        self.source_repo.save(Source(title="API Feed 2", source_type="api"))
        self.source_repo.save(Source(title="Web Page", source_type="web"))
        api_results = self.source_repo.find_by_source_type("api")
        self.assertGreaterEqual(len(api_results), 2)
        self.assertTrue(all(s.source_type == "api" for s in api_results))

    def test_source_exists(self) -> None:
        src = Source(title="Exist Test", source_type="manual")
        self.assertFalse(self.source_repo.exists(src.id))
        self.source_repo.save(src)
        self.assertTrue(self.source_repo.exists(src.id))

    # --- DocumentRepository -------------------------------------------------

    def test_document_save_and_find_by_id(self) -> None:
        doc = Document(
            title="AI Paper",
            content="Artificial intelligence is transforming every industry.",
            tags=["ai", "tech"],
        )
        self.document_repo.save(doc)
        retrieved = self.document_repo.find_by_id(doc.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, "AI Paper")
        self.assertEqual(retrieved.tags, ["ai", "tech"])

    def test_document_word_count_persisted(self) -> None:
        doc = Document(title="Word Count", content="one two three")
        self.document_repo.save(doc)
        retrieved = self.document_repo.find_by_id(doc.id)
        self.assertEqual(retrieved.word_count, 3)

    def test_document_content_hash_persisted(self) -> None:
        doc = Document(title="Hash Persist", content="stable content")
        self.document_repo.save(doc)
        retrieved = self.document_repo.find_by_id(doc.id)
        self.assertEqual(retrieved.content_hash, doc.content_hash)

    def test_document_find_by_content_hash(self) -> None:
        doc = Document(title="Hash Lookup", content="unique content for hashing xyz123")
        self.document_repo.save(doc)
        retrieved = self.document_repo.find_by_content_hash(doc.content_hash)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, doc.id)

    def test_document_search_by_title(self) -> None:
        self.document_repo.save(Document(title="Deep Learning Fundamentals", content="Content A"))
        self.document_repo.save(Document(title="Shallow Thoughts", content="Content B"))
        results = self.document_repo.search_by_title("Deep")
        self.assertEqual(len(results), 1)

    def test_document_search_content(self) -> None:
        self.document_repo.save(
            Document(title="Searchable", content="The transformer architecture changed NLP forever.")
        )
        results = self.document_repo.search_content("transformer architecture")
        self.assertGreaterEqual(len(results), 1)

    def test_document_delete(self) -> None:
        doc = Document(title="Ephemeral", content="Will be deleted")
        self.document_repo.save(doc)
        self.assertTrue(self.document_repo.delete(doc.id))
        self.assertIsNone(self.document_repo.find_by_id(doc.id))

    # --- TopicRepository ----------------------------------------------------

    def test_topic_save_and_find_by_name(self) -> None:
        topic = Topic(name="Epistemology")
        self.topic_repo.save(topic)
        found = self.topic_repo.find_by_name("Epistemology")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, topic.id)

    def test_topic_find_root_topics(self) -> None:
        root1 = Topic(name="RootTopic_A")
        root2 = Topic(name="RootTopic_B")
        child = Topic(name="ChildTopic_C", parent_topic_id=root1.id)
        for t in (root1, root2, child):
            self.topic_repo.save(t)
        roots = self.topic_repo.find_root_topics()
        root_ids = {t.id for t in roots}
        self.assertIn(root1.id, root_ids)
        self.assertIn(root2.id, root_ids)
        self.assertNotIn(child.id, root_ids)

    def test_topic_find_children(self) -> None:
        parent = Topic(name="ParentX")
        child1 = Topic(name="ChildX1", parent_topic_id=parent.id)
        child2 = Topic(name="ChildX2", parent_topic_id=parent.id)
        for t in (parent, child1, child2):
            self.topic_repo.save(t)
        children = self.topic_repo.find_children(parent.id)
        child_ids = {t.id for t in children}
        self.assertIn(child1.id, child_ids)
        self.assertIn(child2.id, child_ids)

    # --- ConceptRepository --------------------------------------------------

    def test_concept_save_and_find_by_name(self) -> None:
        concept = Concept(name="Backpropagation", aliases=["backprop"])
        self.concept_repo.save(concept)
        found = self.concept_repo.find_by_name("Backpropagation")
        self.assertIsNotNone(found)
        self.assertEqual(found.aliases, ["backprop"])

    def test_concept_increment_frequency(self) -> None:
        concept = Concept(name="Gradient Descent")
        self.concept_repo.save(concept)
        self.concept_repo.increment_frequency(concept.id)
        self.concept_repo.increment_frequency(concept.id)
        updated = self.concept_repo.find_by_id(concept.id)
        self.assertEqual(updated.frequency, 2)

    def test_concept_search_by_name(self) -> None:
        self.concept_repo.save(Concept(name="Neural Network"))
        self.concept_repo.save(Concept(name="Neural Architecture Search"))
        self.concept_repo.save(Concept(name="Support Vector Machine"))
        results = self.concept_repo.search_by_name("Neural")
        self.assertEqual(len(results), 2)

    # --- InvestigationRepository --------------------------------------------

    def test_investigation_save_and_find_by_id(self) -> None:
        inv = Investigation(
            title="LLM Safety Study",
            research_question="What are the key risks of frontier LLMs?",
        )
        self.investigation_repo.save(inv)
        found = self.investigation_repo.find_by_id(inv.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.title, "LLM Safety Study")

    def test_investigation_update_status(self) -> None:
        inv = Investigation(title="Status Test", research_question="Does status update?")
        self.investigation_repo.save(inv)
        self.investigation_repo.update_status(inv.id, "completed")
        updated = self.investigation_repo.find_by_id(inv.id)
        self.assertEqual(updated.status, "completed")

    def test_investigation_add_and_get_documents(self) -> None:
        inv = Investigation(title="Doc Linking", research_question="Q?")
        doc = Document(title="Linked Doc", content="Some content here")
        src = Source(title="Source for Doc", source_type="web")
        self.source_repo.save(src)
        self.document_repo.save(doc)
        self.investigation_repo.save(inv)
        self.investigation_repo.add_document(inv.id, doc.id)
        doc_ids = self.investigation_repo.get_documents(inv.id)
        self.assertIn(doc.id, doc_ids)

    def test_investigation_remove_document(self) -> None:
        inv = Investigation(title="Remove Doc Test", research_question="Q?")
        doc = Document(title="To Remove", content="Will be removed")
        self.document_repo.save(doc)
        self.investigation_repo.save(inv)
        self.investigation_repo.add_document(inv.id, doc.id)
        self.investigation_repo.remove_document(inv.id, doc.id)
        doc_ids = self.investigation_repo.get_documents(inv.id)
        self.assertNotIn(doc.id, doc_ids)

    def test_investigation_find_by_status(self) -> None:
        self.investigation_repo.save(
            Investigation(title="Active Inv", research_question="Q?", status="active")
        )
        self.investigation_repo.save(
            Investigation(title="Paused Inv", research_question="Q?", status="paused")
        )
        active = self.investigation_repo.find_by_status("active")
        self.assertTrue(all(i.status == "active" for i in active))


# ===========================================================================
# TestExceptions
# ===========================================================================

class TestExceptions(unittest.TestCase):
    """Verify the exception hierarchy and attribute contracts."""

    def test_orvia_error_is_base_exception(self) -> None:
        exc = OrviaError("test")
        self.assertIsInstance(exc, Exception)

    def test_validation_error_has_field(self) -> None:
        exc = ValidationError("bad value", field="email")
        self.assertEqual(exc.field, "email")
        self.assertIsInstance(exc, OrviaError)

    def test_not_found_error_attrs(self) -> None:
        exc = NotFoundError(entity="Document", id="abc-123")
        self.assertEqual(exc.entity, "Document")
        self.assertEqual(exc.id, "abc-123")
        self.assertIsInstance(exc, OrviaError)

    def test_duplicate_error_attrs(self) -> None:
        exc = DuplicateError(entity="Source", field="url")
        self.assertEqual(exc.entity, "Source")
        self.assertEqual(exc.field, "url")

    def test_database_error_inherits_orvia(self) -> None:
        self.assertTrue(issubclass(DatabaseError, OrviaError))

    def test_repository_error_inherits_orvia(self) -> None:
        self.assertTrue(issubclass(RepositoryError, OrviaError))


# ===========================================================================
# TestWorkspaceService
# ===========================================================================

class TestWorkspaceService(unittest.TestCase):
    """Tests for WorkspaceService health check and stats."""

    def setUp(self) -> None:
        self.db = _make_db()
        source_repo = SourceRepository(self.db)
        document_repo = DocumentRepository(self.db)
        topic_repo = TopicRepository(self.db)
        concept_repo = ConceptRepository(self.db)
        investigation_repo = InvestigationRepository(self.db)
        self.service = WorkspaceService(
            db=self.db,
            source_repo=source_repo,
            document_repo=document_repo,
            topic_repo=topic_repo,
            concept_repo=concept_repo,
            investigation_repo=investigation_repo,
        )

    def tearDown(self) -> None:
        self.db.disconnect()

    def test_health_check_returns_ok(self) -> None:
        result = self.service.health_check()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["database"])
        self.assertIn("version", result)
        self.assertIn("timestamp", result)

    def test_get_workspace_stats_returns_all_keys(self) -> None:
        stats = self.service.get_workspace_stats()
        for key in ("sources", "documents", "topics", "concepts", "investigations"):
            self.assertIn(key, stats)
            self.assertIsInstance(stats[key], int)

    def test_workspace_stats_increments(self) -> None:
        stats_before = self.service.get_workspace_stats()
        SourceRepository(self.db).save(Source(title="Stats Src", source_type="web"))
        stats_after = self.service.get_workspace_stats()
        self.assertEqual(stats_after["sources"], stats_before["sources"] + 1)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
