"""
ORVIA — Application Entry Point

Bootstraps the application: logging, configuration, database initialisation,
repository wiring, and a health/stats report.
"""

import logging
import sys

from orvia.app.core.config import Config
from orvia.app.core.database import DatabaseManager
from orvia.app.core.exceptions import OrviaError
from orvia.app.core.logging_config import setup_logging
from orvia.app.repositories.concept_repository import ConceptRepository
from orvia.app.repositories.document_repository import DocumentRepository
from orvia.app.repositories.investigation_repository import InvestigationRepository
from orvia.app.repositories.source_repository import SourceRepository
from orvia.app.repositories.topic_repository import TopicRepository
from orvia.app.services.workspace_service import WorkspaceService
from orvia import __version__, __app_name__


def main() -> None:
    """
    Bootstrap ORVIA:
    1. Configure logging
    2. Load configuration
    3. Ensure required directories exist
    4. Connect to and initialise the SQLite database
    5. Wire up repositories and services
    6. Run health-check and report workspace statistics
    """
    # ------------------------------------------------------------------ #
    # 1. Logging                                                          #
    # ------------------------------------------------------------------ #
    logger = setup_logging("INFO")

    # ------------------------------------------------------------------ #
    # 2. Configuration                                                    #
    # ------------------------------------------------------------------ #
    config = Config.from_env()
    logger.info("Configuration loaded: %r", config)

    # ------------------------------------------------------------------ #
    # 3. Directory scaffold                                               #
    # ------------------------------------------------------------------ #
    config.ensure_directories()

    # ------------------------------------------------------------------ #
    # 4. Startup banner                                                   #
    # ------------------------------------------------------------------ #
    banner = (
        "\n"
        "╔══════════════════════════════════════════════╗\n"
        f"║   {__app_name__} v{__version__}  — Research Intelligence       ║\n"
        "║   Personal Research Intelligence Workspace  ║\n"
        "╚══════════════════════════════════════════════╝"
    )
    logger.info(banner)

    db: DatabaseManager | None = None
    try:
        # -------------------------------------------------------------- #
        # 5. Database                                                     #
        # -------------------------------------------------------------- #
        db = DatabaseManager(db_path=config.DATABASE_PATH)
        db.connect()
        db.initialize_schema()
        logger.info("Database ready at: %s", config.DATABASE_PATH)

        # -------------------------------------------------------------- #
        # 6. Repositories                                                 #
        # -------------------------------------------------------------- #
        source_repo = SourceRepository(db)
        document_repo = DocumentRepository(db)
        topic_repo = TopicRepository(db)
        concept_repo = ConceptRepository(db)
        investigation_repo = InvestigationRepository(db)
        logger.info("Repositories initialised.")

        # -------------------------------------------------------------- #
        # 7. Services                                                     #
        # -------------------------------------------------------------- #
        workspace_service = WorkspaceService(
            db=db,
            source_repo=source_repo,
            document_repo=document_repo,
            topic_repo=topic_repo,
            concept_repo=concept_repo,
            investigation_repo=investigation_repo,
        )

        # -------------------------------------------------------------- #
        # 8. Health check                                                 #
        # -------------------------------------------------------------- #
        health = workspace_service.health_check()
        logger.info("Health check → %s", health)

        # -------------------------------------------------------------- #
        # 9. Workspace statistics                                         #
        # -------------------------------------------------------------- #
        stats = workspace_service.get_workspace_stats()
        logger.info("Workspace stats → %s", stats)

        logger.info(
            "ORVIA foundation initialised successfully. Ready for next phase."
        )

    except OrviaError as exc:
        logger.error("ORVIA error during startup: %s", exc)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        logger.critical("Unexpected error during startup: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        if db is not None:
            db.disconnect()
            logger.info("Database connection closed. Goodbye.")


if __name__ == "__main__":
    main()
