"""
BaseModel — foundation dataclass for all ORVIA domain models.

All models carry:
- id:         UUID4 string, auto-generated
- created_at: datetime, set on construction
- updated_at: datetime, set on construction (refreshed before persistence)
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from orvia.app.core.exceptions import ValidationError


def _now_iso() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


def _new_uuid() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


@dataclass
class BaseModel:
    """
    Abstract-like base for all ORVIA domain models.

    Subclasses should call super().__post_init__() if they define their own
    __post_init__ to ensure id/timestamps are populated.
    """

    id: str = field(default_factory=_new_uuid)
    created_at: datetime = field(default_factory=_now_iso)
    updated_at: datetime = field(default_factory=_now_iso)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize this model to a plain dictionary suitable for SQLite storage.

        - datetime fields are converted to ISO-format strings.
        - list / dict fields are JSON-encoded strings.
        Subclasses that omit updated_at from their schema should override this.
        """
        result: dict[str, Any] = {}
        for attr, value in self.__dict__.items():
            result[attr] = self._serialize_value(value)
        return result

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """Convert a Python value to its SQLite-storable representation."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (list, dict)):
            return json.dumps(value)
        return value

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BaseModel":
        """
        Reconstruct a model instance from a plain dictionary (e.g. a DB row).

        Subclasses should override this to handle JSON fields and datetime
        parsing specific to their schema.
        """
        processed = dict(data)
        for dt_field in ("created_at", "updated_at"):
            if dt_field in processed and isinstance(processed[dt_field], str):
                processed[dt_field] = datetime.fromisoformat(processed[dt_field])
        return cls(**processed)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Validate this model's field values.

        Raises:
            ValidationError: if any field violates its constraint.
        The base implementation performs no checks; subclasses override.
        """

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r})"
