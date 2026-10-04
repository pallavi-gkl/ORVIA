"""
Evidence model — links a document excerpt to a concept in ORVIA.

Note: the `evidences` table has only `created_at`, not `updated_at`.
to_dict() omits updated_at accordingly.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel, _now_iso, _new_uuid


@dataclass
class Evidence(BaseModel):
    """
    A piece of evidence connecting a document excerpt to a concept,
    with an associated relevance score.
    """

    document_id: str = ""
    concept_id: str = ""
    excerpt: str = ""
    relevance_score: float = 0.5
    page_number: Optional[int] = None
    position: Optional[int] = None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        if not self.excerpt or not self.excerpt.strip():
            raise ValidationError("Evidence excerpt must not be empty.", field="excerpt")
        if not (0.0 <= self.relevance_score <= 1.0):
            raise ValidationError(
                "relevance_score must be between 0.0 and 1.0.",
                field="relevance_score",
            )

    # ------------------------------------------------------------------
    # Serialisation — omits updated_at (not in DB schema)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "concept_id": self.concept_id,
            "excerpt": self.excerpt,
            "relevance_score": self.relevance_score,
            "page_number": self.page_number,
            "position": self.position,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        processed = dict(data)
        if "created_at" in processed and isinstance(processed["created_at"], str):
            processed["created_at"] = datetime.fromisoformat(processed["created_at"])
        if "updated_at" not in processed:
            processed["updated_at"] = processed.get("created_at", _now_iso())
        elif isinstance(processed["updated_at"], str):
            processed["updated_at"] = datetime.fromisoformat(processed["updated_at"])
        return cls(**processed)
