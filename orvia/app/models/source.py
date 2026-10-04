"""
Source model — represents a bibliographic/content source in ORVIA.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from orvia.app.core.exceptions import ValidationError
from orvia.app.models.base import BaseModel

VALID_SOURCE_TYPES: frozenset[str] = frozenset({"web", "file", "manual", "api"})


@dataclass
class Source(BaseModel):
    """A research content source (uploaded file, document, web article, or manual entry)."""

    title: str = ""
    source_type: str = "manual"
    url: Optional[str] = None
    author: Optional[str] = None
    published_date: Optional[str] = None
    domain: Optional[str] = None
    reliability_score: float = 0.5
    filename: Optional[str] = None
    file_type: Optional[str] = None  # 'txt', 'csv', 'json', etc.
    content: Optional[str] = None
    file_size: int = 0
    modified_at: Optional[str] = None
    imported_at: Optional[str] = None
    word_count: int = 0
    character_count: int = 0
    content_hash: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError("Source title must not be empty.", field="title")
        if self.source_type not in VALID_SOURCE_TYPES:
            raise ValidationError(
                f"source_type must be one of {sorted(VALID_SOURCE_TYPES)!r}; "
                f"got {self.source_type!r}.",
                field="source_type",
            )
        if not (0.0 <= self.reliability_score <= 1.0):
            raise ValidationError(
                "reliability_score must be between 0.0 and 1.0.",
                field="reliability_score",
            )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source_type": self.source_type,
            "url": self.url,
            "author": self.author,
            "published_date": self.published_date,
            "domain": self.domain,
            "reliability_score": self.reliability_score,
            "filename": self.filename,
            "file_type": self.file_type,
            "content": self.content,
            "file_size": self.file_size,
            "modified_at": self.modified_at,
            "imported_at": self.imported_at,
            "word_count": self.word_count,
            "character_count": self.character_count,
            "content_hash": self.content_hash,
            "metadata": json.dumps(self.metadata) if isinstance(self.metadata, dict) else self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Source":
        processed = dict(data)
        for dt_field in ("created_at", "updated_at"):
            if dt_field in processed and isinstance(processed[dt_field], str):
                processed[dt_field] = datetime.fromisoformat(processed[dt_field])
        raw_meta = processed.get("metadata")
        if isinstance(raw_meta, str):
            try:
                processed["metadata"] = json.loads(raw_meta)
            except (json.JSONDecodeError, TypeError):
                processed["metadata"] = {}
        elif raw_meta is None:
            processed["metadata"] = {}

        # Default integers and strings
        processed.setdefault("filename", None)
        processed.setdefault("file_type", None)
        processed.setdefault("content", None)
        processed.setdefault("file_size", 0)
        processed.setdefault("modified_at", None)
        processed.setdefault("imported_at", None)
        processed.setdefault("word_count", 0)
        processed.setdefault("character_count", 0)
        processed.setdefault("content_hash", None)

        return cls(**processed)
