"""
Text Normalization Layer for ORVIA Source Ingestion.
Standardizes Unicode, cleans extraneous repeated whitespace and line endings,
while preserving structural paragraphs and original semantic content.
"""
from __future__ import annotations

import re
import unicodedata


class TextNormalizer:
    """Deterministic, non-destructive text normalizer."""

    # Unicode non-breaking space, zero-width space, etc.
    _UNWANTED_SPACES = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")

    @classmethod
    def normalize(cls, text: str) -> str:
        """
        Normalize text content:
        1. Unicode normalization (NFC)
        2. Standardize line endings (\r\n, \r -> \n)
        3. Replace non-breaking and exotic whitespace with standard spaces
        4. Strip trailing whitespace from individual lines
        5. Collapse 3+ consecutive newlines to double newline (clean paragraph break)
        6. Strip leading/trailing surrounding document whitespace
        """
        if not text:
            return ""

        # 1. Unicode normalization (NFC produces composed characters)
        normalized = unicodedata.normalize("NFC", text)

        # 2. Convert carriage returns
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")

        # 3. Replace non-breaking & exotic spaces with regular space
        normalized = cls._UNWANTED_SPACES.sub(" ", normalized)

        # 4. Strip trailing spaces from lines and trim tabs if excessive
        lines = [line.rstrip() for line in normalized.split("\n")]

        # 5. Join lines and collapse 3+ consecutive newlines to 2
        joined = "\n".join(lines)
        joined = re.sub(r"\n{3,}", "\n\n", joined)

        # 6. Final strip of outer whitespace
        return joined.strip()

    @classmethod
    def clean_inline_whitespace(cls, s: str) -> str:
        """Collapse multiple inline spaces/tabs to a single space."""
        if not s:
            return ""
        return re.sub(r"[ \t]+", " ", s).strip()
