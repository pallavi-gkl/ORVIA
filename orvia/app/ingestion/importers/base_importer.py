"""
Base Importer interface and result contracts for ORVIA Source Intelligence.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from orvia.app.core.exceptions import IngestionError


@dataclass
class ImportResult:
    """The result of a source import attempt."""

    success: bool
    source_id: Optional[str] = None
    title: Optional[str] = None
    filename: Optional[str] = None
    file_type: str = ""
    file_size: int = 0
    content: Optional[str] = None
    content_hash: Optional[str] = None
    word_count: int = 0
    character_count: int = 0
    stats: dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    is_duplicate: bool = False
    duplicate_source_id: Optional[str] = None


class BaseImporter(ABC):
    """Abstract base class for all file format importers."""

    supported_extensions: frozenset[str] = frozenset()

    def can_handle(self, filename: str) -> bool:
        """Check if this importer supports the given file extension."""
        if not filename:
            return False
        ext = Path(filename).suffix.lower()
        return ext in self.supported_extensions

    def decode_bytes(self, file_bytes: bytes) -> str:
        """
        Decode raw bytes into a string, gracefully attempting UTF-8,
        UTF-8-SIG (BOM), UTF-16, and Latin-1 encodings.
        """
        if not file_bytes:
            return ""

        encodings = ("utf-8", "utf-8-sig", "utf-16", "cp1252", "latin-1")
        for enc in encodings:
            try:
                return file_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue

        raise IngestionError(
            "Unable to decode file content. The file encoding is unrecognized or binary."
        )

    @staticmethod
    def compute_content_hash(text: str) -> str:
        """Return a deterministic SHA-256 fingerprint of the normalized text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str) -> tuple[str, dict[str, Any]]:
        """
        Validate and parse raw file bytes.
        Returns a tuple of (normalized_content, metadata_and_statistics_dict).
        Raises IngestionError if the content is malformed or invalid.
        """
        pass
