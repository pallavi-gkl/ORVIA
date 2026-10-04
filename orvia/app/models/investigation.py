"""
Investigation model — a named research session in ORVIA.
Extended for Phase 8: Investigation Workspace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import json

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel, _now_iso, _new_uuid


# Case-insensitive tuple of valid status strings
VALID_STATUSES: tuple[str, ...] = (
    "draft", "active", "paused", "completed", "archived",
    "DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "ARCHIVED",
)


@dataclass
class Investigation(BaseModel):
    """
    Represents a focused research investigation with a guiding question,
    lifecycle status, description, notes, and provenance links.
    """

    title: str = ""
    research_question: str = ""
    status: str = "active"
    notes: Optional[str] = None
    description: str = ""
    completed_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError("Investigation title must not be empty.", field="title")
        if not self.research_question or not self.research_question.strip():
            raise ValidationError(
                "research_question must not be empty.", field="research_question"
            )
        norm_status = self.status.lower() if isinstance(self.status, str) else str(self.status)
        valid_lower = ("draft", "active", "paused", "completed", "archived")
        if norm_status not in valid_lower:
            raise ValidationError(
                f"status must be one of {VALID_STATUSES!r}; got {self.status!r}.",
                field="status",
            )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "research_question": self.research_question,
            "description": self.description,
            "status": self.status.lower() if isinstance(self.status, str) else str(self.status),
            "notes": self.notes,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata if isinstance(self.metadata, dict) else {},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Investigation":
        processed = dict(data)
        for dt_field in ("created_at", "updated_at", "completed_at"):
            if dt_field in processed and isinstance(processed[dt_field], str):
                processed[dt_field] = datetime.fromisoformat(processed[dt_field])
        if "metadata" in processed and isinstance(processed["metadata"], str):
            try:
                processed["metadata"] = json.loads(processed["metadata"])
            except Exception:
                processed["metadata"] = {}
        # Filter only fields that Investigation dataclass accepts
        valid_fields = {
            "id", "title", "research_question", "status", "notes",
            "description", "completed_at", "metadata", "created_at", "updated_at"
        }
        filtered = {k: v for k, v in processed.items() if k in valid_fields}
        return cls(**filtered)
