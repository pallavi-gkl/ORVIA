"""
DatabaseManager — SQLite connection and schema management for ORVIA.

Features:
- WAL journal mode for concurrent reads
- Foreign key enforcement
- dict-like row access via sqlite3.Row factory
- Context-manager support
- Centralised schema creation (idempotent)
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

from orvia.app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Thin wrapper around sqlite3 that provides:
    - WAL mode + foreign key pragma on connect
    - Helper methods: execute, executemany, fetchone, fetchall
    - Idempotent schema initialisation
    - Context-manager protocol
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path: Path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        logger.debug("DatabaseManager created for path: %s", db_path)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the SQLite connection and configure pragmas."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                str(self._db_path), check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL;")
            self._connection.execute("PRAGMA foreign_keys=ON;")
            self._connection.commit()
            logger.info("Database connected: %s", self._db_path)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to connect to database: {exc}") from exc

    def disconnect(self) -> None:
        """Close the SQLite connection if open."""
        if self._connection is not None:
            try:
                self._connection.close()
                logger.info("Database disconnected: %s", self._db_path)
            except sqlite3.Error as exc:
                logger.warning("Error during disconnect: %s", exc)
            finally:
                self._connection = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "DatabaseManager":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        self.disconnect()
        return False  # do not suppress exceptions

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> sqlite3.Connection:
        if self._connection is None:
            raise DatabaseError(
                "No active database connection. Call connect() first."
            )
        return self._connection

    def execute(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> sqlite3.Cursor:
        """Execute a single SQL statement and commit.  Returns the cursor."""
        conn = self._ensure_connected()
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor
        except sqlite3.Error as exc:
            conn.rollback()
            logger.error("execute() failed — SQL: %s | params: %s | error: %s", sql, params, exc)
            raise DatabaseError(f"execute failed: {exc}") from exc

    def executemany(
        self, sql: str, params_list: list[tuple[Any, ...]]
    ) -> sqlite3.Cursor:
        """Execute a SQL statement against a list of parameter tuples."""
        conn = self._ensure_connected()
        try:
            cursor = conn.executemany(sql, params_list)
            conn.commit()
            return cursor
        except sqlite3.Error as exc:
            conn.rollback()
            logger.error("executemany() failed — SQL: %s | error: %s", sql, exc)
            raise DatabaseError(f"executemany failed: {exc}") from exc

    def fetchone(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> Optional[dict]:
        """Execute a SELECT and return the first row as a plain dict, or None."""
        conn = self._ensure_connected()
        try:
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row is not None else None
        except sqlite3.Error as exc:
            logger.error("fetchone() failed — SQL: %s | error: %s", sql, exc)
            raise DatabaseError(f"fetchone failed: {exc}") from exc

    def fetchall(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> list[dict]:
        """Execute a SELECT and return all rows as a list of plain dicts."""
        conn = self._ensure_connected()
        try:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            logger.error("fetchall() failed — SQL: %s | error: %s", sql, exc)
            raise DatabaseError(f"fetchall failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Online Backup & Data Safety (Phase 12)
    # ------------------------------------------------------------------

    def create_backup(self, backup_dir: Optional[Path | str] = None) -> Path:
        """
        Create a consistent, point-in-time backup snapshot of the SQLite database.
        Uses SQLite's online backup API, which is non-blocking and safe in WAL mode.
        Returns the Path to the newly created backup file.
        """
        conn = self._ensure_connected()
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        if backup_dir is None:
            target_dir = self._db_path.parent / "backups"
        else:
            target_dir = Path(backup_dir)

        target_dir.mkdir(parents=True, exist_ok=True)
        backup_path = target_dir / f"orvia_backup_{timestamp}.db"

        dest_conn = sqlite3.connect(str(backup_path))
        try:
            with dest_conn:
                conn.backup(dest_conn)
            logger.info("Database backup created successfully: %s", backup_path)
            return backup_path
        except sqlite3.Error as exc:
            logger.error("Database backup failed: %s", exc)
            raise DatabaseError(f"Database backup failed: {exc}") from exc
        finally:
            dest_conn.close()

    def list_backups(self, backup_dir: Optional[Path | str] = None) -> list[dict[str, Any]]:
        """
        List all available backup files with size and creation timestamps.
        Ordered by most recent first.
        """
        if backup_dir is None:
            target_dir = self._db_path.parent / "backups"
        else:
            target_dir = Path(backup_dir)

        if not target_dir.exists():
            return []

        backups = []
        from datetime import datetime, timezone
        for p in sorted(target_dir.glob("orvia_backup_*.db"), reverse=True):
            stat = p.stat()
            size_kb = stat.st_size / 1024
            size_display = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.2f} MB"
            backups.append({
                "filename": p.name,
                "path": str(p),
                "size_bytes": stat.st_size,
                "size_display": size_display,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return backups

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def initialize_schema(self) -> None:
        """Create all application tables and indexes (idempotent), then run migrations."""
        conn = self._ensure_connected()
        ddl_statements = self._build_ddl()
        try:
            for ddl in ddl_statements:
                conn.execute(ddl)
            self._migrate(conn)
            conn.commit()
            logger.info("Database schema initialised successfully.")
        except sqlite3.Error as exc:
            conn.rollback()
            raise DatabaseError(f"Schema initialisation failed: {exc}") from exc

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Run incremental column migrations to ensure schema compatibility."""
        cursor = conn.execute("PRAGMA table_info(sources);")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        column_defs = [
            ("filename", "TEXT"),
            ("file_type", "TEXT"),
            ("content", "TEXT"),
            ("file_size", "INTEGER DEFAULT 0"),
            ("modified_at", "TEXT"),
            ("imported_at", "TEXT"),
            ("word_count", "INTEGER DEFAULT 0"),
            ("character_count", "INTEGER DEFAULT 0"),
            ("content_hash", "TEXT"),
        ]

        for col_name, col_type in column_defs:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE sources ADD COLUMN {col_name} {col_type};")
                logger.info("Migrated sources table: added column %s", col_name)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_file_type ON sources(file_type);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_content_hash ON sources(content_hash);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_title ON sources(title);")

        # Investigations table columns migration (Phase 8)
        cursor = conn.execute("PRAGMA table_info(investigations);")
        existing_inv_cols = {row["name"] for row in cursor.fetchall()}
        inv_column_defs = [
            ("description", "TEXT DEFAULT ''"),
            ("completed_at", "TEXT"),
            ("metadata", "TEXT"),
        ]
        for col_name, col_type in inv_column_defs:
            if col_name not in existing_inv_cols:
                conn.execute(f"ALTER TABLE investigations ADD COLUMN {col_name} {col_type};")
                logger.info("Migrated investigations table: added column %s", col_name)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_investigations_status ON investigations(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_investigations_created_at ON investigations(created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_investigations_updated_at ON investigations(updated_at);")

        cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='investigations';")
        row = cur.fetchone()
        if row and row["sql"] and "draft" not in row["sql"].lower():
            logger.info("Migrating investigations table CHECK constraint to include 'draft'")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS investigations_phase8 (
                    id                TEXT PRIMARY KEY,
                    title             TEXT NOT NULL,
                    research_question TEXT NOT NULL,
                    description       TEXT DEFAULT '',
                    status            TEXT DEFAULT 'active' CHECK(status IN (
                        'draft','active','paused','completed','archived'
                    )),
                    notes             TEXT,
                    completed_at      TEXT,
                    metadata          TEXT,
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL
                );
            """)
            conn.execute("""
                INSERT OR IGNORE INTO investigations_phase8
                    (id, title, research_question, description, status, notes, completed_at, metadata, created_at, updated_at)
                SELECT
                    id, title, research_question,
                    COALESCE(description, ''),
                    status, notes, completed_at, metadata, created_at, updated_at
                FROM investigations;
            """)
            conn.execute("DROP TABLE investigations;")
            conn.execute("ALTER TABLE investigations_phase8 RENAME TO investigations;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_investigations_status ON investigations(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_investigations_created_at ON investigations(created_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_investigations_updated_at ON investigations(updated_at);")

        # Phase 11 tables migration
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_activities (
                id            TEXT PRIMARY KEY,
                activity_type TEXT NOT NULL,
                entity_type   TEXT NOT NULL,
                entity_id     TEXT,
                title         TEXT NOT NULL,
                description   TEXT DEFAULT '',
                metadata      TEXT DEFAULT '{}',
                created_at    TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_act_type ON research_activities(activity_type);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_act_entity ON research_activities(entity_type, entity_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_act_created ON research_activities(created_at);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_context_state (
                id                     TEXT PRIMARY KEY DEFAULT 'current',
                active_investigation_id TEXT REFERENCES investigations(id) ON DELETE SET NULL,
                active_source_id        TEXT REFERENCES sources(id) ON DELETE SET NULL,
                active_concept_id       TEXT REFERENCES concepts(id) ON DELETE SET NULL,
                active_report_id        TEXT REFERENCES reports(id) ON DELETE SET NULL,
                updated_at             TEXT NOT NULL
            );
        """)

        # Phase ingestion pipeline — concept_source_links offset columns
        cursor = conn.execute("PRAGMA table_info(concept_source_links);")
        existing_csl_cols = {row["name"] for row in cursor.fetchall()}
        if "first_occurrence" not in existing_csl_cols:
            conn.execute(
                "ALTER TABLE concept_source_links ADD COLUMN first_occurrence INTEGER DEFAULT 0;"
            )
            logger.info("Migrated concept_source_links: added first_occurrence")
        if "last_occurrence" not in existing_csl_cols:
            conn.execute(
                "ALTER TABLE concept_source_links ADD COLUMN last_occurrence INTEGER DEFAULT 0;"
            )
            logger.info("Migrated concept_source_links: added last_occurrence")

    @staticmethod
    def _build_ddl() -> list[str]:
        """Return the ordered list of DDL statements for all tables + indexes."""
        return [
            # ----------------------------------------------------------------
            # sources
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS sources (
                id               TEXT PRIMARY KEY,
                title            TEXT NOT NULL,
                url              TEXT,
                source_type      TEXT NOT NULL CHECK(source_type IN ('web','file','manual','api')),
                author           TEXT,
                published_date   TEXT,
                domain           TEXT,
                reliability_score REAL DEFAULT 0.5,
                filename         TEXT,
                file_type        TEXT,
                content          TEXT,
                file_size        INTEGER DEFAULT 0,
                modified_at      TEXT,
                imported_at      TEXT,
                word_count       INTEGER DEFAULT 0,
                character_count  INTEGER DEFAULT 0,
                content_hash     TEXT,
                metadata         TEXT,
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_sources_source_type ON sources(source_type);",
            "CREATE INDEX IF NOT EXISTS idx_sources_domain ON sources(domain);",

            # ----------------------------------------------------------------
            # documents
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS documents (
                id            TEXT PRIMARY KEY,
                source_id     TEXT REFERENCES sources(id) ON DELETE SET NULL,
                title         TEXT NOT NULL,
                content       TEXT NOT NULL,
                summary       TEXT,
                word_count    INTEGER,
                language      TEXT DEFAULT 'en',
                tags          TEXT,
                content_hash  TEXT,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_documents_source_id ON documents(source_id);",
            "CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);",
            "CREATE INDEX IF NOT EXISTS idx_documents_language ON documents(language);",

            # ----------------------------------------------------------------
            # topics
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS topics (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL UNIQUE,
                description     TEXT,
                parent_topic_id TEXT REFERENCES topics(id) ON DELETE SET NULL,
                created_at      TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_topics_parent_topic_id ON topics(parent_topic_id);",

            # ----------------------------------------------------------------
            # concepts
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS concepts (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                definition TEXT,
                topic_id   TEXT REFERENCES topics(id) ON DELETE SET NULL,
                aliases    TEXT,
                frequency  INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_concepts_topic_id ON concepts(topic_id);",
            "CREATE INDEX IF NOT EXISTS idx_concepts_name ON concepts(name);",

            # ----------------------------------------------------------------
            # relationships
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS relationships (
                id                  TEXT PRIMARY KEY,
                source_concept_id   TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                target_concept_id   TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                relationship_type   TEXT NOT NULL CHECK(relationship_type IN (
                    'related_to','contradicts','supports','derives_from',
                    'part_of','causes','precedes'
                )),
                strength            REAL DEFAULT 0.5,
                evidence_count      INTEGER DEFAULT 0,
                created_at          TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_relationships_source_concept ON relationships(source_concept_id);",
            "CREATE INDEX IF NOT EXISTS idx_relationships_target_concept ON relationships(target_concept_id);",
            "CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);",

            # ----------------------------------------------------------------
            # evidences
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS evidences (
                id              TEXT PRIMARY KEY,
                document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                concept_id      TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                excerpt         TEXT NOT NULL,
                relevance_score REAL DEFAULT 0.5,
                page_number     INTEGER,
                position        INTEGER,
                created_at      TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_evidences_document_id ON evidences(document_id);",
            "CREATE INDEX IF NOT EXISTS idx_evidences_concept_id ON evidences(concept_id);",

            # ----------------------------------------------------------------
            # investigations (Phase 8 — Workspace)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigations (
                id                TEXT PRIMARY KEY,
                title             TEXT NOT NULL,
                research_question TEXT NOT NULL,
                description       TEXT DEFAULT '',
                status            TEXT DEFAULT 'active' CHECK(status IN (
                    'draft','active','paused','completed','archived'
                )),
                notes             TEXT,
                completed_at      TEXT,
                metadata          TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_investigations_status ON investigations(status);",
            "CREATE INDEX IF NOT EXISTS idx_investigations_created_at ON investigations(created_at);",
            "CREATE INDEX IF NOT EXISTS idx_investigations_updated_at ON investigations(updated_at);",

            # ----------------------------------------------------------------
            # investigation_documents (join table, Phase 1 compatibility)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_documents (
                investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                document_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                added_at         TEXT NOT NULL,
                PRIMARY KEY (investigation_id, document_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_docs_investigation ON investigation_documents(investigation_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_docs_document ON investigation_documents(document_id);",

            # ----------------------------------------------------------------
            # investigation_sources (Phase 8)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_sources (
                investigation_id   TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                source_id          TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                relationship_type  TEXT NOT NULL DEFAULT 'RELEVANT',
                notes              TEXT,
                added_at           TEXT NOT NULL,
                PRIMARY KEY (investigation_id, source_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_src_inv ON investigation_sources(investigation_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_src_src ON investigation_sources(source_id);",

            # ----------------------------------------------------------------
            # investigation_concepts (Phase 8)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_concepts (
                investigation_id   TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                concept_id         TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                role               TEXT NOT NULL DEFAULT 'KEY_CONCEPT',
                notes              TEXT,
                added_at           TEXT NOT NULL,
                PRIMARY KEY (investigation_id, concept_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_cpt_inv ON investigation_concepts(investigation_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_cpt_cpt ON investigation_concepts(concept_id);",

            # ----------------------------------------------------------------
            # investigation_evidence (Phase 8)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_evidence (
                id                 TEXT PRIMARY KEY,
                investigation_id   TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                source_id          TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                title              TEXT DEFAULT '',
                statement          TEXT NOT NULL,
                excerpt            TEXT DEFAULT '',
                location           TEXT DEFAULT '',
                evidence_type      TEXT NOT NULL DEFAULT 'OBSERVATION',
                confidence         REAL DEFAULT 1.0,
                notes              TEXT,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_ev_inv ON investigation_evidence(investigation_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_ev_src ON investigation_evidence(source_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_ev_type ON investigation_evidence(evidence_type);",

            # ----------------------------------------------------------------
            # investigation_notes (Phase 8)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_notes (
                id                 TEXT PRIMARY KEY,
                investigation_id   TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                title              TEXT DEFAULT '',
                content            TEXT NOT NULL,
                note_type          TEXT NOT NULL DEFAULT 'GENERAL',
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_notes_inv ON investigation_notes(investigation_id);",

            # ----------------------------------------------------------------
            # investigation_questions (Phase 8)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_questions (
                id                 TEXT PRIMARY KEY,
                investigation_id   TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                question           TEXT NOT NULL,
                status             TEXT NOT NULL DEFAULT 'OPEN',
                resolution_note    TEXT,
                resolved_at        TEXT,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_q_inv ON investigation_questions(investigation_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_q_status ON investigation_questions(status);",

            # ----------------------------------------------------------------
            # investigation_findings (Phase 8)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_findings (
                id                 TEXT PRIMARY KEY,
                investigation_id   TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                title              TEXT NOT NULL,
                statement          TEXT NOT NULL,
                status             TEXT NOT NULL DEFAULT 'DRAFT',
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_find_inv ON investigation_findings(investigation_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_find_status ON investigation_findings(status);",

            # ----------------------------------------------------------------
            # investigation_finding_evidence (Phase 8)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_finding_evidence (
                finding_id         TEXT NOT NULL REFERENCES investigation_findings(id) ON DELETE CASCADE,
                evidence_id        TEXT NOT NULL REFERENCES investigation_evidence(id) ON DELETE CASCADE,
                added_at           TEXT NOT NULL,
                PRIMARY KEY (finding_id, evidence_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_fe_finding ON investigation_finding_evidence(finding_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_fe_evidence ON investigation_finding_evidence(evidence_id);",

            # ----------------------------------------------------------------
            # investigation_activities (Phase 8)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS investigation_activities (
                id                 TEXT PRIMARY KEY,
                investigation_id   TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                activity_type      TEXT NOT NULL,
                description        TEXT NOT NULL,
                entity_type        TEXT,
                entity_id          TEXT,
                created_at         TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_act_inv ON investigation_activities(investigation_id);",
            "CREATE INDEX IF NOT EXISTS idx_inv_act_created ON investigation_activities(created_at);",

            # ----------------------------------------------------------------
            # search_history
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS search_history (
                id           TEXT PRIMARY KEY,
                query        TEXT NOT NULL,
                result_count INTEGER DEFAULT 0,
                created_at   TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_search_history_created_at ON search_history(created_at);",
            "CREATE INDEX IF NOT EXISTS idx_search_history_query ON search_history(query);",

            # ----------------------------------------------------------------
            # search_postings (index persistence)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS search_postings (
                term           TEXT NOT NULL,
                source_id      TEXT NOT NULL,
                term_frequency INTEGER NOT NULL,
                positions_json TEXT NOT NULL,
                in_title       INTEGER DEFAULT 0,
                PRIMARY KEY (term, source_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_search_postings_term ON search_postings(term);",
            "CREATE INDEX IF NOT EXISTS idx_search_postings_source ON search_postings(source_id);",

            # ----------------------------------------------------------------
            # search_source_stats
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS search_source_stats (
                source_id      TEXT PRIMARY KEY,
                token_count    INTEGER NOT NULL,
                title          TEXT NOT NULL,
                file_type      TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            );
            """,

            # ----------------------------------------------------------------
            # term_cooccurrences
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS term_cooccurrences (
                term_a             TEXT NOT NULL,
                term_b             TEXT NOT NULL,
                cooccurrence_count INTEGER DEFAULT 1,
                PRIMARY KEY (term_a, term_b)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_cooccurrences_term_a ON term_cooccurrences(term_a);",

            # ----------------------------------------------------------------
            # concept_source_links  (Phase 6 — Concept Intelligence)
            # Maps detected concepts to the sources they appear in.
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS concept_source_links (
                concept_id       TEXT NOT NULL,
                source_id        TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                occurrences      INTEGER DEFAULT 1,
                in_title         INTEGER DEFAULT 0,
                first_seen_at    TEXT NOT NULL,
                first_occurrence INTEGER DEFAULT 0,
                last_occurrence  INTEGER DEFAULT 0,
                PRIMARY KEY (concept_id, source_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_csl_concept_id ON concept_source_links(concept_id);",
            "CREATE INDEX IF NOT EXISTS idx_csl_source_id  ON concept_source_links(source_id);",

            # ----------------------------------------------------------------
            # concept_cooccurrences  (Phase 6)
            # Pairwise concept co-occurrence counted across the collection.
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS concept_cooccurrences (
                concept_a_id   TEXT NOT NULL,
                concept_b_id   TEXT NOT NULL,
                shared_sources INTEGER DEFAULT 1,
                strength       REAL    DEFAULT 0.0,
                PRIMARY KEY (concept_a_id, concept_b_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_cco_a ON concept_cooccurrences(concept_a_id);",
            "CREATE INDEX IF NOT EXISTS idx_cco_b ON concept_cooccurrences(concept_b_id);",

            # ----------------------------------------------------------------
            # analysis_status  (Phase 6)
            # Per-source concept analysis pipeline status.
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS analysis_status (
                source_id       TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
                status          TEXT DEFAULT 'not_analyzed'
                                     CHECK(status IN (
                                         'not_analyzed','analyzing','analyzed',
                                         'needs_reanalysis','error'
                                     )),
                concepts_found  INTEGER DEFAULT 0,
                analyzed_at     TEXT,
                error_message   TEXT
            );
            """,

            # ----------------------------------------------------------------
            # reports (Phase 10 — Research Reports & Synthesis)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS reports (
                id                TEXT PRIMARY KEY,
                investigation_id  TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                title             TEXT NOT NULL,
                subtitle          TEXT DEFAULT '',
                summary           TEXT DEFAULT '',
                status            TEXT NOT NULL DEFAULT 'DRAFT'
                                      CHECK(status IN ('DRAFT', 'IN_REVIEW', 'FINAL', 'ARCHIVED')),
                version           INTEGER NOT NULL DEFAULT 1,
                parent_report_id  TEXT REFERENCES reports(id) ON DELETE SET NULL,
                metadata          TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL,
                generated_at      TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_reports_investigation ON reports(investigation_id);",
            "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);",
            "CREATE INDEX IF NOT EXISTS idx_reports_version ON reports(investigation_id, version);",
            "CREATE INDEX IF NOT EXISTS idx_reports_parent ON reports(parent_report_id);",

            # ----------------------------------------------------------------
            # report_sections (Phase 10)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS report_sections (
                id           TEXT PRIMARY KEY,
                report_id    TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                section_type TEXT NOT NULL CHECK(section_type IN (
                    'EXECUTIVE_SUMMARY', 'RESEARCH_QUESTION', 'SCOPE', 'SOURCES',
                    'KEY_CONCEPTS', 'EVIDENCE', 'FINDINGS', 'COMPARISON',
                    'PATTERNS', 'RELATIONSHIPS', 'OPEN_QUESTIONS', 'LIMITATIONS',
                    'CONCLUSION', 'REFERENCES'
                )),
                title        TEXT NOT NULL,
                position     INTEGER NOT NULL DEFAULT 0,
                content      TEXT DEFAULT '',
                metadata     TEXT,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_rep_sec_report ON report_sections(report_id);",
            "CREATE INDEX IF NOT EXISTS idx_rep_sec_pos ON report_sections(report_id, position);",
            "CREATE INDEX IF NOT EXISTS idx_rep_sec_type ON report_sections(section_type);",

            # ----------------------------------------------------------------
            # report_sources (Phase 10 — Source citations in report)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS report_sources (
                report_id      TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                source_id      TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                citation_label TEXT NOT NULL,
                position       INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (report_id, source_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_rep_src_rep ON report_sources(report_id);",
            "CREATE INDEX IF NOT EXISTS idx_rep_src_src ON report_sources(source_id);",

            # ----------------------------------------------------------------
            # report_evidence (Phase 10 — Evidence provenance links in report)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS report_evidence (
                report_id      TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                evidence_id    TEXT NOT NULL REFERENCES investigation_evidence(id) ON DELETE CASCADE,
                section_id     TEXT REFERENCES report_sections(id) ON DELETE SET NULL,
                position       INTEGER NOT NULL DEFAULT 0,
                citation_label TEXT NOT NULL,
                PRIMARY KEY (report_id, evidence_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_rep_evi_rep ON report_evidence(report_id);",
            "CREATE INDEX IF NOT EXISTS idx_rep_evi_evi ON report_evidence(evidence_id);",
            "CREATE INDEX IF NOT EXISTS idx_rep_evi_sec ON report_evidence(section_id);",

            # ----------------------------------------------------------------
            # report_findings (Phase 10 — Finding links in report)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS report_findings (
                report_id   TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                finding_id  TEXT NOT NULL REFERENCES investigation_findings(id) ON DELETE CASCADE,
                section_id  TEXT REFERENCES report_sections(id) ON DELETE SET NULL,
                position    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (report_id, finding_id)
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_rep_fnd_rep ON report_findings(report_id);",
            "CREATE INDEX IF NOT EXISTS idx_rep_fnd_fnd ON report_findings(finding_id);",
            "CREATE INDEX IF NOT EXISTS idx_rep_fnd_sec ON report_findings(section_id);",

            # ----------------------------------------------------------------
            # research_activities (Phase 11 — Global research memory & activity log)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS research_activities (
                id            TEXT PRIMARY KEY,
                activity_type TEXT NOT NULL,
                entity_type   TEXT NOT NULL,
                entity_id     TEXT,
                title         TEXT NOT NULL,
                description   TEXT DEFAULT '',
                metadata      TEXT DEFAULT '{}',
                created_at    TEXT NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_act_type ON research_activities(activity_type);",
            "CREATE INDEX IF NOT EXISTS idx_act_entity ON research_activities(entity_type, entity_id);",
            "CREATE INDEX IF NOT EXISTS idx_act_created ON research_activities(created_at);",

            # ----------------------------------------------------------------
            # research_context_state (Phase 11 — Global active research context)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS research_context_state (
                id                     TEXT PRIMARY KEY DEFAULT 'current',
                active_investigation_id TEXT REFERENCES investigations(id) ON DELETE SET NULL,
                active_source_id        TEXT REFERENCES sources(id) ON DELETE SET NULL,
                active_concept_id       TEXT REFERENCES concepts(id) ON DELETE SET NULL,
                active_report_id        TEXT REFERENCES reports(id) ON DELETE SET NULL,
                updated_at             TEXT NOT NULL
            );
            """,
        ]
