"""
Abstract base repository for ORVIA data access layer.

All concrete repositories inherit from BaseRepository[T] and must implement
the five abstract methods that form the standard CRUD contract.
"""

from abc import ABC, abstractmethod
from typing import Generic, Optional, TypeVar

from orvia.app.core.database import DatabaseManager
from orvia.app.models.base import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseRepository(ABC, Generic[T]):
    """
    Generic repository base class.

    Subclasses are responsible for:
    - Defining TABLE (str) as a class attribute
    - Implementing all abstract CRUD methods
    - Serialising/deserialising model instances to/from dicts
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def save(self, entity: T) -> T:
        """Insert or update *entity* in the data store. Returns the saved entity."""

    @abstractmethod
    def find_by_id(self, id: str) -> Optional[T]:
        """Return the entity with the given *id*, or None if not found."""

    @abstractmethod
    def find_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """Return a paginated list of all entities."""

    @abstractmethod
    def delete(self, id: str) -> bool:
        """Delete the entity with the given *id*. Return True if a row was removed."""

    @abstractmethod
    def count(self) -> int:
        """Return the total number of entities in the backing table."""

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def exists(self, id: str) -> bool:
        """Return True if an entity with *id* exists in the data store."""
        row = self._db.fetchone(
            f"SELECT 1 FROM {self._get_table()} WHERE id = ?;", (id,)  # noqa: S608
        )
        return row is not None

    def _get_table(self) -> str:
        """Return the TABLE attribute defined on the concrete subclass."""
        table: str = getattr(self.__class__, "TABLE", "")
        if not table:
            raise AttributeError(
                f"{self.__class__.__name__} must define a TABLE class attribute."
            )
        return table
