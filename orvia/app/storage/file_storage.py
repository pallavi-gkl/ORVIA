"""
FileStorage — filesystem abstraction for ORVIA binary/text file management.

Provides a clean interface for saving, reading, deleting, and listing files
within a configurable base directory, with subfolder support.
"""

import logging
from pathlib import Path

from orvia.app.core.exceptions import OrviaError

logger = logging.getLogger(__name__)


class FileStorage:
    """
    Simple file-system storage manager rooted at *base_path*.

    All operations are relative to *base_path* and create intermediate
    directories as needed.
    """

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path
        self._base_path.mkdir(parents=True, exist_ok=True)
        logger.debug("FileStorage initialised at: %s", self._base_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_file(
        self, filename: str, content: bytes, subfolder: str = ""
    ) -> Path:
        """
        Write *content* to *filename* (optionally inside *subfolder*).

        Creates all intermediate directories.  Returns the full Path of the
        saved file.
        """
        target_dir = self._base_path / subfolder if subfolder else self._base_path
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename
        try:
            file_path.write_bytes(content)
            logger.debug("Saved file: %s (%d bytes)", file_path, len(content))
            return file_path
        except OSError as exc:
            raise OrviaError(f"Failed to save file '{file_path}': {exc}") from exc

    def read_file(self, filepath: Path) -> bytes:
        """
        Read and return the raw bytes of *filepath*.

        Args:
            filepath: Absolute or base-relative Path to the file.

        Raises:
            OrviaError: if the file does not exist or cannot be read.
        """
        resolved = self._resolve(filepath)
        if not resolved.exists():
            raise OrviaError(f"File not found: {resolved}")
        try:
            data = resolved.read_bytes()
            logger.debug("Read file: %s (%d bytes)", resolved, len(data))
            return data
        except OSError as exc:
            raise OrviaError(f"Failed to read file '{resolved}': {exc}") from exc

    def delete_file(self, filepath: Path) -> bool:
        """
        Delete *filepath*.  Returns True if the file was deleted, False if it
        did not exist.

        Raises:
            OrviaError: on permission or OS errors.
        """
        resolved = self._resolve(filepath)
        if not resolved.exists():
            logger.debug("delete_file: file not found (no-op): %s", resolved)
            return False
        try:
            resolved.unlink()
            logger.debug("Deleted file: %s", resolved)
            return True
        except OSError as exc:
            raise OrviaError(f"Failed to delete file '{resolved}': {exc}") from exc

    def list_files(self, subfolder: str = "") -> list[Path]:
        """
        Return a sorted list of all file Paths inside *subfolder* (or the base
        directory if *subfolder* is empty). Only immediate children are listed
        (non-recursive).
        """
        target_dir = self._base_path / subfolder if subfolder else self._base_path
        if not target_dir.exists():
            return []
        return sorted(p for p in target_dir.iterdir() if p.is_file())

    def file_exists(self, filepath: Path) -> bool:
        """Return True if *filepath* exists and is a regular file."""
        resolved = self._resolve(filepath)
        return resolved.is_file()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve(self, filepath: Path) -> Path:
        """Return *filepath* as-is if absolute, otherwise resolve relative to base."""
        if filepath.is_absolute():
            return filepath
        return self._base_path / filepath
