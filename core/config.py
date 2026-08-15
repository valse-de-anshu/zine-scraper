"""
core/config.py
--------------
Config Layer: Loads, parses, and saves settings, theme options, and profile preferences.
Delegates file path resolution to PathAuthority and filesystem actions to StorageLayer.
"""

import json
from pathlib import Path
from typing import Dict, Any

from core.paths import PathAuthority
from core.storage import StorageLayer

DEFAULT_CONFIG = {
    "theme": "tokyo-night-storm",
    "download_base": "",  # If empty, defaults to PathAuthority downloads root (~/Downloads/Zine)
    "music_quick_grab_path": "", # Custom music quick grab path (falls back if unmounted/invalid)
    "chapter_delay": 1.0,
    "first_launch": True,
    "show_tips": True,
    "playlist_max_items": 100,
    "ai_subtitles_vram": "6GB (INT8)",
    "ai_target_lang": "English",
    "ai_subtitles_mode": "Both",
    "ai_subtitles_model": "~/Models/faster-whisper-large-v3-turbo",
    "tts_mode": "Preset Voice",
    "tts_custom_speaker": "Vivian",
    "tts_voice_instruct": "",
    "tts_clone_ref_audio": "",
    "tts_clone_ref_transcript": "",
    "tts_model_choice": "1.7B",
    "tts_temperature": 0.9,
    "tts_top_p": 0.8,
    "tts_precision": "bf16",
}
class ConfigLayer:
    def __init__(self, paths: PathAuthority, storage: StorageLayer):
        self._paths = paths
        self._storage = storage
        self._config_file = self._paths.get_config_file()
        self._defer_save = False
        self._settings = self._load_settings()
        # Apply theme on startup
        theme_name = self._settings.get("theme", "tokyo-night-storm")
        from core.ui import apply_theme
        apply_theme(theme_name)

    def _sanitize_download_base(self, settings: dict) -> dict:
        """
        Guard: if download_base points inside the app's own .config dir (or is
        otherwise unreachable), reset it to ~/Downloads/Zine.
        This prevents the scraper from downloading into the source-code folder.
        """
        import os
        raw = settings.get("download_base", "")
        downloads_default = str(Path.home() / "Downloads" / "Zine")

        if not raw:
            settings["download_base"] = downloads_default
            return settings

        try:
            candidate = Path(raw).expanduser().resolve()
            app_root  = self._paths.get_app_root().resolve()
            # Reject if it lives inside the app config directory
            try:
                candidate.relative_to(app_root)
                # If we get here it IS inside app root — reset it
                settings["download_base"] = downloads_default
                self.save_settings(settings)
                return settings
            except ValueError:
                pass  # Good — it's outside the app root

            # Also reject if parent doesn't exist at all (stale/moved)
            if not candidate.parent.exists():
                settings["download_base"] = downloads_default
                self.save_settings(settings)
        except Exception:
            settings["download_base"] = downloads_default

        return settings

    def _load_settings(self) -> Dict[str, Any]:
        """Loads configuration from disk, falls back to default settings."""
        if not self._config_file.exists():
            settings = DEFAULT_CONFIG.copy()
            settings["download_base"] = str(Path.home() / "Downloads" / "Zine")
            if not self._defer_save:
                self.save_settings(settings)
            return settings

        try:
            raw_data = self._storage.read_file(self._config_file)
            data = json.loads(raw_data)
            settings = DEFAULT_CONFIG.copy()
            settings.update(data)
            return self._sanitize_download_base(settings)
        except Exception:
            settings = DEFAULT_CONFIG.copy()
            settings["download_base"] = str(Path.home() / "Downloads" / "Zine")
            return settings

    def save_settings(self, settings: Dict[str, Any]):
        """Saves configuration back to disk."""
        self._settings = settings
        raw_data = json.dumps(settings, indent=4)
        self._storage.write_file(self._config_file, raw_data)

    def get(self, key: str, default: Any = None, force_reload: bool = False) -> Any:
        """Retrieves a config value from cached in-memory settings."""
        if force_reload and self._config_file.exists():
            self._settings = self._load_settings()
        return self._settings.get(key, default)

    def set(self, key: str, value: Any):
        """Sets a config value and persists changes immediately."""
        self._settings[key] = value
        if not self._defer_save:
            self.save_settings(self._settings)
        if key == "theme":
            from core.ui import apply_theme
            apply_theme(value)

    def is_first_launch(self) -> bool:
        return self.get("first_launch", True)

    def mark_launched(self):
        self._defer_save = False
        self.set("first_launch", False)

    def get_music_quick_grab_path(self) -> Path:
        """
        Returns the resolved Path for music Quick Grab downloads.
        If a custom music path is set in settings, attempts to validate and use it.
        If the custom path is inaccessible, unmounted, invalid, or cannot be created,
        safely falls back to standard Quick grab root.
        """
        import os
        custom_music = self.get("music_quick_grab_path")
        if custom_music:
            try:
                music_path = Path(custom_music).expanduser().resolve()
                music_path.mkdir(parents=True, exist_ok=True)
                if music_path.exists() and os.access(music_path, os.W_OK):
                    return music_path
            except Exception:
                pass  # Fallback on any unmounted drive, permission error, or invalid path
                
        # Standard fallback to Quick grab
        download_base = self.get("download_base")
        if download_base:
            base = Path(download_base).resolve()
        else:
            base = self._paths.get_downloads_root()
        return base / "Quick grab"
