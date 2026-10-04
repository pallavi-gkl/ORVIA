"""
Custom exception hierarchy for ORVIA.
All application exceptions derive from OrviaError for easy top-level handling.
"""


class OrviaError(Exception):
    """Base exception for all ORVIA application errors."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r})"


class DatabaseError(OrviaError):
    """Raised when a database operation fails."""


class ValidationError(OrviaError):
    """Raised when a model fails validation."""

    def __init__(self, message: str, field: str = "") -> None:
        super().__init__(message)
        self.field = field

    def __repr__(self) -> str:
        return f"ValidationError(field={self.field!r}, message={self.message!r})"


class NotFoundError(OrviaError):
    """Raised when a requested entity does not exist in the data store."""

    def __init__(self, entity: str, id: str) -> None:
        super().__init__(f"{entity} with id '{id}' was not found.")
        self.entity = entity
        self.id = id

    def __repr__(self) -> str:
        return f"NotFoundError(entity={self.entity!r}, id={self.id!r})"


class DuplicateError(OrviaError):
    """Raised when a uniqueness constraint would be violated."""

    def __init__(self, entity: str, field: str) -> None:
        super().__init__(f"{entity} with the same {field} already exists.")
        self.entity = entity
        self.field = field

    def __repr__(self) -> str:
        return f"DuplicateError(entity={self.entity!r}, field={self.field!r})"


class IngestionError(OrviaError):
    """Raised when document or source ingestion fails."""


class RepositoryError(OrviaError):
    """Raised when a repository operation fails unexpectedly."""
