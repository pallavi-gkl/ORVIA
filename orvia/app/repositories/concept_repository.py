"""
ConceptRepository — persistence layer for Concept entities.
"""

import logging
from typing import Optional

from orvia.app.core.exceptions import RepositoryError
from orvia.app.models.concept import Concept
from orvia.app.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class ConceptRepository(BaseRepository[Concept]):
    """CRUD and query operations for the `concepts` table."""

    TABLE = "concepts"

    # ------------------------------------------------------------------
    # BaseRepository implementation
    # ------------------------------------------------------------------

    def save(self, concept: Concept) -> Concept:
        """Insert or replace a Concept record."""
        concept.validate()
        data = concept.to_dict()
        sql = """
            INSERT OR REPLACE INTO concepts
                (id, name, definition, topic_id, aliases, frequency,
                 created_at, updated_at)
            VALUES
                (:id, :name, :definition, :topic_id, :aliases, :frequency,
                 :created_at, :updated_at);
        """
        try:
            self._db.execute(sql, data)
            logger.debug("Saved Concept id=%s name=%s", concept.id, concept.name)
            return concept
        except Exception as exc:
            raise RepositoryError(f"Failed to save Concept: {exc}") from exc

    def find_by_id(self, id: str) -> Optional[Concept]:
        """Return a Concept by primary key, or None."""
        row = self._db.fetchone("SELECT * FROM concepts WHERE id = ?;", (id,))
        if row is None:
            return None
        return Concept.from_dict(row)

    def find_all(self, limit: int = 100, offset: int = 0) -> list[Concept]:
        """Return a paginated list of all Concepts."""
        rows = self._db.fetchall(
            "SELECT * FROM concepts ORDER BY name ASC LIMIT ? OFFSET ?;",
            (limit, offset),
        )
        return [Concept.from_dict(r) for r in rows]

    def delete(self, id: str) -> bool:
        """Delete a Concept by id. Returns True if a row was deleted."""
        try:
            cursor = self._db.execute("DELETE FROM concepts WHERE id = ?;", (id,))
            deleted = cursor.rowcount > 0
            if deleted:
                logger.debug("Deleted Concept id=%s", id)
            return deleted
        except Exception as exc:
            raise RepositoryError(f"Failed to delete Concept id={id}: {exc}") from exc

    def count(self) -> int:
        """Return the total number of Concept records."""
        row = self._db.fetchone("SELECT COUNT(*) AS cnt FROM concepts;")
        return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # Additional queries
    # ------------------------------------------------------------------

    def find_by_topic(self, topic_id: str) -> list[Concept]:
        """Return all Concepts belonging to a given topic."""
        rows = self._db.fetchall(
            "SELECT * FROM concepts WHERE topic_id = ? ORDER BY name ASC;",
            (topic_id,),
        )
        return [Concept.from_dict(r) for r in rows]

    def find_by_name(self, name: str) -> Optional[Concept]:
        """Return the first Concept with an exact name match, or None."""
        row = self._db.fetchone(
            "SELECT * FROM concepts WHERE name = ? LIMIT 1;", (name,)
        )
        if row is None:
            return None
        return Concept.from_dict(row)

    def search_by_name(self, query: str) -> list[Concept]:
        """Return Concepts whose name contains *query* (LIKE search)."""
        rows = self._db.fetchall(
            "SELECT * FROM concepts WHERE name LIKE ? ORDER BY frequency DESC;",
            (f"%{query}%",),
        )
        return [Concept.from_dict(r) for r in rows]

    def increment_frequency(self, concept_id: str) -> None:
        """Atomically increment the frequency counter for a Concept."""
        try:
            self._db.execute(
                "UPDATE concepts SET frequency = frequency + 1 WHERE id = ?;",
                (concept_id,),
            )
            logger.debug("Incremented frequency for Concept id=%s", concept_id)
        except Exception as exc:
            raise RepositoryError(
                f"Failed to increment frequency for Concept id={concept_id}: {exc}"
            ) from exc
