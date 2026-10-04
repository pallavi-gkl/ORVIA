"""
Document Processing & Extraction Engine for ORVIA.
Converts ingested Source materials (TXT, CSV, JSON) into discrete,
structured Document entities with section splitting, tagging, and provenance linking.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from typing import Optional

from orvia.app.models.document import Document
from orvia.app.models.source import Source
from orvia.app.repositories.document_repository import DocumentRepository

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """
    Extracts and sections raw research sources into granular Document objects
    suitable for inverted indexing and synthesis.
    """

    def __init__(self, document_repo: DocumentRepository) -> None:
        self.document_repo = document_repo

    def process_source(self, source: Source, clean_existing: bool = True) -> list[Document]:
        """
        Process a single Source into one or more structured Document records.
        If clean_existing=True, deletes previously processed documents for this source_id.
        """
        if not source.content or not source.content.strip():
            logger.warning("Source id=%s has empty content; skipping processing.", source.id)
            return []

        if clean_existing:
            existing_docs = self.document_repo.find_by_source(source.id)
            for doc in existing_docs:
                self.document_repo.delete(doc.id)

        file_type = (source.file_type or "txt").lower()
        processed_docs: list[Document] = []

        if file_type in ("csv",):
            processed_docs = self._process_csv_source(source)
        elif file_type in ("json",):
            processed_docs = self._process_json_source(source)
        else:
            # Default: TXT, MD, Markdown
            processed_docs = self._process_text_source(source)

        # Fallback: if no granular sub-documents were generated, create a single document
        if not processed_docs:
            primary_doc = Document(
                source_id=source.id,
                title=source.title,
                content=source.content,
                summary=self._generate_summary(source.content),
                word_count=source.word_count,
                tags=["format:" + file_type, "primary"],
            )
            self.document_repo.save(primary_doc)
            processed_docs.append(primary_doc)

        logger.info(
            "Processed Source id=%s (%s) into %d Document entities.",
            source.id,
            source.title,
            len(processed_docs),
        )
        return processed_docs

    def _process_text_source(self, source: Source) -> list[Document]:
        """
        Segment plain text / markdown sources by markdown section headers (##)
        or double newlines if no headers are present.
        """
        content = source.content
        docs: list[Document] = []

        # Always create the primary comprehensive document
        primary_doc = Document(
            source_id=source.id,
            title=source.title,
            content=content,
            summary=self._generate_summary(content),
            word_count=source.word_count,
            tags=["format:txt", "primary"],
        )
        self.document_repo.save(primary_doc)
        docs.append(primary_doc)

        # Check for markdown headers: ## Header Name
        header_sections = re.split(r"\n(?=#{1,3}\s+)", content)
        if len(header_sections) > 1:
            for section in header_sections:
                sec_text = section.strip()
                if len(sec_text.split()) < 5:  # skip trivial headers
                    continue

                lines = sec_text.split("\n", 1)
                first_line = lines[0].strip()
                sec_title = re.sub(r"^#{1,3}\s*", "", first_line)
                sec_content = lines[1].strip() if len(lines) > 1 else sec_text

                sub_doc = Document(
                    source_id=source.id,
                    title=f"{source.title} — {sec_title}",
                    content=sec_content,
                    summary=self._generate_summary(sec_content),
                    word_count=len(sec_content.split()),
                    tags=["format:txt", "section", "header:" + sec_title.lower().replace(" ", "_")[:30]],
                )
                self.document_repo.save(sub_doc)
                docs.append(sub_doc)

        return docs

    def _process_csv_source(self, source: Source) -> list[Document]:
        """
        Process CSV source into structured records and a comprehensive summary document.
        """
        docs: list[Document] = []
        raw_csv = source.content.strip()

        # Primary document containing full CSV text
        primary_doc = Document(
            source_id=source.id,
            title=source.title,
            content=raw_csv,
            summary=f"Tabular dataset with headers from {source.filename}.",
            word_count=source.word_count,
            tags=["format:csv", "tabular", "dataset"],
        )
        self.document_repo.save(primary_doc)
        docs.append(primary_doc)

        # Parse rows to create row-level search documents
        try:
            reader = csv.DictReader(io.StringIO(raw_csv))
            row_idx = 1
            for row in reader:
                # Format each row into a readable narrative key-value block
                items = [f"{k}: {v}" for k, v in row.items() if v]
                row_content = " | ".join(items)
                first_val = list(row.values())[0] if row else f"Row {row_idx}"

                sub_doc = Document(
                    source_id=source.id,
                    title=f"{source.title} — {first_val}",
                    content=row_content,
                    summary=row_content[:150],
                    word_count=len(row_content.split()),
                    tags=["format:csv", "record", f"row:{row_idx}"],
                )
                self.document_repo.save(sub_doc)
                docs.append(sub_doc)
                row_idx += 1
                if row_idx > 50:  # limit individual row documents to top 50
                    break
        except Exception as exc:
            logger.warning("Could not parse rows for CSV source %s: %s", source.id, exc)

        return docs

    def _process_json_source(self, source: Source) -> list[Document]:
        """
        Process JSON source into logical child documents (e.g. paradigms, items).
        """
        docs: list[Document] = []
        raw_json = source.content.strip()

        primary_doc = Document(
            source_id=source.id,
            title=source.title,
            content=raw_json,
            summary=f"Structured JSON schema dataset from {source.filename}.",
            word_count=source.word_count,
            tags=["format:json", "structured"],
        )
        self.document_repo.save(primary_doc)
        docs.append(primary_doc)

        try:
            data = json.loads(raw_json)
            # If top level has array of entities (e.g., 'paradigms', 'items', 'models')
            if isinstance(data, dict):
                for key, val in data.items():
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        for item in val:
                            name = item.get("name") or item.get("title") or item.get("id") or "Entity"
                            item_str = json.dumps(item, indent=2)
                            sub_doc = Document(
                                source_id=source.id,
                                title=f"{source.title} — {name}",
                                content=item_str,
                                summary=item.get("description", item_str[:150]),
                                word_count=len(item_str.split()),
                                tags=["format:json", "entity", f"category:{key}"],
                            )
                            self.document_repo.save(sub_doc)
                            docs.append(sub_doc)
        except Exception as exc:
            logger.warning("Could not parse sub-elements for JSON source %s: %s", source.id, exc)

        return docs

    def _generate_summary(self, text: str, max_chars: int = 180) -> str:
        """Create a clean excerpt summary from content."""
        clean = " ".join(text.split())
        if len(clean) <= max_chars:
            return clean
        cut = clean[:max_chars]
        last_space = cut.rfind(" ")
        if last_space != -1:
            cut = cut[:last_space]
        return cut + "…"
