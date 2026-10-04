"""
Deterministic Source Statistics Calculator for ORVIA.
Calculates real character, word, line, paragraph, CSV tabular, and JSON structure metrics.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any


class SourceStatisticsCalculator:
    """Calculates factual, deterministic statistics from source content."""

    @staticmethod
    def calculate_text_stats(content: str) -> dict[str, int]:
        """Calculate standard text statistics."""
        if not content:
            return {
                "character_count": 0,
                "character_count_no_spaces": 0,
                "word_count": 0,
                "line_count": 0,
                "paragraph_count": 0,
            }

        characters = len(content)
        characters_no_spaces = len("".join(content.split()))
        words = len(content.split())
        lines = len(content.split("\n"))
        # Count non-empty paragraphs separated by double newlines
        paragraphs = len([p for p in content.split("\n\n") if p.strip()])

        return {
            "character_count": characters,
            "character_count_no_spaces": characters_no_spaces,
            "word_count": words,
            "line_count": lines,
            "paragraph_count": max(paragraphs, 1 if words > 0 else 0),
        }

    @staticmethod
    def calculate_csv_stats(content: str) -> dict[str, Any]:
        """Parse CSV and extract tabular row, column, and header metrics."""
        text_stats = SourceStatisticsCalculator.calculate_text_stats(content)
        if not content.strip():
            return {
                **text_stats,
                "row_count": 0,
                "column_count": 0,
                "headers": [],
            }

        f = io.StringIO(content.strip())
        reader = csv.reader(f)
        try:
            first_row = next(reader, None)
            headers = [h.strip() for h in first_row] if first_row else []
            col_count = len(headers)
            row_count = sum(1 for _ in reader)  # Data rows excluding header
        except csv.Error:
            headers = []
            col_count = 0
            row_count = 0

        return {
            **text_stats,
            "row_count": row_count,
            "column_count": col_count,
            "headers": headers[:20],  # cap at first 20 headers preview
        }

    @staticmethod
    def calculate_json_stats(content: str) -> dict[str, Any]:
        """Parse JSON and extract structure type, item counts, and top-level keys."""
        text_stats = SourceStatisticsCalculator.calculate_text_stats(content)
        if not content.strip():
            return {
                **text_stats,
                "structure_type": "empty",
                "item_count": 0,
                "top_level_keys": [],
            }

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                structure_type = "object"
                top_level_keys = list(parsed.keys())
                item_count = len(top_level_keys)
            elif isinstance(parsed, list):
                structure_type = "array"
                item_count = len(parsed)
                top_level_keys = []
            else:
                structure_type = "scalar"
                item_count = 1
                top_level_keys = []
        except (json.JSONDecodeError, TypeError):
            structure_type = "invalid"
            item_count = 0
            top_level_keys = []

        return {
            **text_stats,
            "structure_type": structure_type,
            "item_count": item_count,
            "top_level_keys": top_level_keys[:30],  # preview top keys
        }
