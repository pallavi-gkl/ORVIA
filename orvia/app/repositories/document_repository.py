"""
DocumentRepository — persistence layer for Document entities.
"""

import logging
from typing import Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import RepositoryError
from orvia.app.models.document import Document
from orvia.app.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class DocumentRepository(BaseRepository[Document]):
    """CRUD and query operations for the `documents` table."""

    TABLE = "documents"

    # ------------------------------------------------------------------
    # BaseRepository implementation
    # ------------------------------------------------------------------

    def save(self, document: Document) -> Document:
        """Insert or replace a Document record."""
        document.validate()
        data = document.to_dict()
        sql = """
            INSERT OR REPLACE INTO documents
                (id, source_id, title, content, summary, word_count,
                 language, tags, content_hash, created_at, updated_at)
            VALUES
                (:id, :source_id, :title, :content, :summary, :word_count,
                 :language, :tags, :content_hash, :created_at, :updated_at);
        """
        try:
            self._db.execute(sql, data)
            logger.debug("Saved Document id=%s", document.id)
            return document
        except Exception as exc:
            raise RepositoryError(f"Failed to save Document: {exc}") from exc

    def find_by_id(self, id: str) -> Optional[Document]:
        """Return a Document by primary key, or None."""
        row = self._db.fetchone("SELECT * FROM documents WHERE id = ?;", (id,))
        if row is None:
            return None
        return Document.from_dict(row)

    def find_all(self, limit: int = 100, offset: int = 0) -> list[Document]:
        """Return a paginated list of all Documents."""
        rows = self._db.fetchall(
            "SELECT * FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?;",
            (limit, offset),
        )
        return [Document.from_dict(r) for r in rows]

    def delete(self, id: str) -> bool:
        """Delete a Document by id. Returns True if a row was deleted."""
        try:
            cursor = self._db.execute("DELETE FROM documents WHERE id = ?;", (id,))
            deleted = cursor.rowcount > 0
            if deleted:
                logger.debug("Deleted Document id=%s", id)
            return deleted
        except Exception as exc:
            raise RepositoryError(f"Failed to delete Document id={id}: {exc}") from exc

    def count(self) -> int:
        """Return the total number of Document records."""
        row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM documents;")
        return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # Additional queries
    # ------------------------------------------------------------------

    def find_by_source(self, source_id: str) -> list[Document]:
        """Return all Documents belonging to a given source."""
        rows = self._db.fetchall(
            "SELECT * FROM documents WHERE source_id = ? ORDER BY created_at DESC;",
            (source_id,),
        )
        return [Document.from_dict(r) for r in rows]

    def find_by_tag(self, tag: str) -> list[Document]:
        """
        Return Documents whose JSON tags array contains *tag*.
        Uses SQLite JSON LIKE search — basic but dependency-free.
        """
        # The tags column stores a JSON array, e.g. '["ai", "nlp"]'
        rows = self._db.fetchall(
            "SELECT * FROM documents WHERE tags LIKE ? ORDER BY created_at DESC;",
            (f'%"{tag}"%',),
        )
        return [Document.from_dict(r) for r in rows]

    def find_by_content_hash(self, hash_value: str) -> Optional[Document]:
        """Return the Document with a matching SHA-256 content hash, or None."""
        row = self._db.fetchone(
            "SELECT * FROM documents WHERE content_hash = ?;", (hash_value,)
        )
        if row is None:
            return None
        return Document.from_dict(row)

    def search_by_title(self, query: str) -> list[Document]:
        """Return Documents whose title contains *query* (case-insensitive LIKE)."""
        rows = self._db.fetchall(
            "SELECT * FROM documents WHERE title LIKE ? ORDER BY created_at DESC;",
            (f"%{query}%",),
        )
        return [Document.from_dict(r) for r in rows]

    def search_content(self, query: str) -> list[Document]:
        """
        Basic full-text search over document content using LIKE.
        This is suitable for Phase 1; Phase 2+ will upgrade to SQLite FTS5.
        """
        rows = self._db.fetchall(
            "SELECT * FROM documents WHERE content LIKE ? ORDER BY created_at DESC;",
            (f"%{query}%",),
        )
        return [Document.from_dict(r) for r in rows]
