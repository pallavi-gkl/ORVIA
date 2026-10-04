"""
InvestigationRepository — persistence layer for Investigation entities.
Re-exports the enhanced InvestigationRepository from orvia.app.investigations.repository
for Phase 8 while retaining 100% backward compatibility for Phase 1.
"""
from orvia.app.investigations.repository import InvestigationRepository

__all__ = ["InvestigationRepository"]
