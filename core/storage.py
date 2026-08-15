"""
core/storage.py
---------------
Storage Layer: Handles all low-level filesystem operations (create, validate, read, write, delete, move).
No other component should touch the filesystem directly.
"""

import os
import shutil
import logging
from pathlib import Path
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class StorageLayer:
    def create_directory(self, path: Path) -> Path:
        """Creates directory and its parent directories if they do not exist."""
        path = Path(path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def validate_directory(self, path: Path) -> Tuple[bool, str]:
        """Validates if a path is a directory and is writable."""
        path = Path(path).resolve()
        if not path.exists():
            return False, "Directory does not exist."
        if not path.is_dir():
            return False, "Path is not a directory."
        
        # Cross-platform writability check
        try:
            test_file = path / ".write_test"
            test_file.touch()
            test_file.unlink()
            return True, ""
        except Exception as e:
            return False, f"Permission denied: {e}"

    def write_file(self, path: Path, data: str, encoding: str = "utf-8"):
        """Writes text content to a file atomically using a temp file."""
        path = Path(path).resolve()
        self.create_directory(path.parent)
        temp_file = path.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding=encoding) as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            temp_file.replace(path)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)
            raise IOError(f"Failed to write file atomically: {e}")

    def read_file(self, path: Path, encoding: str = "utf-8") -> str:
        """Reads text content from a file."""
        path = Path(path).resolve()
        with open(path, "r", encoding=encoding) as f:
            return f.read()

    def write_bin_file(self, path: Path, data: bytes):
        """Writes binary data to a file atomically."""
        path = Path(path).resolve()
        self.create_directory(path.parent)
        temp_file = path.with_suffix(".tmp")
        try:
            with open(temp_file, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            temp_file.replace(path)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)
            raise IOError(f"Failed to write binary file atomically: {e}")

    def read_bin_file(self, path: Path) -> bytes:
        """Reads binary content from a file."""
        path = Path(path).resolve()
        with open(path, "rb") as f:
            return f.read()

    def delete_file(self, path: Path) -> bool:
        """Removes a file. Returns True if successful, False otherwise."""
        path = Path(path).resolve()
        try:
            if path.exists():
                path.unlink()
                return True
        except Exception as e:
            logger.error(f"Failed to delete file {path}: {e}")
        return False

    def move_file(self, src: Path, dest: Path) -> bool:
        """Moves or renames a file/directory. Returns True if successful."""
        src = Path(src).resolve()
        dest = Path(dest).resolve()
        try:
            if src.exists():
                self.create_directory(dest.parent)
                shutil.move(str(src), str(dest))
                return True
        except Exception as e:
            logger.error(f"Failed to move {src} to {dest}: {e}")
        return False
