"""
orvia/app/repositories/__init__.py

Re-exports all repository classes.
"""

from orvia.app.repositories.base_repository import BaseRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.document_repository import DocumentRepository
from orvia.app.repositories.topic_repository import TopicRepository
from orvia.app.repositories.concept_repository import ConceptRepository


def __getattr__(name: str):
    if name == "InvestigationRepository":
        from orvia.app.investigations.repository import InvestigationRepository
        return InvestigationRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseRepository",
    "SourceRepository",
    "DocumentRepository",
    "TopicRepository",
    "ConceptRepository",
    "InvestigationRepository",
]

