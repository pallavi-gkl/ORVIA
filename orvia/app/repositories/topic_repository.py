"""
TopicRepository — persistence layer for Topic entities.

Important: the `topics` table has no `updated_at` column.
"""

import logging
from typing import Optional

from orvia.app.core.exceptions import RepositoryError
from orvia.app.models.topic import Topic
from orvia.app.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class TopicRepository(BaseRepository[Topic]):
    """CRUD and query operations for the `topics` table."""

    TABLE = "topics"

    # ------------------------------------------------------------------
    # BaseRepository implementation
    # ------------------------------------------------------------------

    def save(self, topic: Topic) -> Topic:
        """Insert or replace a Topic. Note: no updated_at in schema."""
        topic.validate()
        data = topic.to_dict()  # to_dict() already omits updated_at
        sql = """
            INSERT OR REPLACE INTO topics
                (id, name, description, parent_topic_id, created_at)
            VALUES
                (:id, :name, :description, :parent_topic_id, :created_at);
        """
        try:
            self._db.execute(sql, data)
            logger.debug("Saved Topic id=%s name=%s", topic.id, topic.name)
            return topic
        except Exception as exc:
            raise RepositoryError(f"Failed to save Topic: {exc}") from exc

    def find_by_id(self, id: str) -> Optional[Topic]:
        """Return a Topic by primary key, or None."""
        row = self._db.fetchone("SELECT * FROM topics WHERE id = ?;", (id,))
        if row is None:
            return None
        return Topic.from_dict(row)

    def find_all(self, limit: int = 100, offset: int = 0) -> list[Topic]:
        """Return a paginated list of all Topics."""
        rows = self._db.fetchall(
            "SELECT * FROM topics ORDER BY name ASC LIMIT ? OFFSET ?;",
            (limit, offset),
        )
        return [Topic.from_dict(r) for r in rows]

    def delete(self, id: str) -> bool:
        """Delete a Topic by id. Returns True if a row was deleted."""
        try:
            cursor = self._db.execute("DELETE FROM topics WHERE id = ?;", (id,))
            deleted = cursor.rowcount > 0
            if deleted:
                logger.debug("Deleted Topic id=%s", id)
            return deleted
        except Exception as exc:
            raise RepositoryError(f"Failed to delete Topic id={id}: {exc}") from exc

    def count(self) -> int:
        """Return the total number of Topic records."""
        row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM topics;")
        return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # Additional queries
    # ------------------------------------------------------------------

    def find_by_name(self, name: str) -> Optional[Topic]:
        """Return the Topic with a matching (exact, case-sensitive) name, or None."""
        row = self._db.fetchone(
            "SELECT * FROM topics WHERE name = ?;", (name,)
        )
        if row is None:
            return None
        return Topic.from_dict(row)

    def find_children(self, parent_id: str) -> list[Topic]:
        """Return all Topics that are direct children of *parent_id*."""
        rows = self._db.fetchall(
            "SELECT * FROM topics WHERE parent_topic_id = ? ORDER BY name ASC;",
            (parent_id,),
        )
        return [Topic.from_dict(r) for r in rows]

    def find_root_topics(self) -> list[Topic]:
        """Return all Topics at the root level (no parent)."""
        rows = self._db.fetchall(
            "SELECT * FROM topics WHERE parent_topic_id IS NULL ORDER BY name ASC;",
        )
        return [Topic.from_dict(r) for r in rows]
