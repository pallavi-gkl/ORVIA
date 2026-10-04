"""
Plain Text and Markdown Importer for ORVIA.
"""
from __future__ import annotations

from typing import Any

from orvia.app.core.exceptions import IngestionError
from orvia.app.ingestion.importers.base_importer import BaseImporter
from orvia.app.ingestion.normalizer import TextNormalizer
from orvia.app.ingestion.statistics import SourceStatisticsCalculator


class TextImporter(BaseImporter):
    """Importer for plain text and markdown documents (.txt, .text, .md)."""

    supported_extensions = frozenset({".txt", ".text", ".md", ".markdown"})

    def parse(self, file_bytes: bytes, filename: str) -> tuple[str, dict[str, Any]]:
        raw_text = self.decode_bytes(file_bytes)
        if not raw_text or not raw_text.strip():
            raise IngestionError(
                f"The file '{filename}' is empty. ORVIA cannot ingest sources with no content."
            )

        normalized = TextNormalizer.normalize(raw_text)
        if not normalized:
            raise IngestionError(
                f"The file '{filename}' contains only whitespace."
            )

        stats = SourceStatisticsCalculator.calculate_text_stats(normalized)
        stats["format"] = "plain_text"
        return normalized, stats
