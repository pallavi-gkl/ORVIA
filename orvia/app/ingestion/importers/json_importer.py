"""
JSON (JavaScript Object Notation) Importer for ORVIA.
"""
from __future__ import annotations

import json
from typing import Any

from orvia.app.core.exceptions import IngestionError
from orvia.app.ingestion.importers.base_importer import BaseImporter
from orvia.app.ingestion.statistics import SourceStatisticsCalculator


class JSONImporter(BaseImporter):
    """Importer for structured JSON documents (.json)."""

    supported_extensions = frozenset({".json"})

    def parse(self, file_bytes: bytes, filename: str) -> tuple[str, dict[str, Any]]:
        raw_text = self.decode_bytes(file_bytes)
        if not raw_text or not raw_text.strip():
            raise IngestionError(
                f"The JSON file '{filename}' is empty. ORVIA cannot ingest sources with no data."
            )

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise IngestionError(
                f"Invalid JSON syntax in '{filename}' at line {exc.lineno}, column {exc.colno}: {exc.msg}."
            ) from exc

        # Format with consistent 2-space indentation for clean reading & hashing
        normalized = json.dumps(parsed, indent=2, ensure_ascii=False)

        stats = SourceStatisticsCalculator.calculate_json_stats(normalized)
        stats["format"] = "structured_json"

        return normalized, stats
