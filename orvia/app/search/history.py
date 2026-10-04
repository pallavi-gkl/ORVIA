"""
Search History & Analytics Subsystem for ORVIA Search Intelligence.
Maintains a local SQLite-backed search query audit log, tracking recent searches,
popular terms, and zero-result queries without storing sensitive source content.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from orvia.app.core.database import DatabaseManager

logger = logging.getLogger(__name__)


class SearchHistoryManager:
    """
    Manages search history recording, query frequency analytics, and history cleanup.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def record_search(self, query: str, result_count: int) -> None:
        """
        Record a user search query event into the local history log.
        """
        clean_query = (query or "").strip()
        if not clean_query:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        rec_id = str(uuid.uuid4())

        try:
            sql = """
            INSERT INTO search_history (id, query, result_count, created_at)
            VALUES (?, ?, ?, ?);
            """
            self.db.execute(sql, (rec_id, clean_query, result_count, now_iso))
        except Exception as exc:
            logger.warning("Failed to record search history for '%s': %s", clean_query, exc)

    def get_recent_searches(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Retrieve recent searches ordered by latest timestamp.
        Returns unique queries preserving their latest result count.
        """
        sql = """
        SELECT query, result_count, MAX(created_at) as latest_time
        FROM search_history
        GROUP BY query
        ORDER BY latest_time DESC
        LIMIT ?;
        """
        try:
            rows = self.db.fetchall(sql, (limit,))
            return [
                {
                    "query": r["query"],
                    "result_count": r["result_count"],
                    "created_at": r["latest_time"],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Failed to fetch recent searches: %s", exc)
            return []

    def get_popular_searches(self, limit: int = 5) -> list[dict[str, Any]]:
        """
        Identify frequently searched terms based on actual search history.
        Only returns terms that have actually been searched.
        """
        sql = """
        SELECT query, COUNT(*) as search_count, MAX(result_count) as last_hits
        FROM search_history
        GROUP BY query
        HAVING COUNT(*) > 0
        ORDER BY search_count DESC, MAX(created_at) DESC
        LIMIT ?;
        """
        try:
            rows = self.db.fetchall(sql, (limit,))
            return [
                {
                    "query": r["query"],
                    "count": r["search_count"],
                    "search_count": r["search_count"],
                    "last_hits": r["last_hits"],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Failed to fetch popular searches: %s", exc)
            return []

    def get_zero_result_queries(self, limit: int = 5) -> list[dict[str, Any]]:
        """
        Identify queries that returned zero results to help uncover research knowledge gaps.
        """
        sql = """
        SELECT query, COUNT(*) as query_count, MAX(created_at) as last_attempted
        FROM search_history
        WHERE result_count = 0
        GROUP BY query
        ORDER BY query_count DESC, last_attempted DESC
        LIMIT ?;
        """
        try:
            rows = self.db.fetchall(sql, (limit,))
            return [
                {
                    "query": r["query"],
                    "attempts": r["query_count"],
                    "last_attempted": r["last_attempted"],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Failed to fetch zero-result queries: %s", exc)
            return []

    def clear_history(self) -> bool:
        """
        Clear all recorded search history.
        """
        try:
            self.db.execute("DELETE FROM search_history;")
            return True
        except Exception as exc:
            logger.warning("Failed to clear search history: %s", exc)
            return False
