"""
Concept model — a named knowledge entity within a topic in ORVIA.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel, _now_iso, _new_uuid


@dataclass
class Concept(BaseModel):
    """A distinct knowledge concept, optionally linked to a Topic."""

    name: str = ""
    topic_id: Optional[str] = None
    definition: Optional[str] = None
    aliases: list[str] = field(default_factory=list)
    frequency: int = 0

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValidationError("Concept name must not be empty.", field="name")

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "topic_id": self.topic_id,
            "definition": self.definition,
            "aliases": json.dumps(self.aliases),
            "frequency": self.frequency,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Concept":
        processed = dict(data)
        for dt_field in ("created_at", "updated_at"):
            if dt_field in processed and isinstance(processed[dt_field], str):
                processed[dt_field] = datetime.fromisoformat(processed[dt_field])
        raw_aliases = processed.get("aliases")
        if isinstance(raw_aliases, str):
            try:
                processed["aliases"] = json.loads(raw_aliases)
            except (json.JSONDecodeError, TypeError):
                processed["aliases"] = []
        elif raw_aliases is None:
            processed["aliases"] = []
        return cls(**processed)
