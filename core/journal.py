"""
core/journal.py
---------------
Download Journal & Structured Telemetry Subsystem.
Maintains high-fidelity, human-readable session journals and feeds rich metadata,
user selections, destination paths, and download progress into:
  1. Logs/Downlode 💩/Download History.json (master enriched download history)
  2. Logs/Downlode 💩/Batch History.json (master enriched batch history)
  3. Logs/Downlode 💩/latest_session.json (mirror of active/latest session)
  4. Logs/Downlode 💩/Sessions/session_YYYY-MM-DD_HH-MM-SS.json (archived sessions)
"""

import os
import sys
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from core.paths import PathAuthority

logger = logging.getLogger(__name__)


def _strip_ansi_and_rich(text: str) -> str:
    """Strips both ANSI terminal escape codes and rich markup tags."""
    ansi_regex = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    no_ansi = ansi_regex.sub('', str(text))
    rich_regex = re.compile(r'\[/?(?:[a-zA-Z0-9_#= -]+)\]')
    cleaned = rich_regex.sub('', no_ansi)
    return cleaned.strip()


def clean_site_and_category(site: Optional[str]) -> Tuple[str, str]:
    """Returns (friendly_site_name, category_name)."""
    if not site:
        return "Unknown", "Media"
    parts = site.replace("/", ".").split(".")
    raw_slug = parts[-1].lower()

    # Prettify category
    cat = "Media"
    if len(parts) >= 2:
        raw_cat = parts[-2]
        cat = raw_cat.replace("_", " ").title()
        cat = cat.replace("Sfw", "SFW").replace("Nsfw", "NSFW").replace("Tts", "TTS")

    site_map = {
        "weebcentral": ("WeebCentral", "Hybrid Comics"),
        "yt_music": ("YouTube Music", "Music"),
        "youtube_music": ("YouTube Music", "Music"),
        "youtube": ("YouTube", "Video"),
        "pornhub": ("PornHub", "Video"),
        "nhentai": ("NHentai", "Doujinshi"),
        "asmhentai": ("AsmHentai", "Doujinshi"),
        "hentai18": ("Hentai18", "Adult Webtoons"),
        "hentai20": ("Hentai20", "Adult Webtoons"),
        "manga18fx": ("Manga18fx", "Adult Webtoons"),
        "manhwaus": ("ManhwaUS", "Adult Webtoons"),
        "asurascans": ("AsuraScans", "Manhwa"),
        "omegascans": ("OmegaScans", "Manhwa"),
        "projectsuki": ("ProjectSuki", "Manhwa"),
        "manhuaplus": ("ManhuaPlus", "Manhwa"),
        "mangak": ("MangaK", "Hybrid Comics"),
        "kunmanga": ("KunManga", "Hybrid Comics"),
        "fanfox": ("FanFox", "Hybrid Comics"),
        "topmanhua": ("TopManhua", "Hybrid Comics"),
        "mangadex": ("MangaDex", "Manga"),
        "novelarchive": ("NovelArchive", "Novels"),
        "hanime": ("Hanime", "Adult Anime"),
        "hanime_red": ("HanimeRed", "Adult Anime"),
        "hentaihaven": ("HentaiHaven", "Adult Anime"),
        "hentaihaven_co": ("HentaiHavenCo", "Adult Anime"),
        "hentaicity": ("HentaiCity", "Adult Anime"),
        "hstream": ("Hstream", "Adult Anime"),
        "oppai_stream": ("OppaiStream", "Adult Anime"),
        "oppai_stream_toon": ("OppaiStreamToon", "Adult Webtoons"),
        "hentaimama": ("Hentaimama", "Adult Anime"),
        "ohentai": ("OHentai", "Adult Anime"),
        "breeze_tts": ("Breeze TTS", "AI Audiobook"),
        "qwen_tts": ("Qwen TTS", "AI Audiobook"),
        "spotify": ("Spotify", "Music"),
        "bandcamp": ("Bandcamp", "Music"),
        "soundcloud": ("SoundCloud", "Music")
    }

    if raw_slug in site_map:
        return site_map[raw_slug]

    friendly = raw_slug.replace("_", " ").title()
    return friendly, cat


class DownloadJournal:
    _instance: Optional["DownloadJournal"] = None

    def __init__(self, cli_args: Optional[List[str]] = None, session_type: Optional[str] = None):
        self._paths = PathAuthority()
        self._journal_dir = self._paths.get_download_logs_root()
        self._journal_dir.mkdir(parents=True, exist_ok=True)
        self._sessions_dir = self._paths.get_sessions_dir()
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        self._migrate_stray_sessions()

        self.session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_file = self._sessions_dir / f"session_{self.session_id}.json"
        self.latest_file = self._journal_dir / "latest_session.json"

        hist_file = self._paths.get_history_file()
        if not hist_file.exists():
            try:
                hist_file.write_text("{}", encoding="utf-8")
            except Exception:
                pass

        batch_file = self._paths.get_batch_history_file()
        if not batch_file.exists():
            try:
                batch_file.write_text("{}", encoding="utf-8")
            except Exception:
                pass

        raw_args = cli_args if cli_args is not None else sys.argv[1:]
        self.cli_args = list(raw_args)

        if session_type:
            self.session_type = session_type
        elif any(a.startswith("--batch") for a in self.cli_args):
            self.session_type = "Batch"
        elif any(a.startswith("-") or a.startswith("http") for a in self.cli_args):
            self.session_type = "CLI"
        else:
            self.session_type = "Interactive TUI"

        self.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.finish_time: Optional[str] = None

        self.downloads: List[Dict[str, Any]] = []
        self.current_download: Optional[Dict[str, Any]] = None

        DownloadJournal._instance = self
        self._save_session()

    def _migrate_stray_sessions(self):
        """Moves any loose session_*.json files in Logs/Downlode 💩 into Sessions/."""
        try:
            for item in self._journal_dir.glob("session_*.json"):
                if item.is_file():
                    target = self._sessions_dir / item.name
                    if not target.exists():
                        item.rename(target)
                    else:
                        item.unlink(missing_ok=True)
        except Exception:
            pass

    @classmethod
    def get_active(cls) -> "DownloadJournal":
        if cls._instance is None:
            cls._instance = DownloadJournal()
        return cls._instance

    @classmethod
    def init_session(cls, cli_args: Optional[List[str]] = None, session_type: Optional[str] = None) -> "DownloadJournal":
        return cls(cli_args=cli_args, session_type=session_type)

    def _save_session(self):
        """Atomically saves the session JSON and updates latest_session.json."""
        try:
            data = {
                "session_id": self.session_id,
                "start_time": self.start_time,
                "finish_time": self.finish_time,
                "session_type": self.session_type,
                "cli_args": self.cli_args,
                "total_downloads": len(self.downloads),
                "downloads": self.downloads
            }
            raw = json.dumps(data, indent=4, ensure_ascii=False)
            self.session_file.write_text(raw, encoding="utf-8")
            self.latest_file.write_text(raw, encoding="utf-8")
        except Exception as e:
            logger.debug(f"Failed to save session journal: {e}")

    def start_download(
        self,
        url: str,
        site: Optional[str] = None,
        title: Optional[str] = None,
        menu_mode: Optional[str] = None,
        destination: Optional[Any] = None,
        chosen_options: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        flags: Optional[List[str]] = None,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Initializes a new download journal entry for the current URL."""
        from core.history import HistoryLayer
        canonical_url = HistoryLayer.normalize_url(url)

        friendly_site, inferred_cat = clean_site_and_category(site)
        final_cat = category or inferred_cat

        # Check if already registered in this session
        existing = next((d for d in self.downloads if d.get("canonical_url") == canonical_url), None)
        if existing and existing.get("status") == "in_progress":
            self.current_download = existing
            return existing

        dest_str = str(destination) if destination else ""

        entry: Dict[str, Any] = {
            "url": url,
            "canonical_url": canonical_url,
            "site": friendly_site,
            "category": final_cat,
            "title": title or "Unknown",
            "menu_mode": menu_mode or ("Batch" if self.session_type == "Batch" else "Quick grab"),
            "execution_mode": "CLI" if (flags and self.session_type == "CLI") else self.session_type,
            "flags": list(flags) if flags else [],
            "destination": dest_str,
            "chosen_options": dict(chosen_options) if chosen_options else {},
            "metadata": dict(metadata) if metadata else {},
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "finish_time": None,
            "status": "in_progress",
            "items": [],
            "summary": {
                "total_items": 0,
                "downloaded": 0,
                "already_exists": 0,
                "failed": 0
            }
        }
        self.downloads.append(entry)
        self.current_download = entry
        self._save_session()
        return entry

    def update_active(self, url: Optional[str] = None, **kwargs):
        """Updates attributes of the active download entry."""
        target = None
        if url:
            from core.history import HistoryLayer
            canon = HistoryLayer.normalize_url(url)
            target = next((d for d in self.downloads if d.get("canonical_url") == canon), None)
        if target is None:
            target = self.current_download
        if target is None:
            return

        for k, v in kwargs.items():
            if v is None:
                continue
            if k == "metadata" and isinstance(v, dict):
                target.setdefault("metadata", {}).update(v)
            elif k == "chosen_options" and isinstance(v, dict):
                target.setdefault("chosen_options", {}).update(v)
            elif k == "flags" and isinstance(v, list):
                existing_f = target.setdefault("flags", [])
                for f in v:
                    if f not in existing_f:
                        existing_f.append(f)
            elif k == "site":
                friendly_site, inferred_cat = clean_site_and_category(v)
                target["site"] = friendly_site
                if not target.get("category") or target.get("category") == "Media":
                    target["category"] = inferred_cat
            else:
                target[k] = v

        self._save_session()

    def record_choice(self, prompt: str, label: str, value: Any):
        """Records an interactive user choice from Selector or MultiSelector."""
        if not self.current_download:
            return
        clean_p = _strip_ansi_and_rich(prompt).strip(": ")
        clean_l = _strip_ansi_and_rich(str(label)).strip()

        options = self.current_download.setdefault("chosen_options", {})
        options[clean_p] = clean_l

        p_lower = clean_p.lower()
        if "quality" in p_lower:
            options["quality"] = clean_l
        elif "format" in p_lower:
            options["format"] = clean_l
        elif "download" in p_lower or "mode" in p_lower or "menu" in p_lower:
            options["mode_selection"] = clean_l

        self._save_session()

    def record_item(
        self,
        url: str,
        item_id: str,
        title: Optional[str] = None,
        filename: Optional[str] = None,
        status: str = "downloaded",
        extra: Optional[Dict[str, Any]] = None
    ):
        """Records a downloaded or verified file/chapter/track."""
        from core.history import HistoryLayer
        canon = HistoryLayer.normalize_url(url)
        target = next((d for d in self.downloads if d.get("canonical_url") == canon), None)
        if target is None:
            target = self.current_download
        if target is None:
            return

        items = target.setdefault("items", [])
        id_str = str(item_id).strip()
        if not id_str:
            return

        existing_item = next((it for it in items if it.get("id") == id_str), None)
        if existing_item:
            existing_item["status"] = status
            if title: existing_item["title"] = title
            if filename: existing_item["filename"] = filename
            if extra: existing_item.update(extra)
        else:
            item_entry = {
                "id": id_str,
                "title": title or f"Item {id_str}",
                "filename": filename or "",
                "status": status,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if extra:
                item_entry.update(extra)
            items.append(item_entry)

        # Update summary counts
        summary = target.setdefault("summary", {"total_items": 0, "downloaded": 0, "already_exists": 0, "failed": 0})
        summary["downloaded"] = sum(1 for it in items if it.get("status") == "downloaded")
        summary["already_exists"] = sum(1 for it in items if it.get("status") in ("already_exists", "existing"))
        summary["failed"] = sum(1 for it in items if it.get("status") == "failed")
        summary["total_items"] = max(summary.get("total_items", 0), len(items))

        self._save_session()

    def finish_download(self, url: str, status: str = "completed", error: Optional[str] = None):
        """Finalizes a download entry and syncs with Download History / Batch History."""
        from core.history import HistoryLayer, BatchHistoryManager
        canon = HistoryLayer.normalize_url(url)
        target = next((d for d in self.downloads if d.get("canonical_url") == canon), None)
        if target is None:
            target = self.current_download
        if target is None:
            return

        target["finish_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target["status"] = status
        if error:
            target["error"] = error

        self._save_session()

        # Seamlessly update Download History.json with enriched details
        try:
            self._sync_to_download_history(target)
        except Exception as e:
            logger.debug(f"Failed to sync to Download History: {e}")

        # Seamlessly update Batch History.json if batch
        try:
            if target.get("menu_mode") == "Batch" or self.session_type == "Batch" or BatchHistoryManager._instance:
                self._sync_to_batch_history(target)
        except Exception as e:
            logger.debug(f"Failed to sync to Batch History: {e}")

    def _sync_to_download_history(self, target: Dict[str, Any]):
        """Persists enriched metadata and chosen options into Download History.json."""
        hist_file = self._paths.get_history_file()
        data = {}
        if hist_file.exists():
            try:
                data = json.loads(hist_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        url = target.get("canonical_url") or target.get("url")
        if not url:
            return

        entry = data.setdefault(url, {})
        entry["title"] = target.get("title") or entry.get("title") or "Unknown"
        entry["site"] = target.get("site") or entry.get("site") or "Unknown"
        entry["category"] = target.get("category") or entry.get("category") or "Media"
        entry["mode"] = target.get("menu_mode") or entry.get("mode") or "Vacuum"
        entry["date"] = target.get("finish_time") or target.get("start_time") or entry.get("date")

        if target.get("destination"):
            entry["destination"] = target.get("destination")
        if target.get("chosen_options"):
            entry["chosen_options"] = target.get("chosen_options")
        if target.get("metadata"):
            entry["metadata"] = target.get("metadata")
        if target.get("flags"):
            existing_flags = entry.setdefault("flags", [])
            for f in target.get("flags", []):
                if f not in existing_flags:
                    existing_flags.append(f)

        existing_info = set(str(x) for x in entry.get("info", []))
        for it in target.get("items", []):
            if it.get("status") in ("downloaded", "already_exists", "existing"):
                existing_info.add(str(it.get("id")))

        def sort_key(x):
            try:
                return (0, float(x))
            except (ValueError, TypeError):
                return (1, str(x))

        entry["info"] = sorted(list(existing_info), key=sort_key)
        entry["status"] = target.get("status", "completed")

        hist_file.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")

    def _sync_to_batch_history(self, target: Dict[str, Any]):
        """Persists enriched metadata and chosen options into Batch History.json."""
        batch_file = self._paths.get_batch_history_file()
        data = {}
        if batch_file.exists():
            try:
                data = json.loads(batch_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        url = target.get("canonical_url") or target.get("url")
        if not url:
            return

        entry = data.setdefault(url, {})
        entry["title"] = target.get("title") or entry.get("title") or "Unknown"
        entry["url"] = url
        entry["site"] = target.get("site") or entry.get("site") or "Unknown"
        entry["category"] = target.get("category") or entry.get("category") or "Media"
        entry["mode"] = target.get("menu_mode") or entry.get("mode") or "Batch"
        entry["status"] = target.get("status", "completed")
        entry["date"] = target.get("finish_time") or target.get("start_time") or entry.get("date")
        if target.get("start_time"):
            entry.setdefault("start_date", target.get("start_time"))
        if target.get("destination"):
            entry["destination"] = target.get("destination")
        if target.get("chosen_options"):
            entry["chosen_options"] = target.get("chosen_options")
        if target.get("metadata"):
            entry["metadata"] = target.get("metadata")
        if target.get("flags"):
            existing_flags = entry.setdefault("flags", [])
            for f in target.get("flags", []):
                if f not in existing_flags:
                    existing_flags.append(f)

        existing_info = set(str(x) for x in entry.get("info", []))
        for it in target.get("items", []):
            if it.get("status") in ("downloaded", "already_exists", "existing"):
                existing_info.add(str(it.get("id")))

        def sort_key(x):
            try:
                return (0, float(x))
            except (ValueError, TypeError):
                return (1, str(x))

        entry["info"] = sorted(list(existing_info), key=sort_key)
        batch_file.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")

    def consume_terminal_line(self, raw_line: str):
        """
        Direct pipe: Parses terminal lines printed to console to extract
        headers, metadata, locations, and download events in real-time.
        """
        line = _strip_ansi_and_rich(raw_line)
        if not line:
            return

        target = self.current_download
        if not target:
            return

        # Strip box-drawing tree prefixes: ├──, └──, │, ◆, ◇
        clean = re.sub(r'^[├└│─◆◇●•\s]+', '', line).strip()

        # 1. Key-value headers: e.g. "Menu : Quick Grab", "Location : /path/to/dir", "Artist : LOVELI LORI"
        m = re.match(r"^([A-Za-z0-9/ ]{2,25})\s*:\s*(.+)$", clean)
        if m:
            k = m.group(1).strip()
            v = m.group(2).strip()
            k_lower = k.lower()

            if k_lower == "menu":
                target["menu_mode"] = v
            elif k_lower in ("quality", "format", "type", "subtitle", "subtitles", "thumbnail", "download mode"):
                target.setdefault("chosen_options", {})[k] = v
            elif k_lower == "location":
                target["destination"] = v
                target.setdefault("metadata", {})["Location"] = v
            elif k_lower == "source":
                friendly_site, inferred_cat = clean_site_and_category(v)
                target["site"] = friendly_site
                target.setdefault("metadata", {})["Source"] = friendly_site
                if not target.get("category") or target.get("category") == "Media":
                    target["category"] = inferred_cat
            elif k_lower in ("channel", "artist", "author", "creator", "model"):
                target.setdefault("metadata", {})[k] = v
                if target.get("title") in ("Unknown", "Videos", "Watch", None):
                    target["title"] = v
            elif k_lower in ("album", "series", "playlist", "novel", "manga", "book", "video", "title"):
                target.setdefault("metadata", {})[k] = v
                if v and v != "Unknown":
                    target["title"] = v
            elif "total" in k_lower:
                target.setdefault("metadata", {})[k] = v
                m_num = re.search(r"\d+", v)
                if m_num:
                    target.setdefault("summary", {})["total_items"] = int(m_num.group(0))
            elif k_lower in ("existing", "cover"):
                target.setdefault("metadata", {})[k] = v

            self._save_session()
            return

        # 2. File exists detection: e.g. "File exists: hate u love u.flac"
        m_exist = re.search(r"(?:File exists|Already exists|Already downloaded):\s*(.+)", line, re.I)
        if m_exist:
            fn = m_exist.group(1).strip()
            stem = Path(fn).stem
            self.record_item(target["url"], stem, title=stem, filename=fn, status="already_exists")
            return

        # 3. Newly downloaded item: e.g. "● hate u love u.flac" or "● Chapter 140"
        m_dl = re.search(r"^[●✔✦]\s*([^\n]+)", line)
        if m_dl:
            content = m_dl.group(1).strip()
            c_lower = content.lower()
            ignore_keywords = (
                "subtitle", "lyrics", "download finished", "connection", "starting",
                "done with", "progress", "result", "warning", "info", "skipping",
                "fetching", "extracting", "found", "searching", "waiting", "bypassing",
                "done:", "failed:", "chapters saved"
            )
            if not any(x in c_lower for x in ignore_keywords):
                fn = content
                stem = Path(fn).stem
                m_ch = re.match(r"(?:Chapter|Ch\.?|Episode|Ep\.?|Track)?\s*(\d+(?:\.\d+)?)", fn, re.I)
                item_id = m_ch.group(1) if m_ch else stem
                self.record_item(target["url"], item_id, title=fn, filename=fn, status="downloaded")
                return

    def finish_session(self):
        """Finalizes the entire session log."""
        self.finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._save_session()
