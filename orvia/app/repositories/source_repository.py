"""
SourceRepository — persistence layer for Source research entities.
"""
from __future__ import annotations

import logging
from typing import Optional

from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import RepositoryError
from orvia.app.models.source import Source
from orvia.app.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SourceRepository(BaseRepository[Source]):
    """CRUD and optimized metadata queries for the `sources` table."""

    TABLE = "sources"

    # ------------------------------------------------------------------
    # BaseRepository implementation
    # ------------------------------------------------------------------

    def save(self, source: Source) -> Source:
        """Insert or replace a Source record in the database."""
        source.validate()
        data = source.to_dict()
        sql = """
            INSERT OR REPLACE INTO sources
                (id, title, url, source_type, author, published_date,
                 domain, reliability_score, filename, file_type, content,
                 file_size, modified_at, imported_at, word_count,
                 character_count, content_hash, metadata, created_at, updated_at)
            VALUES
                (:id, :title, :url, :source_type, :author, :published_date,
                 :domain, :reliability_score, :filename, :file_type, :content,
                 :file_size, :modified_at, :imported_at, :word_count,
                 :character_count, :content_hash, :metadata, :created_at, :updated_at);
        """
        try:
            self._db.execute(sql, data)
            logger.debug("Saved Source id=%s title=%s", source.id, source.title)
            return source
        except Exception as exc:
            raise RepositoryError(f"Failed to save Source: {exc}") from exc

    def find_by_id(self, id: str) -> Optional[Source]:
        """Return a full Source by primary key (including content), or None."""
        row = self._db.fetchone(
            "SELECT * FROM sources WHERE id = ?;", (id,)
        )
        if row is None:
            return None
        return Source.from_dict(row)

    def find_by_content_hash(self, content_hash: str) -> Optional[Source]:
        """Return a Source matching the given deterministic content hash, or None."""
        if not content_hash:
            return None
        row = self._db.fetchone(
            "SELECT * FROM sources WHERE content_hash = ? LIMIT 1;", (content_hash,)
        )
        if row is None:
            return None
        return Source.from_dict(row)

    def find_all(self, limit: int = 100, offset: int = 0) -> list[Source]:
        """Return a paginated list of all full Sources."""
        rows = self._db.fetchall(
            "SELECT * FROM sources ORDER BY created_at DESC LIMIT ? OFFSET ?;",
            (limit, offset),
        )
        return [Source.from_dict(r) for r in rows]

    def find_all_metadata(
        self,
        limit: int = 100,
        offset: int = 0,
        file_type: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: str = "newest",
    ) -> list[dict]:
        """
        Return paginated source records WITHOUT loading heavy content into memory.
        Used by the Research Library UI for high performance.
        """
        conditions: list[str] = []
        params: list[object] = []

        if file_type and file_type.lower() != "all":
            conditions.append("LOWER(file_type) = ?")
            params.append(file_type.lower())

        if search_query and search_query.strip():
            conditions.append("(title LIKE ? OR filename LIKE ?)")
            q = f"%{search_query.strip()}%"
            params.extend([q, q])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        order_clauses = {
            "newest": "ORDER BY created_at DESC",
            "oldest": "ORDER BY created_at ASC",
            "name": "ORDER BY title COLLATE NOCASE ASC",
            "size": "ORDER BY file_size DESC",
        }
        order_clause = order_clauses.get(sort_by, "ORDER BY created_at DESC")

        sql = f"""
            SELECT id, title, filename, file_type, source_type, file_size,
                   imported_at, word_count, character_count, reliability_score,
                   created_at, updated_at
            FROM sources
            {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])

        rows = self._db.fetchall(sql, tuple(params))
        return [dict(r) for r in rows]

    def update_title(self, id: str, new_title: str) -> bool:
        """Update the title of an existing source."""
        if not new_title or not new_title.strip():
            return False
        try:
            cursor = self._db.execute(
                "UPDATE sources SET title = ?, updated_at = datetime('now') WHERE id = ?;",
                (new_title.strip(), id),
            )
            return cursor.rowcount > 0
        except Exception as exc:
            raise RepositoryError(f"Failed to update Source title: {exc}") from exc

    def delete(self, id: str) -> bool:
        """Delete a Source by id. Returns True if a row was deleted."""
        try:
            cursor = self._db.execute("DELETE FROM sources WHERE id = ?;", (id,))
            deleted = cursor.rowcount > 0
            if deleted:
                logger.debug("Deleted Source id=%s", id)
            return deleted
        except Exception as exc:
            raise RepositoryError(f"Failed to delete Source id={id}: {exc}") from exc

    def count(self, file_type: Optional[str] = None) -> int:
        """Return the total number of Source records, optionally filtered by file_type."""
        if file_type and file_type.lower() != "all":
            row = self._db.fetchone(
                "SELECT COUNT(*) AS cnt FROM sources WHERE LOWER(file_type) = ?;",
                (file_type.lower(),),
            )
        else:
            row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM sources;")
        return int(row["cnt"]) if row else 0

    def count_by_type(self) -> dict[str, int]:
        """Return count breakdown by file_type."""
        rows = self._db.fetchall(
            "SELECT COALESCE(file_type, 'other') AS ftype, COUNT(*) AS cnt FROM sources GROUP BY ftype;"
        )
        counts = {"all": self.count(), "txt": 0, "csv": 0, "json": 0}
        for r in rows:
            ft = str(r["ftype"]).lower()
            counts[ft] = int(r["cnt"])
        return counts

    # ------------------------------------------------------------------
    # Additional queries
    # ------------------------------------------------------------------

    def find_by_source_type(self, source_type: str) -> list[Source]:
        """Return all Sources of a given source_type."""
        rows = self._db.fetchall(
            "SELECT * FROM sources WHERE source_type = ? ORDER BY created_at DESC;",
            (source_type,),
        )
        return [Source.from_dict(r) for r in rows]

    def find_by_domain(self, domain: str) -> list[Source]:
        """Return all Sources from a given domain."""
        rows = self._db.fetchall(
            "SELECT * FROM sources WHERE domain = ? ORDER BY created_at DESC;",
            (domain,),
        )
        return [Source.from_dict(r) for r in rows]

    def search_by_title(self, query: str) -> list[Source]:
        """Return Sources whose title contains *query* (case-insensitive LIKE)."""
        rows = self._db.fetchall(
            "SELECT * FROM sources WHERE title LIKE ? ORDER BY created_at DESC;",
            (f"%{query}%",),
        )
        return [Source.from_dict(r) for r in rows]
