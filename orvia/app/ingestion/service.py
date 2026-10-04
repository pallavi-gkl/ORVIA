"""
SourceImportService — Core ingestion and validation service for ORVIA.
Coordinates format detection, normalization, deterministic statistics calculation,
duplicate detection, and atomic persistence.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from orvia.app.core.exceptions import IngestionError
from orvia.app.ingestion.importers.base_importer import BaseImporter, ImportResult
from orvia.app.ingestion.importers.csv_importer import CSVImporter
from orvia.app.ingestion.importers.json_importer import JSONImporter
from orvia.app.ingestion.importers.text_importer import TextImporter
from orvia.app.models.source import Source
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)

DEFAULT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


class SourceImportService:
    """Service responsible for validating, parsing, checking duplicates, and indexing sources."""

    def __init__(
        self,
        source_repo: SourceRepository,
        storage: Optional[FileStorage] = None,
        max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    ) -> None:
        self._source_repo = source_repo
        self._storage = storage
        self._max_file_size_bytes = max_file_size_bytes
        self._importers: list[BaseImporter] = []

        # Register default importers (extensible for PDF in later phases)
        self.register_importer(TextImporter())
        self.register_importer(CSVImporter())
        self.register_importer(JSONImporter())

    def register_importer(self, importer: BaseImporter) -> None:
        """Register a new file format importer."""
        self._importers.append(importer)

    def get_supported_extensions(self) -> set[str]:
        """Return all supported file extensions across registered importers."""
        supported = set()
        for imp in self._importers:
            supported.update(imp.supported_extensions)
        return supported

    def get_importer_for(self, filename: str) -> Optional[BaseImporter]:
        """Find the matching importer for a given filename."""
        for imp in self._importers:
            if imp.can_handle(filename):
                return imp
        return None

    def import_source(
        self,
        file_bytes: bytes,
        filename: str,
        force_duplicate: bool = False,
        custom_title: Optional[str] = None,
    ) -> ImportResult:
        """
        Validate, parse, normalize, check duplicates, and persist a source file.
        Returns an ImportResult with clear status and user-facing error message if failed.
        """
        clean_filename = Path(filename).name.strip()
        if not clean_filename:
            return ImportResult(
                success=False,
                error_message="Invalid filename provided. Please provide a valid file.",
            )

        # 1. Check file size
        file_size = len(file_bytes) if file_bytes else 0
        if file_size == 0:
            return ImportResult(
                success=False,
                filename=clean_filename,
                error_message=f"The file '{clean_filename}' is empty. ORVIA cannot ingest empty files.",
            )

        if file_size > self._max_file_size_bytes:
            max_mb = self._max_file_size_bytes / (1024 * 1024)
            return ImportResult(
                success=False,
                filename=clean_filename,
                file_size=file_size,
                error_message=f"File exceeds maximum allowed size ({max_mb:.0f} MB).",
            )

        # 2. Match importer
        importer = self.get_importer_for(clean_filename)
        if not importer:
            ext = Path(clean_filename).suffix.lower() or "no extension"
            supported_str = ", ".join(sorted(self.get_supported_extensions()))
            return ImportResult(
                success=False,
                filename=clean_filename,
                file_size=file_size,
                error_message=f"Unsupported format '{ext}'. Supported formats: {supported_str}",
            )

        # 3. Parse and normalize content
        try:
            normalized_content, stats = importer.parse(file_bytes, clean_filename)
        except IngestionError as exc:
            return ImportResult(
                success=False,
                filename=clean_filename,
                file_size=file_size,
                error_message=str(exc),
            )
        except Exception as exc:
            logger.exception("Unexpected error while parsing source %s", clean_filename)
            return ImportResult(
                success=False,
                filename=clean_filename,
                file_size=file_size,
                error_message=f"Failed to process '{clean_filename}': {exc}",
            )

        # 4. Deterministic content hash for duplicate detection
        content_hash = importer.compute_content_hash(normalized_content)

        # 5. Duplicate detection
        existing = self._source_repo.find_by_content_hash(content_hash)
        if existing is not None and not force_duplicate:
            return ImportResult(
                success=False,
                is_duplicate=True,
                duplicate_source_id=existing.id,
                title=existing.title,
                filename=clean_filename,
                file_type=existing.file_type or Path(clean_filename).suffix.lstrip(".").lower(),
                file_size=file_size,
                content_hash=content_hash,
                word_count=existing.word_count,
                character_count=existing.character_count,
                error_message=f"Existing source detected: '{existing.title}'. This exact content is already indexed in your library.",
            )

        # 6. Format file_type and title
        ext = Path(clean_filename).suffix.lstrip(".").lower()
        title = custom_title.strip() if custom_title and custom_title.strip() else Path(clean_filename).stem.replace("_", " ").title()

        now_iso = datetime.now(timezone.utc).isoformat()
        word_count = stats.get("word_count", 0)
        char_count = stats.get("character_count", 0)

        # 7. Persist to SourceRepository
        source = Source(
            title=title,
            source_type="file",
            filename=clean_filename,
            file_type=ext,
            content=normalized_content,
            file_size=file_size,
            imported_at=now_iso,
            word_count=word_count,
            character_count=char_count,
            content_hash=content_hash,
            metadata=stats,
        )

        try:
            saved = self._source_repo.save(source)
        except Exception as exc:
            logger.exception("Database error saving source %s", clean_filename)
            return ImportResult(
                success=False,
                filename=clean_filename,
                file_size=file_size,
                error_message="A database error occurred while saving the source. Please try again.",
            )

        # 8. Optional raw storage backup
        if self._storage:
            try:
                self._storage.save_file(
                    filename=f"{saved.id}_{clean_filename}",
                    content=file_bytes,
                    subfolder="sources",
                )
            except Exception as exc:
                logger.warning("Storage archive failed for source %s: %s", saved.id, exc)

        logger.info("Successfully imported source id=%s title=%s", saved.id, saved.title)
        return ImportResult(
            success=True,
            source_id=saved.id,
            title=saved.title,
            filename=clean_filename,
            file_type=ext,
            file_size=file_size,
            content=normalized_content,
            content_hash=content_hash,
            word_count=word_count,
            character_count=char_count,
            stats=stats,
        )
