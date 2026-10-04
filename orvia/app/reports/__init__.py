"""
orvia.app.reports — Phase 10 Research Reports & Evidence Synthesis System.
"""

from orvia.app.reports.models import (
    Report,
    ReportSection,
    ReportSource,
    ReportEvidence,
    ReportFinding,
    ReportStatus,
    ReportSectionType,
    ReportQualityMetrics,
    ReportVersionDiff,
    VALID_REPORT_STATUSES,
    VALID_SECTION_TYPES,
)
from orvia.app.reports.repository import ReportRepository
from orvia.app.reports.service import ResearchReportService
from orvia.app.reports.synthesis import ReportSynthesisEngine
from orvia.app.reports.quality import ReportQualityAnalyzer
from orvia.app.reports.export import ReportExportService
from orvia.app.reports.comparison import ReportVersionComparator
from orvia.app.reports.citations import CitationManager

__all__ = [
    "Report",
    "ReportSection",
    "ReportSource",
    "ReportEvidence",
    "ReportFinding",
    "ReportStatus",
    "ReportSectionType",
    "ReportQualityMetrics",
    "ReportVersionDiff",
    "VALID_REPORT_STATUSES",
    "VALID_SECTION_TYPES",
    "ReportRepository",
    "ResearchReportService",
    "ReportSynthesisEngine",
    "ReportQualityAnalyzer",
    "ReportExportService",
    "ReportVersionComparator",
    "CitationManager",
]
