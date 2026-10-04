"""
CSV (Comma-Separated Values) Importer for ORVIA.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from orvia.app.core.exceptions import IngestionError
from orvia.app.ingestion.importers.base_importer import BaseImporter
from orvia.app.ingestion.normalizer import TextNormalizer
from orvia.app.ingestion.statistics import SourceStatisticsCalculator


class CSVImporter(BaseImporter):
    """Importer for comma-separated value tables (.csv)."""

    supported_extensions = frozenset({".csv"})

    def parse(self, file_bytes: bytes, filename: str) -> tuple[str, dict[str, Any]]:
        raw_text = self.decode_bytes(file_bytes)
        if not raw_text or not raw_text.strip():
            raise IngestionError(
                f"The CSV file '{filename}' is empty. ORVIA cannot ingest sources with no data rows."
            )

        # Basic newline normalization
        normalized = TextNormalizer.normalize(raw_text)

        # Validate CSV parsability
        stream = io.StringIO(normalized)
        try:
            reader = csv.reader(stream)
            rows = list(reader)
        except csv.Error as exc:
            raise IngestionError(
                f"Invalid CSV format in '{filename}': {exc}. Please verify row delimiters and quotation marks."
            ) from exc

        if not rows or len(rows) == 0:
            raise IngestionError(f"The CSV file '{filename}' contains no rows.")

        stats = SourceStatisticsCalculator.calculate_csv_stats(normalized)
        stats["format"] = "tabular_csv"

        return normalized, stats
