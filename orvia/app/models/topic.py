"""
Topic model — a hierarchical knowledge category in ORVIA.

Note: the `topics` table only has `created_at`, not `updated_at`.
to_dict() deliberately omits updated_at for DB persistence.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel, _now_iso, _new_uuid


@dataclass
class Topic(BaseModel):
    """A topic node in the hierarchical knowledge taxonomy."""

    name: str = ""
    description: Optional[str] = None
    parent_topic_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValidationError("Topic name must not be empty.", field="name")
        if len(self.name) > 200:
            raise ValidationError(
                "Topic name must not exceed 200 characters.", field="name"
            )

    # ------------------------------------------------------------------
    # Serialisation — omits updated_at (not in DB schema)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return dict for DB persistence (no updated_at column in topics table)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parent_topic_id": self.parent_topic_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Topic":
        processed = dict(data)
        if "created_at" in processed and isinstance(processed["created_at"], str):
            processed["created_at"] = datetime.fromisoformat(processed["created_at"])
        # updated_at may not be in the DB row; fall back to created_at
        if "updated_at" not in processed:
            processed["updated_at"] = processed.get("created_at", _now_iso())
        elif isinstance(processed["updated_at"], str):
            processed["updated_at"] = datetime.fromisoformat(processed["updated_at"])
        return cls(**processed)
