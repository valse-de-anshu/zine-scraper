"""
core/paths.py
-------------
Path Authority: The single source of truth for all filesystem locations in the scraper suite.
Its only responsibility is to answer: "Where should this file or directory live?"
It contains no storage operations (read/write/mkdir) and no business logic.
"""

import os
from pathlib import Path
from typing import Optional, Any

def sanitize_user_path(raw_path: str) -> str:
    """
    Cleans up file paths provided by users via drag-and-drop or pasting.
    Strips quotes, file:// URIs, and intelligently fixes missing root slashes on Unix systems.
    """
    if not raw_path:
        return raw_path
        
    clean = raw_path.strip("'\" \t\n")
    if clean.startswith("file://"):
        clean = clean[7:]
        
    # Fix missing root slash for absolute paths if dropped by terminal
    if clean.startswith(("home/", "mnt/", "media/", "usr/", "opt/", "Users/", "var/", "etc/", "tmp/")):
        clean = "/" + clean
        
    return clean

class PathAuthority:
    def __init__(self, app_root: Optional[Path] = None):
        # Resolve base application directory in a cross-platform way
        if app_root:
            self._app_root = Path(app_root).resolve()
        else:
            if os.name == 'nt':
                appdata = os.environ.get('APPDATA')
                if appdata:
                    self._app_root = Path(appdata) / "zine scraper"
                else:
                    self._app_root = Path.home() / "AppData" / "Roaming" / "zine scraper"
            else:
                self._app_root = Path.home() / ".config" / "zine scraper"
        
        # Suite root inside repo
        if app_root:
            self._suite_root = self._app_root
        else:
            self._suite_root = Path(__file__).parent.parent.resolve()

        # Download library root (user-configurable, default below)
        self._downloads_root = Path.home() / "Downloads" / "Zine"

        # Internal dirs (live inside the app/suite root, not the library)
        self._poop_root  = self._suite_root / "💩"
        self._cache_root = self._poop_root
        self._temp_root  = self._poop_root
        
        # Files
        self._config_file  = self._suite_root / "core" / "settings.json"
        
        # Logs 
        self._logs_root = self._suite_root / "Logs"
        self._history_file = self._logs_root / "Download History.json"
        self._url_history_file = self._logs_root / "URL History.txt"

    # ── Core paths ──────────────────────────────────────────────────────────

    def get_app_root(self) -> Path:
        return self._app_root

    def get_downloads_root(self) -> Path:
        """The user-chosen library root (e.g. ~/Downloads/Zine)."""
        return self._downloads_root

    def set_downloads_root(self, path: Path) -> None:
        """Update the in-memory library root (call after user configures it)."""
        self._downloads_root = Path(path).resolve()

    def get_cache_root(self) -> Path:
        return self._cache_root

    def get_temp_root(self) -> Path:
        return self._temp_root

    def get_history_file(self) -> Path:
        return self._history_file

    def get_config_file(self) -> Path:
        return self._config_file

    def get_urls_file(self) -> Path:
        return self.get_batch_root() / "Batch URL.txt"
        
    def get_url_history_file(self) -> Path:
        return self._url_history_file

    def get_logs_root(self) -> Path:
        return self._logs_root

    # ── Library structure paths (all rooted at downloads_root) ──────────────

    def get_quick_grab_root(self) -> Path:
        return self._downloads_root / "Quick grab"

    def get_quick_grab_path(self, site: str, creator: Optional[str] = None) -> Path:
        """e.g. get_quick_grab_path('youtube', 'Linus Tech Tips')"""
        hentai_map = {"hanime": "Hanime", "hanime_red": "HanimeRed", "hentaihaven": "HentaiHaven", "hentaihaven_co": "HentaiHavenCo", "hentaicity": "HentaiCity", "hstream": "Hstream", "oppai_stream": "OppaiStream", "hentaimama": "Hentaimama", "ohentai": "Ohentai", "asmhentai": "AsmHentai"}
        
        if site.lower() in hentai_map:
            base = self.get_quick_grab_root() / "Hentai" / hentai_map[site.lower()]
        else:
            base = self.get_quick_grab_root() / site
            
        if creator:
            return base / creator
        return base

    def get_vacuum_root(self) -> Path:
        return self._downloads_root / "Vacuum"

    def get_vacuum_path(self, site: str, creator: Optional[str] = None) -> Path:
        """e.g. get_vacuum_path('mangak', 'Solo Leveling')"""
        hentai_map = {"hanime": "Hanime", "hanime_red": "HanimeRed", "hentaihaven": "HentaiHaven", "hentaihaven_co": "HentaiHavenCo", "hentaicity": "HentaiCity", "hstream": "Hstream", "oppai_stream": "OppaiStream", "hentaimama": "Hentaimama", "ohentai": "Ohentai", "asmhentai": "AsmHentai"}
        
        if site.lower() in hentai_map:
            base = self.get_vacuum_root() / "Hentai" / hentai_map[site.lower()]
        else:
            base = self.get_vacuum_root() / site
            
        if creator:
            return base / creator
        return base

    def get_batch_root(self) -> Path:
        return self._downloads_root / "Batch"

    def get_library_temp_root(self) -> Path:
        """Temp dir inside the library (auto-cleaned on startup)."""
        return self._poop_root

    def get_library_temp_path(self, sub: str) -> Path:
        """sub is ignored. Everything dumps into 💩"""
        return self._poop_root

    # ── Legacy convenience (kept for backward compatibility) ────────────────

    def get_video_root(self) -> Path:
        """Shorthand: vacuum/video directory."""
        return self.get_vacuum_path("youtube")

class ZineFolder(type(Path())):
    def __truediv__(self, other):
        import re
        other_str = str(other)
        if re.match(r"^ch\d+(\.\d+)?$", other_str):
            ch_part = other_str[2:]
            return Path(super().__truediv__(f"Chapter {ch_part}"))
        elif re.match(r"^_temp_ch?\d+(\.\d+)?$", other_str):
            digits = re.findall(r"\d+(?:\.\d+)?", other_str)[0]
            return Path(super().__truediv__(f"_temp_Chapter_{digits}"))
        return Path(super().__truediv__(other))

def get_category_for_scraper(site_folder: str, is_music: bool = False, is_video: bool = False, is_asset: bool = False, scraper: Any = None) -> str:
    """
    Resolve the download category for a given site/scraper.
    """
    if scraper is not None:
        s_url = str(getattr(scraper, "url", "")).lower()
        if "music.youtube.com" in s_url or getattr(scraper, "is_music", False):
            is_music = True
        stype = getattr(scraper, "scraper_type", None)
        if stype == "toon" or stype == "novel":
            return "toon"
        if stype == "music":
            return "music"
        if stype == "video":
            return "music" if is_music else "video"
        if stype == "image":
            if is_music: return "music"
            if is_video: return "video"
            return "image"
        if stype == "asset":
            if is_video: return "video"
            if is_music: return "music"
            return "asset"
        if stype == "book":
            return "book"

    # ── Priority 2: legacy site-name lookup ─────────
    if site_folder == "youtube":
        return "music" if is_music else "video"
    if site_folder in ["soundcloud", "idagio", "youtube.yt_music", "yt_music"]:
        return "music"
    if site_folder == "pornhub":
        return "video"
    if site_folder == "pinterest":
        return "image"
    if site_folder == "archive":
        if is_video: return "video"
        if is_music: return "music"
        return "asset"
    if site_folder == "gutenberg":
        return "book"

    _LEGACY_TOON_SITES = {
        "manhuaplus", "manhwaus", "asurascans", "omegascans",
        "kunmanga", "fanfox", "nhentai", "weebcentral", "mangak",
        "projectsuki", "hentai18", "hentai20"
    }
    if site_folder in _LEGACY_TOON_SITES:
        return "toon"

    if is_music: return "music"
    if is_video: return "video"
    if is_asset: return "asset"
    return "toon"

def get_container_root(url: str, scraper: Any, is_batch: bool, batch_path: Optional[Path] = None) -> Path:
    """
    Returns the container root directory for a given scraper/URL.
    e.g. <downloads_root>/Quick grab/youtube or <downloads_root>/Vacuum/youtube
    """
    from core.site_map import get_site_folder
    
    if batch_path is not None:
        return Path(batch_path)
        
    paths = PathAuthority()
    library_root = paths.get_downloads_root()
    
    # Read download_base from settings.json directly to avoid circular imports with ConfigLayer
    config_file = paths.get_config_file()
    if config_file.exists():
        try:
            import json
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                custom_base = data.get("download_base", "")
                if custom_base:
                    candidate = Path(custom_base).expanduser().resolve()
                    # Only use the stored path if its parent exists and is writable.
                    # This prevents crashing when a user removes or renames their
                    # library root and the stale path is still in settings.json.
                    if candidate.parent.exists() and os.access(candidate.parent, os.W_OK):
                        library_root = candidate
                    # else: silently fall back to ~/Downloads/Zine
        except Exception:
            pass
            
    is_vacuum = False
    if getattr(scraper, "is_playlist", False):
        is_vacuum = True
    elif getattr(scraper, "get_link_type", lambda: "")() in ["playlist", "channel", "board", "profile", "album", "artist", "model"]:
        is_vacuum = True
    else:
        site_folder = get_site_folder(url) or "generic"
        category = get_category_for_scraper(site_folder, scraper=scraper)
        if category == "toon":
            if hasattr(scraper, "is_chapter_link"):
                is_chapter_link = scraper.is_chapter_link()
            else:
                is_chapter_link = any(x in url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])
            if not is_chapter_link:
                is_vacuum = True
        else:
            is_vacuum = False
            
    container_name = "Batch" if is_batch else ("Vacuum" if is_vacuum else "Quick grab")
    container_root = library_root / container_name
    
    site_folder = get_site_folder(url) or "generic"
    
    hentai_map = {
        "hanime": "Hanime",
        "hanime_red": "HanimeRed",
        "hentaihaven": "HentaiHaven",
        "hentaihaven_co": "HentaiHavenCo",
        "hentaicity": "HentaiCity",
        "hstream": "Hstream",
        "oppai_stream": "OppaiStream",
        "hentaimama": "Hentaimama",
        "ohentai": "Ohentai",
        "asmhentai": "AsmHentai",
    }
    
    if not is_vacuum and not is_batch:
        category = get_category_for_scraper(site_folder, scraper=scraper)
        if category == "music":
            if config_file.exists():
                try:
                    import json
                    with open(config_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        custom_music = data.get("music_quick_grab_path")
                        if custom_music:
                            m_path = Path(custom_music).expanduser().resolve()
                            m_path.mkdir(parents=True, exist_ok=True)
                            if m_path.exists() and os.access(m_path, os.W_OK):
                                return m_path
                except Exception:
                    pass
            return container_root
        elif category != "toon" and not site_folder.startswith("light_novel."):
            return container_root

    if site_folder.lower() in hentai_map:
        return container_root / "Hentai" / hentai_map[site_folder.lower()]
        
    if site_folder.startswith("light_novel."):
        sub_folder = site_folder.split(".")[1]
        return container_root / "Light Novel" / sub_folder
        
    # If the site folder is nested like "oppai_stream.oppai_stream_toon", clean it up
    if "." in site_folder:
        parts = site_folder.split(".")
        # Default to the parent folder name but nicely capitalized, or if they map to something we know
        parent = parts[0]
        if parent.lower() in hentai_map:
            site_folder = hentai_map[parent.lower()]
        else:
            site_folder = parent.title()
            
    # Also clean up standard "oppai_stream_toon" just in case
    if site_folder == "oppai_stream_toon":
        site_folder = "OppaiStream"

    return container_root / site_folder

def resolve_folder_collision(target_parent: Path, title: str, platform_id: str) -> Path:
    import re as _re
    safe_title = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title).strip()
    safe_title = _re.sub(r'\s{2,}', ' ', safe_title)
    if not safe_title:
        safe_title = "Unknown"
        
    if not target_parent.exists():
        return target_parent / safe_title
        
    def normalize(text):
        text = _re.sub(r'[^a-zA-Z0-9\s]', ' ', text.lower())
        return [w for w in text.split() if w]
        
    new_words = normalize(safe_title)
    if not new_words:
        return target_parent / safe_title
        
    best_match = None
    best_match_len = 0
    
    try:
        for f in target_parent.iterdir():
            if f.is_dir():
                exist_words = normalize(f.name)
                if not exist_words: continue
                
                # Direction A: Existing folder is a prefix of the new Title (e.g. SAO is prefix of SAO II)
                if len(exist_words) <= len(new_words):
                    match = True
                    for i, w in enumerate(exist_words):
                        if new_words[i] != w:
                            match = False
                            break
                    if match and len(exist_words) >= 1:
                        if len(exist_words) > best_match_len:
                            # Avoid over-grouping 1-word generic titles
                            if len(exist_words) == 1 and len(new_words) > 1 and len(exist_words[0]) <= 3:
                                continue 
                            best_match = f
                            best_match_len = len(exist_words)
                            
                # Direction B: New Title is a prefix of an Existing folder (e.g. We scraped SAO II first, and are now scraping SAO)
                elif len(new_words) < len(exist_words):
                    match = True
                    for i, w in enumerate(new_words):
                        if exist_words[i] != w:
                            match = False
                            break
                    if match and len(new_words) >= 1:
                        if len(new_words) == 1 and len(exist_words) > 1 and len(new_words[0]) <= 3:
                            continue
                        
                        # The new title is the true franchise root! Restructure on the fly.
                        new_root = target_parent / safe_title
                        new_root.mkdir(parents=True, exist_ok=True)
                        import shutil
                        try:
                            # Move the existing spinoff inside the new root
                            shutil.move(str(f), str(new_root / f.name))
                        except Exception:
                            pass
    except Exception:
        pass

    if best_match:
        if best_match_len == len(new_words):
            return best_match
        return best_match / safe_title
        
    return target_parent / safe_title
