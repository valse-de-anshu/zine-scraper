"""
core/cache.py
-------------
Cache Layer: Manages temporary and cached files (thumbnails, metadata, temp files, and cleanup).
Delegates paths to PathAuthority and storage operations to StorageLayer.
"""

from pathlib import Path
from typing import Optional

from core.paths import PathAuthority
from core.storage import StorageLayer

class CacheLayer:
    def __init__(self, paths: PathAuthority, storage: StorageLayer):
        self._paths = paths
        self._storage = storage
        self._cache_root = self._paths.get_cache_root()
        self._storage.create_directory(self._cache_root)

    def get_cache_path(self, key: str, suffix: str = ".cache") -> Path:
        """Returns the resolved cache file path for a key and suffix."""
        # Sanitize key for filesystem
        safe_key = "".join([c for c in key if c.isalnum() or c in ".-_"]).strip()
        return self._cache_root / f"{safe_key}{suffix}"

    def write_cache_text(self, key: str, data: str, suffix: str = ".txt"):
        """Writes text data to the cache."""
        cache_file = self.get_cache_path(key, suffix)
        self._storage.write_file(cache_file, data)

    def read_cache_text(self, key: str, suffix: str = ".txt") -> Optional[str]:
        """Reads text data from the cache. Returns None if it doesn't exist."""
        cache_file = self.get_cache_path(key, suffix)
        if not cache_file.exists():
            return None
        try:
            return self._storage.read_file(cache_file)
        except Exception:
            return None

    def write_cache_bin(self, key: str, data: bytes, suffix: str = ".bin"):
        """Writes binary data to the cache."""
        cache_file = self.get_cache_path(key, suffix)
        self._storage.write_bin_file(cache_file, data)

    def read_cache_bin(self, key: str, suffix: str = ".bin") -> Optional[bytes]:
        """Reads binary data from the cache. Returns None if it doesn't exist."""
        cache_file = self.get_cache_path(key, suffix)
        if not cache_file.exists():
            return None
        try:
            return self._storage.read_bin_file(cache_file)
        except Exception:
            return None

    def delete_cache_item(self, key: str, suffix: str = ".bin") -> bool:
        """Deletes a specific cached item."""
        cache_file = self.get_cache_path(key, suffix)
        return self._storage.delete_file(cache_file)

    def clear_cache(self):
        """Clears all files in the cache directory."""
        if self._cache_root.exists():
            for item in self._cache_root.iterdir():
                if item.is_file():
                    self._storage.delete_file(item)

def load_urls() -> list:
    from core.paths import PathAuthority
    from core.storage import StorageLayer
    paths = PathAuthority()
    storage = StorageLayer()
    urls_file = paths.get_urls_file()
    urls = []
    if urls_file.exists():
        try:
            content = storage.read_file(urls_file)
            for line in content.splitlines():
                line = line.split("#")[0].strip()
                if line:
                    urls.append(line)
        except Exception:
            pass
    return urls

def save_url_to_file(url: str, title: str, silent: bool = False):
    """
    Delegates URL tracking to HistoryLayer instead of polluting the Batch file.
    """
    try:
        from core.paths import PathAuthority
        from core.storage import StorageLayer
        from core.history import HistoryLayer
        paths = PathAuthority()
        storage = StorageLayer()
        hist = HistoryLayer(paths, storage)
        hist.mark_url_tracked(url, title=title)
    except Exception:
        pass
