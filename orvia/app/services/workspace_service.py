"""
WorkspaceService — high-level operations for the ORVIA workspace.

Aggregates repository access into business-facing methods such as
workspace statistics and health checks.
"""

import logging
from datetime import datetime, timezone

from orvia.app.core.database import DatabaseManager
from orvia import __version__
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.document_repository import DocumentRepository
from orvia.app.repositories.investigation_repository import InvestigationRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.topic_repository import TopicRepository

logger = logging.getLogger(__name__)


class WorkspaceService:
    """
    Provides workspace-level operations: aggregated statistics and
    system health checks.
    """

    def __init__(
        self,
        db: DatabaseManager,
        source_repo: SourceRepository,
        document_repo: DocumentRepository,
        topic_repo: TopicRepository,
        concept_repo: ConceptRepository,
        investigation_repo: InvestigationRepository,
    ) -> None:
        self._db = db
        self._source_repo = source_repo
        self._document_repo = document_repo
        self._topic_repo = topic_repo
        self._concept_repo = concept_repo
        self._investigation_repo = investigation_repo
        logger.debug("WorkspaceService initialised.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_workspace_stats(self) -> dict:
        """
        Return entity counts for every major collection in the workspace.

        Returns:
            dict with keys: sources, documents, topics, concepts, investigations
        """
        stats = {
            "sources": self._source_repo.count(),
            "documents": self._document_repo.count(),
            "topics": self._topic_repo.count(),
            "concepts": self._concept_repo.count(),
            "investigations": self._investigation_repo.count(),
        }
        logger.info("Workspace stats: %s", stats)
        return stats

    def health_check(self) -> dict:
        """
        Perform a lightweight database connectivity check.

        Returns:
            dict with keys: status ('ok'|'error'), database (bool),
                            version (str), timestamp (str ISO-8601)
        """
        db_ok = False
        try:
            self._db.fetchone("SELECT 1 AS ping;")
            db_ok = True
        except Exception as exc:
            logger.error("Health check DB ping failed: %s", exc)

        result = {
            "status": "ok" if db_ok else "error",
            "database": db_ok,
            "version": __version__,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        logger.info("Health check result: %s", result)
        return result
