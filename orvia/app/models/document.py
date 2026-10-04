"""
Document model — represents an ingested piece of content in ORVIA.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel, _now_iso, _new_uuid


@dataclass
class Document(BaseModel):
    """
    A document derived from a Source (or standalone).

    word_count and content_hash are computed automatically in __post_init__.
    """

    title: str = ""
    content: str = ""
    source_id: Optional[str] = None
    summary: Optional[str] = None
    word_count: int = 0
    language: str = "en"
    tags: list[str] = field(default_factory=list)
    content_hash: Optional[str] = None

    def __post_init__(self) -> None:
        # Auto-compute word count
        if self.content:
            self.word_count = len(self.content.split())
        # Auto-compute SHA-256 content hash
        if self.content and not self.content_hash:
            self.content_hash = hashlib.sha256(
                self.content.encode("utf-8")
            ).hexdigest()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError("Document title must not be empty.", field="title")
        if not self.content or not self.content.strip():
            raise ValidationError("Document content must not be empty.", field="content")

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "source_id": self.source_id,
            "summary": self.summary,
            "word_count": self.word_count,
            "language": self.language,
            "tags": json.dumps(self.tags),
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Document":
        processed = dict(data)
        for dt_field in ("created_at", "updated_at"):
            if dt_field in processed and isinstance(processed[dt_field], str):
                processed[dt_field] = datetime.fromisoformat(processed[dt_field])
        raw_tags = processed.get("tags")
        if isinstance(raw_tags, str):
            try:
                processed["tags"] = json.loads(raw_tags)
            except (json.JSONDecodeError, TypeError):
                processed["tags"] = []
        elif raw_tags is None:
            processed["tags"] = []
        # Provide content_hash to prevent __post_init__ recalculation
        return cls(**processed)
