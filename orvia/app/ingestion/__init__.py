"""
ORVIA Ingestion Package — Data Ingestion & Source Intelligence.
"""
from orvia.app.ingestion.importers.base_importer import BaseImporter, ImportResult
from orvia.app.ingestion.importers.csv_importer import CSVImporter
from orvia.app.ingestion.importers.json_importer import JSONImporter
from orvia.app.ingestion.importers.text_importer import TextImporter
from orvia.app.ingestion.normalizer import TextNormalizer
from orvia.app.ingestion.service import SourceImportService
from orvia.app.ingestion.statistics import SourceStatisticsCalculator

__all__ = [
    "BaseImporter",
    "ImportResult",
    "TextImporter",
    "CSVImporter",
    "JSONImporter",
    "TextNormalizer",
    "SourceStatisticsCalculator",
    "SourceImportService",
]
