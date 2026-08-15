import re
from pathlib import Path
from typing import Optional, Any

def sanitize_filename(name: str) -> str:
    """Sanitizes directory and file names for filesystem safety."""
    if not name:
        return ""
    clean = re.sub(r'[\/:*?"<>|]', "_", str(name)).strip()
    return clean or "music"

def get_save_path(
    url: str,
    scraper: Any,
    is_batch: bool = False,
    batch_path: Optional[Path] = None,
    default_root: Optional[Path] = None,
    location_manager: Optional[Any] = None
) -> Optional[Path]:
    """
    Resolves the target save path for YouTube Music audio files.
      - Quick Grab (single track): default_root (e.g. Quick grab/ or custom music_quick_grab_path)
      - Vacuum Album: default_root / {Artist} / {Album}
      - Vacuum Playlist: default_root / Playlists / {Playlist_Title}
    """
    if batch_path:
        return Path(batch_path)

    metadata = getattr(scraper, "metadata", {})
    artist = metadata.get("Artist") or "Unknown Artist"
    album = metadata.get("Album") or ""

    clean_artist = sanitize_filename(artist)
    clean_album = sanitize_filename(album) if album and album != "Single" else ""

    from core.paths import PathAuthority, get_container_root
    from core.config import ConfigLayer
    from core.storage import StorageLayer
    paths = PathAuthority()
    config = ConfigLayer(paths, StorageLayer())

    if default_root is None:
        default_root = get_container_root(url, scraper, is_batch)

    base = Path(default_root)
    link_type = getattr(scraper, "get_link_type", lambda: "")()

    if link_type == "single" or not getattr(scraper, "is_playlist", False):
        custom_music = config.get("music_quick_grab_path")
        if custom_music:
            target = Path(custom_music).expanduser().resolve()
        else:
            target = base
    elif link_type == "album":
        if clean_artist and clean_artist not in ["YouTube Music", "Various Artists"]:
            target = base / clean_artist / (clean_album or "Album")
        else:
            target = base / (clean_album or "Album")
    else:
        # Playlist / Artist
        if clean_artist and clean_artist != "YouTube Music":
            target = base / clean_artist / (clean_album or "Playlist")
        else:
            target = base / "Playlists" / (clean_album or "Playlist")

    if location_manager:
        location_manager.create_directory(target)

    return target
