"""
Internal citation system for Phase 10 Research Reports.

Provides:
- Stable, sequential citation labels for sources: [1], [2], [3], etc.
- Evidence citation labels with precise location references: [1, p. 4], [2, Section 3], [3]
- Reference list formatting with full source metadata
"""

from __future__ import annotations

from typing import Any, Optional


class CitationManager:
    """
    Manages deterministic, stable citation mapping for a report.
    """

    @staticmethod
    def generate_source_citations(sources: list[Any]) -> dict[str, str]:
        """
        Assign stable [1], [2], [3] numeric labels to sources in sequential order.
        Returns a dictionary mapping source_id -> citation_label.
        """
        citations: dict[str, str] = {}
        for idx, src in enumerate(sources, start=1):
            src_id = src.id if hasattr(src, "id") else src.get("id")
            if src_id:
                citations[src_id] = f"[{idx}]"
        return citations

    @staticmethod
    def format_evidence_citation(source_label: str, location: Optional[str] = None) -> str:
        """
        Format an evidence citation label using the source label and optional exact location.
        Example:
          source_label="[1]", location="p. 14" -> "[1, p. 14]"
          source_label="[2]", location="" -> "[2]"
        Never invents locations or page numbers.
        """
        if not source_label:
            return "[?]"

        clean_label = source_label.strip()
        # Extract bare number if wrapped in brackets e.g. "[1]" -> "1"
        inner = clean_label[1:-1] if clean_label.startswith("[") and clean_label.endswith("]") else clean_label

        if location and location.strip():
            loc_str = location.strip()
            # If user already wrote 'p. 4', use it; else keep as given
            return f"[{inner}, {loc_str}]"
        return f"[{inner}]"

    @staticmethod
    def format_reference_entry(citation_label: str, source: Any) -> str:
        """
        Format a formal bibliographic entry for a source.
        Example: [1] Machine Learning Foundations — Author (2024). Source: pdf
        """
        title = getattr(source, "title", None) or (source.get("title") if isinstance(source, dict) else "Untitled Source")
        author = getattr(source, "author", None) or (source.get("author") if isinstance(source, dict) else "")
        url = getattr(source, "url", None) or (source.get("url") if isinstance(source, dict) else "")
        file_type = getattr(source, "file_type", None) or (source.get("file_type") if isinstance(source, dict) else "")
        published_date = getattr(source, "published_date", None) or (source.get("published_date") if isinstance(source, dict) else "")

        parts = [f"{citation_label} **{title}**"]
        meta_items = []
        if author:
            meta_items.append(f"Author: {author}")
        if published_date:
            meta_items.append(f"Date: {published_date}")
        if file_type:
            meta_items.append(f"Format: {file_type.upper()}")
        if url:
            meta_items.append(f"URL: {url}")

        if meta_items:
            parts.append(f" ({', '.join(meta_items)})")
        return "".join(parts)
