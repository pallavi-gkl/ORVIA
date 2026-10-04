"""
Relationship model — directed edge between two Concepts in ORVIA.

Note: the `relationships` table has only `created_at`, not `updated_at`.
to_dict() omits updated_at accordingly.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel, _now_iso, _new_uuid

VALID_TYPES: tuple[str, ...] = (
    "related_to",
    "contradicts",
    "supports",
    "derives_from",
    "part_of",
    "causes",
    "precedes",
)


@dataclass
class Relationship(BaseModel):
    """A typed, weighted directional relationship between two Concepts."""

    source_concept_id: str = ""
    target_concept_id: str = ""
    relationship_type: str = "related_to"
    strength: float = 0.5
    evidence_count: int = 0

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        if not self.source_concept_id:
            raise ValidationError(
                "source_concept_id must not be empty.", field="source_concept_id"
            )
        if not self.target_concept_id:
            raise ValidationError(
                "target_concept_id must not be empty.", field="target_concept_id"
            )
        if self.source_concept_id == self.target_concept_id:
            raise ValidationError(
                "source_concept_id and target_concept_id must differ.",
                field="source_concept_id",
            )
        if self.relationship_type not in VALID_TYPES:
            raise ValidationError(
                f"relationship_type must be one of {VALID_TYPES!r}; "
                f"got {self.relationship_type!r}.",
                field="relationship_type",
            )
        if not (0.0 <= self.strength <= 1.0):
            raise ValidationError(
                "strength must be between 0.0 and 1.0.", field="strength"
            )

    # ------------------------------------------------------------------
    # Serialisation — omits updated_at (not in DB schema)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_concept_id": self.source_concept_id,
            "target_concept_id": self.target_concept_id,
            "relationship_type": self.relationship_type,
            "strength": self.strength,
            "evidence_count": self.evidence_count,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relationship":
        processed = dict(data)
        if "created_at" in processed and isinstance(processed["created_at"], str):
            processed["created_at"] = datetime.fromisoformat(processed["created_at"])
        if "updated_at" not in processed:
            processed["updated_at"] = processed.get("created_at", _now_iso())
        elif isinstance(processed["updated_at"], str):
            processed["updated_at"] = datetime.fromisoformat(processed["updated_at"])
        return cls(**processed)
