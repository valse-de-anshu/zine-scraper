"""
core/funnel.py
--------------
Funnel Layer: Captures raw inputs, resolves commands, and dynamically handshakes 
with site-specific scraper TUIs. Routes all operations through path config and storage layers.
"""

import os
import sys
import re
import time
import importlib
import select
from pathlib import Path
from typing import List, Tuple, Any, Optional
import logging

logger = logging.getLogger("core.funnel")

from core.ui import console, startup_clear, print_banner, clean_exit, Selector, get_theme_input_ansi, read_tty_key
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.console import Group
from rich.text import Text
from rich.markup import escape
from core.paths import PathAuthority
from core.storage import StorageLayer
from core.config import ConfigLayer
from core.history import HistoryLayer
from core.cache import CacheLayer

# Initialize Centralized Foundation Services
paths = PathAuthority()
storage = StorageLayer()
config = ConfigLayer(paths, storage)
history = HistoryLayer(paths, storage)
cache = CacheLayer(paths, storage)

# Centralized dynamic path settings via module-level __getattr__
URLS_FILE = paths.get_urls_file()

from core.domain_manager import DomainManager
domain_manager = DomainManager(Path(__file__).parent.parent / "scrapers")


def __getattr__(name: str) -> Any:
    if name == "BASE_SAVE_PATH":
        return Path(config.get("download_base") or paths.get_downloads_root())
    if name == "VIDEO_SAVE_ROOT":
        return Path(config.get("download_base") or paths.get_downloads_root()) / "video"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

from core.paths import sanitize_user_path

def load_urls(file_path: Optional[Path] = None) -> List[str]:
    target_file = Path(file_path) if file_path else URLS_FILE
    urls = []
    if not target_file.exists():
        try:
            storage.write_file(target_file, "# Add URLs here to download sequentially in vacuum mode.\n# Example: https://site.com/series-url --5\n")
        except Exception:
            pass
    if target_file.exists():
        try:
            content = storage.read_file(target_file)
            for line in content.splitlines():
                line = line.split("#")[0].strip()
                if line and not line.startswith("="):
                    urls.append(line)
        except Exception:
            pass
    return urls


from core.site_map import get_site_folder

def get_scraper_instance(url: str):
    try:
        site_folder = get_site_folder(url)
        if not site_folder: return None

        module = importlib.import_module(f"scrapers.{site_folder}.scraper")
        base_classes = ["BaseScraper", "AssetBaseScraper", "VideoBaseScraper", "MusicBaseScraper"]
        scraper_class = next((getattr(module, n) for n in dir(module) 
                            if n.endswith("Scraper") and n not in base_classes), None)
        return scraper_class(url) if scraper_class else None
    except Exception as e:
        console.print(f"[error]Failed to load scraper: {escape(str(e))}[/error]")
    return None

from core.settings_tui import launch_settings_tui
from wizard.setup import run_first_launch_setup

def clear_lines(num_lines: int):
    for _ in range(num_lines):
        sys.stdout.write("\033[1A\033[2K")
    sys.stdout.flush()

def handle_vacuum_queue(
    hist_layer,
    store_layer,
    custom_file: Optional[Path] = None,
    default_only_metadata: bool = False,
    default_flags: Optional[List[str]] = None,
    default_chapter_limit: Optional[int] = None,
    default_quick_grab: bool = False,
    default_all: bool = False
):
    """Process a URL queue file headlessly — the successor to batch mode.
    Each URL is routed individually using its own vacuum/quick-grab destination.
    Completed URLs are removed from the queue file atomically for safe resume (unless running in --meta mode)."""
    target_file = Path(custom_file) if custom_file else URLS_FILE
    urls = load_urls(target_file)
    if not urls:
        file_label = target_file.name
        console.print(f"[warning]No URLs found in {file_label}![/warning]")
        time.sleep(1.5)
        return

    startup_clear()
    print_banner()
    mode_label = "Metadata Extractor Queue (--meta)" if default_only_metadata else "Vacuum Queue"
    console.print(f"[menu]Menu:[/menu] [site]{mode_label}[/site]")
    if custom_file:
        console.print(f"[menu]Source File:[/menu] [sexy_pink]{target_file.resolve()}[/sexy_pink]")
    console.print(f"[info]Queue: {len(urls)} URLs loaded.[/info]")
    console.print()

    # Process each URL sequentially — no global path override, each scraper picks its own vacuum destination
    for raw_url in list(urls):
        raw_url_clean = raw_url.strip()
        if not raw_url_clean:
            continue

        url = raw_url_clean
        flags = list(default_flags or [])
        batch_quick_grab = default_quick_grab
        chapter_limit = default_chapter_limit
        batch_all = default_all
        only_metadata = default_only_metadata

        # Parse inline flags: --0 (Quick grab), --<N> (chapter limit), --A/--a (vacuum all), --meta/--metadata
        if re.search(r"--(?:meta|metadata)\b", url, re.IGNORECASE):
            only_metadata = True
            if "--meta" not in flags:
                flags.append("--meta")
        url = re.sub(r"\s*--(?:meta|metadata)\b", "", url, flags=re.IGNORECASE).strip()

        flag_matches = re.findall(r"--(\d+|[aA])\b", url)
        for flag_str in flag_matches:
            if flag_str.lower() == 'a':
                batch_all = True
                if "--a" not in flags:
                    flags.append("--a")
            else:
                val = int(flag_str)
                if val == 0:
                    batch_quick_grab = True
                    if "--0" not in flags:
                        flags.append("--0")
                else:
                    chapter_limit = val
                    if f"--{val}" not in flags:
                        flags.append(f"--{val}")
        url = re.sub(r"\s*--(\d+|[aA])\b", "", url).strip()

        if batch_all:
            batch_quick_grab = False
            chapter_limit = None

        canonical_url = HistoryLayer.normalize_url(url)

        # Route without a global batch_path — let each scraper decide its own vacuum/quick-grab folder
        success = route_url(
            url,
            hist_layer,
            store_layer,
            batch_path=None,
            is_batch=True,
            batch_quick_grab=batch_quick_grab,
            batch_all=batch_all,
            flags=flags,
            chapter_limit=chapter_limit,
            only_metadata=only_metadata
        )

        if success:
            if not only_metadata:
                # Atomically remove completed URL from the queue file so a Revolt/crash can safely resume
                try:
                    current_urls = load_urls(target_file)
                    remaining = [u for u in current_urls if u.strip() != raw_url_clean]
                    content = "\n".join(remaining) + ("\n" if remaining else "")
                    store_layer.write_file(target_file, content)
                except Exception as e:
                    logging.error(f"Failed to update {target_file.name}: {e}")
            console.print(f"[success]✔ Done: {raw_url_clean}[/success]\n")
        else:
            console.print(f"[error]✘ Failed: {raw_url_clean}[/error]\n")

        import core.ui
        if core.ui._REVOLT_ACTIVE and core.ui._REVOLT_LIMIT <= 0 and getattr(core.ui, "_REVOLT_CURRENT_DONE", False):
            core.ui.trigger_revolt_exit()

    if sys.stdin.isatty():
        from core.ui import wait_for_return
        wait_for_return("Press Enter to return...")


# Backward-compat alias so any external callers still work
handle_batch = handle_vacuum_queue


def handle_only_metadata(url: str, hist_layer: HistoryLayer, store_layer: StorageLayer, scraper: Any, site_folder: str, batch_path: Optional[Path] = None, is_batch: bool = False) -> bool:
    from core.paths import get_container_root
    from core.metadata_engine import MetadataEngine, ZineMetadataPayload
    from rich.panel import Panel
    from rich.syntax import Syntax
    import json
    import requests

    console.print(f"[menu]Mode[/menu]         : [sexy_pink]Metadata Extractor (--meta)[/sexy_pink]")
    console.print(f"[menu]URL[/menu]          : [site]{escape(url)}[/site]")
    console.print(f"[menu]Site Engine[/menu]  : [info]{site_folder}[/info]")
    console.print("")

    info_dict = {}
    meta_dict = {}
    extracted_title = "Unknown"
    cover_url = getattr(scraper, "cover_url", None) or getattr(scraper, "cover_image", None)

    with console.status("[info]Extracting metadata from source...[/info]", spinner="dots"):
        try:
            if hasattr(scraper, "get_metadata_and_videos"):
                meta_dict, videos, info_dict = scraper.get_metadata_and_videos()
                extracted_title = getattr(scraper, "title", None) or meta_dict.get("Channel/Series") or meta_dict.get("title") or (info_dict.get("title") if isinstance(info_dict, dict) else None) or "Unknown"
                if not cover_url:
                    cover_url = meta_dict.get("Thumbnail") or (info_dict.get("thumbnail") if isinstance(info_dict, dict) else None)
            elif hasattr(scraper, "get_metadata_and_assets"):
                meta_dict, assets = scraper.get_metadata_and_assets()
                extracted_title = meta_dict.get("Title") or getattr(scraper, "title", "Unknown")
                if not cover_url:
                    cover_url = meta_dict.get("Cover URL")
            elif hasattr(scraper, "get_title_and_chapters"):
                extracted_title, chapters = scraper.get_title_and_chapters()
            elif hasattr(scraper, "get_chapters"):
                chapters = scraper.get_chapters()
                extracted_title = getattr(scraper, "title", "Unknown")
            elif hasattr(scraper, "get_boards_and_pins"):
                boards, profile = scraper.get_boards_and_pins()
                extracted_title = profile.get("name") or getattr(scraper, "title", "Unknown")
            else:
                extracted_title = getattr(scraper, "title", "Unknown")
        except Exception as e:
            console.print(f"[error]Failed to extract metadata: {escape(str(e))}[/error]")
            if not is_batch and sys.stdin.isatty():
                from core.ui import wait_for_error
                wait_for_error("Press Enter to return...")
            return False

    if not extracted_title or extracted_title == "Unknown":
        extracted_title = getattr(scraper, "title", None) or getattr(scraper, "name", None) or "Unknown"

    clean_title = re.sub(r'[\/\\:\*\?\"\<\>\|]', '_', str(extracted_title).strip()).strip('. ')

    # Vacuum container root
    scraper._force_vacuum = True
    default_root = get_container_root(url, scraper, is_batch=True, batch_path=batch_path)
    target_folder = default_root / clean_title
    target_folder.mkdir(parents=True, exist_ok=True)

    # Save metadata using scraper engine if available or MetadataEngine
    saved = False
    if hasattr(scraper, "engine") and hasattr(scraper.engine, "save_metadata"):
        try:
            import inspect
            sig = inspect.signature(scraper.engine.save_metadata)
            params = sig.parameters
            call_kwargs = {}
            if "info" in params:
                call_kwargs["info"] = info_dict or meta_dict
            if "source" in params:
                call_kwargs["source"] = meta_dict.get("Source", site_folder or "Unknown")
            if "model_name" in params:
                call_kwargs["model_name"] = clean_title
            if "custom_metadata" in params:
                call_kwargs["custom_metadata"] = meta_dict
            if "skip_cover" in params:
                call_kwargs["skip_cover"] = False
            if "videos" in params:
                call_kwargs["videos"] = videos if "videos" in locals() and videos else None
            if "avatar_url" in params:
                call_kwargs["avatar_url"] = cover_url
            scraper.engine.save_metadata(target_folder, **call_kwargs)
            saved = True
        except Exception as e:
            logger.debug(f"Scraper engine save_metadata fallback: {e}")

    if not saved:
        title_val = extracted_title
        alt_title_val = getattr(scraper, "alt_title", "") or meta_dict.get("alt_title", "") or meta_dict.get("Alternative Title", "")
        author_val = getattr(scraper, "author", "") or meta_dict.get("Author", "") or meta_dict.get("Creator", "") or meta_dict.get("Uploader", "") or meta_dict.get("uploader", "")
        artist_val = getattr(scraper, "artist", "") or meta_dict.get("Artist", "")
        studio_val = getattr(scraper, "studio", "") or meta_dict.get("Studio", "")
        desc_val = getattr(scraper, "description", "") or meta_dict.get("Description", "") or meta_dict.get("Summary", "") or (info_dict.get("description") if isinstance(info_dict, dict) else "")
        status_val = getattr(scraper, "status", "") or meta_dict.get("Status", "")
        rating_val = str(getattr(scraper, "rating", "") or meta_dict.get("Rating", "") or "")
        year_val = str(getattr(scraper, "year", "") or meta_dict.get("Year", "") or meta_dict.get("Release Date", "") or meta_dict.get("Date", "") or meta_dict.get("date", "") or "")

        tags_raw = getattr(scraper, "tags", []) or getattr(scraper, "genres", []) or meta_dict.get("Tags") or meta_dict.get("genres") or meta_dict.get("Subject") or meta_dict.get("Subjects") or []
        tags_list = []
        if isinstance(tags_raw, str):
            for sub in tags_raw.replace(";", ",").split(","):
                if sub.strip():
                    tags_list.append(sub.strip())
        elif isinstance(tags_raw, list):
            for item in tags_raw:
                if isinstance(item, str):
                    for sub in item.replace(";", ",").split(","):
                        if sub.strip() and sub.strip() not in tags_list:
                            tags_list.append(sub.strip())

        media_type = "Manga"
        if "NOVEL" in site_folder.upper():
            media_type = "Novel"
        elif "MANHWA" in site_folder.upper():
            media_type = "Manhwa"
        elif "MANHUA" in site_folder.upper():
            media_type = "Manhua"
        elif "KNOWLEDGE" in site_folder.upper() or "STUDY" in site_folder.upper():
            media_type = "Book"
        elif "MUSIC" in site_folder.upper():
            media_type = "Song"
        elif "SOCIAL" in site_folder.upper() or "PORN" in site_folder.upper():
            media_type = "Channel"
        elif "ANIME" in site_folder.upper() or "SERIES" in site_folder.upper():
            media_type = "Series"

        canonical_url = getattr(scraper, "series_url", None) or getattr(scraper, "canonical_url", None) or getattr(scraper, "series_page", None) or getattr(scraper, "url", None) or url
        payload = ZineMetadataPayload(
            title=title_val,
            type=media_type,
            alt_title=alt_title_val,
            author=author_val,
            artist=artist_val,
            studio=studio_val,
            description=desc_val,
            status=status_val,
            rating=rating_val,
            tags=tags_list,
            year=year_val,
            url=canonical_url,
            views=str(getattr(scraper, "views", "") or meta_dict.get("Views", "") or meta_dict.get("views", "") or ""),
            likes=str(getattr(scraper, "likes", "") or meta_dict.get("Likes", "") or meta_dict.get("likes", "") or ""),
            hottest=getattr(scraper, "hottest", []) or meta_dict.get("hottest", []),
            most_rated=getattr(scraper, "most_rated", []) or meta_dict.get("most_rated", [])
        )
        MetadataEngine.save_metadata(target_folder, payload)

    # Save cover if available
    cover_file = target_folder / "cover.png"
    if not cover_file.exists() and cover_url:
        try:
            if hasattr(scraper, "save_cover"):
                scraper.save_cover(target_folder)
            elif cover_url:
                headers = getattr(scraper, "headers", {"User-Agent": "Mozilla/5.0"})
                res = requests.get(cover_url, headers=headers, timeout=10)
                if res.status_code == 200:
                    cover_ext = ".jpg" if "jpeg" in res.headers.get("Content-Type", "") or cover_url.endswith((".jpg", ".jpeg")) else ".png"
                    (target_folder / f"cover{cover_ext}").write_bytes(res.content)
        except Exception as e:
            logger.debug(f"Cover download non-fatal error: {e}")

    meta_file = target_folder / ".zine" / "metadata.json"
    if meta_file.exists():
        console.print(f"[success]✔ Metadata extracted and saved successfully![/success]")
        console.print(f"[menu]Location[/menu]     : [site]{escape(str(meta_file.resolve()))}[/site]\n")
        try:
            raw_json = meta_file.read_text(encoding="utf-8")
            syntax = Syntax(raw_json, "json", theme="monokai", line_numbers=True)
            console.print(Panel(syntax, title=f"[bold cyan]📄 .zine/metadata.json — {extracted_title}[/bold cyan]", border_style="cyan"))
        except Exception:
            pass
        if not is_batch and sys.stdin.isatty():
            from core.ui import wait_for_return
            wait_for_return("Press Enter to return...")
        return True
    else:
        console.print(f"[error]Failed to write metadata.json to {target_folder}[/error]")
        if not is_batch and sys.stdin.isatty():
            from core.ui import wait_for_error
            wait_for_error("Press Enter to return...")
        return False


def route_url(url: str, hist_layer: HistoryLayer, store_layer: StorageLayer, batch_path: Optional[Path] = None, is_batch: bool = False, batch_quick_grab: bool = False, batch_all: bool = False, flags: Optional[List[str]] = None, chapter_limit: Optional[int] = None, only_metadata: bool = False) -> bool:
    import core.ui
    if core.ui._REVOLT_ACTIVE and core.ui._REVOLT_LIMIT <= 0 and getattr(core.ui, "_REVOLT_CURRENT_DONE", False):
        core.ui.trigger_revolt_exit()
        return False

    if not is_batch:
        startup_clear()
        print_banner()
        try:
            from core.history_links import URLHistoryManager
            URLHistoryManager().append(url)
        except Exception:
            pass
        
    from core.ui import reset_error_wait
    reset_error_wait()

    try:
        scraper = get_scraper_instance(url)
    except Exception as e:
        logger.error(f"Error resolving scraper for URL: {url} -> {e}")
        scraper = None

    safe_url = escape(str(url))

    if not scraper:
        logging.error(f"Unsupported URL: {url}")
        from core.logger import record_error_log
        from core.ui import print_failure_box, wait_for_error
        record_error_log("Unsupported URL or command", context={"url": url})
        print_failure_box(safe_url, reason="Domain or URL format is not supported by any active scraper in Zine.")
        if not is_batch:
            if sys.stdin.isatty() and not getattr(scraper, "_is_cli", False):
                wait_for_error("Press Enter to return...")
        else:
            time.sleep(1.5)
        return False

    site_folder = get_site_folder(url)
    if not site_folder:
        console.print(f"[warning]Unsupported site folder for URL: {safe_url}[/warning]")
        if not is_batch:
            if sys.stdin.isatty():
                from core.ui import wait_for_error
                wait_for_error("Press Enter to return...")
        else:
            time.sleep(1.5)
        return False

    if only_metadata:
        return handle_only_metadata(url, hist_layer, store_layer, scraper, site_folder, batch_path=batch_path, is_batch=is_batch)

    try:
        tui_module = importlib.import_module(f"scrapers.{site_folder}.tui")
    except Exception as e:
        logging.error(f"Failed to import TUI module for {site_folder}: {e}")
        console.print(f"[error]Site handler error for {site_folder}: {e}[/error]")
        if not is_batch:
            if sys.stdin.isatty():
                from core.ui import wait_for_error
                wait_for_error("Press Enter to return...")
        else:
            time.sleep(1.5)
        return False

    from core.journal import DownloadJournal
    journal = DownloadJournal.get_active()
    init_mode = "Quick grab" if batch_quick_grab else "Vacuum"
    initial_title = getattr(scraper, "title", None) or getattr(scraper, "name", None) or "Unknown"
    journal.start_download(
        url=url,
        site=site_folder,
        title=initial_title,
        menu_mode=init_mode,
        destination=batch_path,
        flags=flags
    )

    try:
        logging.info(f"Passing control to TUI for site: {site_folder} with scraper: {scraper.__class__.__name__}")
        
        notification_fired = False
        last_error: Optional[str] = None
        already_up_to_date = False
        download_count = 0

        original_mark_downloaded = getattr(hist_layer, "mark_downloaded", None)
        def tracking_mark_downloaded(*args, **kwargs):
            nonlocal download_count
            download_count += 1
            if original_mark_downloaded:
                return original_mark_downloaded(*args, **kwargs)

        if original_mark_downloaded:
            hist_layer.mark_downloaded = tracking_mark_downloaded

        def clean_error_text(text: str) -> str:
            s = re.sub(r"\033\[[0-9;]*[mK]", "", text)
            s = re.sub(r"\[/?[\w#= -]+\]", "", s).strip()
            for line in s.splitlines():
                line = line.strip()
                if line:
                    if len(line) > 120:
                        line = line[:117] + "..."
                    return line
            return s[:120]

        def check_has_downloaded() -> bool:
            if download_count > 0:
                return True
            for attr in ("downloaded_count", "success_count"):
                val = getattr(scraper, attr, None)
                if isinstance(val, (int, float)) and val > 0:
                    return True
            for attr in ("verified_nums", "verified_ids"):
                val = getattr(scraper, attr, None)
                if isinstance(val, list) and len(val) > 0:
                    return True
            return False

        def fire_notification():
            nonlocal notification_fired
            if notification_fired:
                return
            t = getattr(scraper, "title", None) or url
            has_downloaded = check_has_downloaded()
            try:
                from butler.notify import send_os_notification
                from core.logger import record_error_log
                from core.ui import print_failure_box
                if has_downloaded:
                    send_os_notification("Zine Scraper", f"Finished downloading: {t}", is_success=True)
                    notification_fired = True
                elif already_up_to_date:
                    send_os_notification("Zine Scraper", f"Already up to date: {t}", is_success=True)
                    notification_fired = True
                else:
                    err_msg = last_error or "Download incomplete / No items saved"
                    send_os_notification("Zine Scraper Error", f"Download failed: {err_msg}", is_success=False)
                    print_failure_box(str(t), reason=str(err_msg))
                    record_error_log(err_msg, context={"url": url, "scraper": site_folder})
                    notification_fired = True
            except Exception as e:
                logging.error(f"Notification failed: {e}")
                notification_fired = True

        original_input = console.input
        original_print = console.print
        original_sleep = time.sleep
        import builtins
        original_builtin_print = builtins.print
        
        def patched_input(prompt="", **kwargs):
            import core.ui
            if core.ui._REVOLT_ACTIVE and core.ui._REVOLT_LIMIT <= 0 and getattr(core.ui, "_REVOLT_CURRENT_DONE", False):
                core.ui.trigger_revolt_exit(title=getattr(scraper, "title", None) or url)
                return ""
            prompt_str = str(prompt)
            prompt_lower = prompt_str.lower()
            if "download finished" in prompt_lower or "press enter to return" in prompt_lower or "return to menu" in prompt_lower or ("finished" in prompt_lower and "return" in prompt_lower):
                fire_notification()
                if is_batch:
                    return ""
            return original_input(prompt, **kwargs)

        def patched_print(*args, **kwargs):
            nonlocal last_error, already_up_to_date
            text = " ".join(str(a) for a in args)
            text_lower = text.lower()

            if "[error]" in text or "failed:" in text_lower or "error:" in text_lower or "could not" in text_lower or "no chapters saved" in text_lower or "download failed" in text_lower or "cannot download" in text_lower:
                last_error = clean_error_text(text)
            elif "already downloaded" in text_lower or "already up to date" in text_lower:
                already_up_to_date = True

            # Direct terminal pipe to Download Journal
            try:
                journal.consume_terminal_line(text)
            except Exception:
                pass

            return original_print(*args, **kwargs)

        def patched_builtin_print(*args, **kwargs):
            patched_print(*args, **kwargs)

        def patched_sleep(secs):
            import core.ui
            import threading
            is_main = threading.current_thread() is threading.main_thread()
            if is_main and core.ui._LIVE_INSTANCE is None and core.ui._REVOLT_ACTIVE and core.ui._REVOLT_LIMIT <= 0 and getattr(core.ui, "_REVOLT_CURRENT_DONE", False):
                core.ui.trigger_revolt_exit(title=getattr(scraper, "title", None) or url)
                return
            original_sleep(secs)
            if is_main and core.ui._LIVE_INSTANCE is None and core.ui._REVOLT_ACTIVE and core.ui._REVOLT_LIMIT <= 0 and getattr(core.ui, "_REVOLT_CURRENT_DONE", False):
                core.ui.trigger_revolt_exit(title=getattr(scraper, "title", None) or url)
                return

        console.input = patched_input
        console.print = patched_print
        builtins.print = patched_builtin_print
        time.sleep = patched_sleep
        try:
            scraper._batch_quick_grab = batch_quick_grab
            scraper._batch_all = batch_all
            scraper._force_vacuum = batch_all
            scraper._batch_flags = flags or []
            scraper._chapter_limit = chapter_limit
            hist_layer._active_batch_flags = flags or []
            tui_module.handle_tui(url, hist_layer, store_layer, scraper, batch_path=batch_path, is_batch=is_batch)
            import core.ui
            if core.ui._REVOLT_ACTIVE and core.ui._REVOLT_LIMIT <= 0 and getattr(core.ui, "_REVOLT_CURRENT_DONE", False):
                core.ui.trigger_revolt_exit(title=getattr(scraper, "title", None) or url)
            fire_notification() # In case it's batch mode and didn't call input
            try:
                final_title = getattr(scraper, "title", None) or getattr(scraper, "name", None)
                final_dest = getattr(scraper, "folder", None) or getattr(scraper, "target_dir", None) or getattr(scraper, "output_dir", None) or batch_path
                if final_title or final_dest:
                    journal.update_active(
                        url=url,
                        title=str(final_title).strip() if (final_title and str(final_title).strip() not in ("Unknown", "Videos", "Watch")) else None,
                        destination=str(final_dest) if final_dest else None
                    )

                has_downloaded = check_has_downloaded()
                final_status = "completed" if (has_downloaded or already_up_to_date) else "failed"
                err_msg = last_error if final_status == "failed" else None
                
                journal.finish_download(
                    url=url,
                    status=final_status,
                    error=err_msg
                )

                if final_title and str(final_title).strip() and str(final_title).strip() not in ("Unknown", "Videos", "Watch"):
                    target_url = getattr(scraper, "series_url", None) or getattr(scraper, "url", None) or url
                    if has_downloaded or already_up_to_date:
                        hist_layer.set_title(target_url, str(final_title).strip(), flags=flags)
            except Exception:
                pass
        finally:
            fire_notification()
            time.sleep = original_sleep
            hist_layer._active_batch_flags = []
            console.input = original_input
            console.print = original_print
            builtins.print = original_builtin_print
            if original_mark_downloaded:
                hist_layer.mark_downloaded = original_mark_downloaded
            
        has_downloaded = check_has_downloaded()
        if not (has_downloaded or already_up_to_date) and not is_batch and sys.stdin.isatty():
            from core.ui import wait_for_error
            wait_for_error("Press Enter to return...")

        logging.info(f"Finished TUI execution for: {url}")
        return True
    except core.ui.TruncateStopException as tse:
        logging.info(f"Scrape truncated early via Ctrl+T: {tse}")
        final_title = getattr(scraper, "title", None) or getattr(scraper, "name", None)
        final_dest = getattr(scraper, "folder", None) or getattr(scraper, "target_dir", None) or getattr(scraper, "output_dir", None) or batch_path
        try:
            journal.update_active(
                url=url,
                title=str(final_title).strip() if (final_title and str(final_title).strip() not in ("Unknown", "Videos", "Watch")) else None,
                destination=str(final_dest) if final_dest else None
            )
            journal.finish_download(url=url, status="completed")
            if final_title and str(final_title).strip() and str(final_title).strip() not in ("Unknown", "Videos", "Watch"):
                target_url = getattr(scraper, "series_url", None) or getattr(scraper, "url", None) or url
                hist_layer.set_title(target_url, str(final_title).strip(), flags=flags)
        except Exception:
            pass
        if not is_batch and sys.stdin.isatty():
            from core.ui import wait_for_return
            wait_for_return("Press Enter to return...")
        return True
    except Exception as e:
        logging.error(f"Failed to load/execute TUI for {site_folder}: {e}", exc_info=True)
        from core.logger import record_error_log
        from core.ui import print_failure_box, wait_for_error
        record_error_log(e, context={"url": url, "site_folder": site_folder, "batch_path": str(batch_path) if batch_path else None})
        try:
            journal.finish_download(url=url, status="failed", error=str(e))
        except Exception:
            pass
        print_failure_box(getattr(scraper, "title", None) or url, reason=str(e))
        try:
            from butler.notify import send_os_notification
            send_os_notification("Zine Scraper Error", f"Scraping failed: {e}", is_success=False)
        except Exception:
            pass
            
        console.print(f"[error]Failed to load TUI for {escape(str(site_folder))}: {escape(str(e))}[/error]")
        if not is_batch:
            wait_for_error("Press Enter to return...")
        else:
            time.sleep(1.5)
        return False

def _get_tui_key() -> str:
    if os.name == "nt":
        try:
            import msvcrt
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()
                if ch2 == b"H": return "UP"
                if ch2 == b"P": return "DOWN"
                if ch2 == b"K": return "LEFT"
                if ch2 == b"M": return "RIGHT"
                if ch2 == b"G": return "HOME"
                if ch2 == b"O": return "END"
                return ""
            if ch in (b"\r", b"\n"): return "ENTER"
            if ch == b"\x1b":       return "ESC"
            if ch == b"\x09":       return "TAB"
            if ch in (b"\x7f", b"\x08"): return "BACKSPACE"
            if ch == b"\x03":       return "CTRL_C"
            try:
                c = ch.decode("utf-8", errors="ignore")
                if c.isprintable(): return c
            except Exception: pass
            return ""
        except Exception:
            return ""
    else:
        import tty, termios, select as _sel
        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            mode    = termios.tcgetattr(fd)
            mode[3] = mode[3] | termios.ISIG   # keep Ctrl-C alive
            mode[1] = mode[1] | termios.OPOST  # keep newline translation
            termios.tcsetattr(fd, termios.TCSADRAIN, mode)
            _sel.select([fd], [], [])
            raw = os.read(fd, 1)
            if not raw: return ""
            ch = raw.decode("utf-8", errors="ignore")
            if ch == "\x1b":
                r, _, _ = _sel.select([fd], [], [], 0.08)
                if r:
                    ch2 = os.read(fd, 1).decode("utf-8", errors="ignore")
                    if ch2 in ("[", "O"):
                        r2, _, _ = _sel.select([fd], [], [], 0.08)
                        if r2:
                            ch3 = os.read(fd, 1).decode("utf-8", errors="ignore")
                            if ch3 == "A": return "UP"
                            if ch3 == "B": return "DOWN"
                            if ch3 == "C": return "RIGHT"
                            if ch3 == "D": return "LEFT"
                            if ch3 == "H": return "HOME"
                            if ch3 == "F": return "END"
                return "ESC"
            if ch in ("\r", "\n"): return "ENTER"
            if ch == "\x03":       return "CTRL_C"
            if ch == "\x09":       return "TAB"
            if ch in ("\x7f", "\x08"): return "BACKSPACE"
            if ch.isprintable():   return ch
            return ""
        except Exception:
            return ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

def get_key_with_esc() -> str:
    if os.name == 'nt':
        try:
            import msvcrt
            ch = msvcrt.getch()
            if ch == b'\x1b':
                return 'ESC'
            if ch in (b'\x00', b'\xe0'):
                ch2 = msvcrt.getch()
                if ch2 == b'H':  # Up
                    return '[A'
                elif ch2 == b'P':  # Down
                    return '[B'
                elif ch2 == b'K':  # Left
                    return '[D'
                elif ch2 == b'M':  # Right
                    return '[C'
                return ""
            if ch in (b'\r', b'\n'):
                return '\r'
            if ch in (b'\x7f', b'\x08'):
                return '\x08'
            if ch == b'\x03':
                return '\x03'
            return ch.decode('utf-8', errors='ignore')
        except Exception:
            return ""
    else:
        try:
            import tty
            import termios
            import select as select_mod
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                # Re-enable ISIG so Ctrl+C immediately generates keyboard interrupt signals
                mode = termios.tcgetattr(fd)
                mode[3] = mode[3] | termios.ISIG
                mode[1] = mode[1] | termios.OPOST
                termios.tcsetattr(fd, termios.TCSANOW, mode)
                r, _, _ = select_mod.select([fd], [], [])
                if not r:
                    return ""
                ch_bytes = os.read(fd, 1)
                ch = ch_bytes.decode('utf-8', errors='ignore')
                if ch == '\x1b':
                    seq = ""
                    r, _, _ = select_mod.select([fd], [], [], 0.001)
                    if r:
                        ch2 = os.read(fd, 1).decode('utf-8', errors='ignore')
                        seq += ch2
                        if ch2 in ('[', 'O'):
                            while True:
                                r2, _, _ = select_mod.select([fd], [], [], 0)
                                if r2:
                                    ch_next = os.read(fd, 1).decode('utf-8', errors='ignore')
                                    seq += ch_next
                                    if ch_next.isalpha() or ch_next == '~':
                                        break
                                else:
                                    break
                    if not seq:
                        return 'ESC'
                    return seq
                else:
                    paste_str = ch
                    while True:
                        r, _, _ = select_mod.select([fd], [], [], 0)
                        if r:
                            extra = os.read(fd, 1).decode('utf-8', errors='ignore')
                            paste_str += extra
                        else:
                            break
                    return paste_str
            finally:
                termios.tcsetattr(fd, termios.TCSANOW, old_settings)
        except Exception:
            return ""

class MainPrompt:
    def __init__(self, paths, config):
        self.paths = paths
        self.config = config
        self.input_text = ""
        self.suggestion = ""
        self.cursor_pos = 0  # index into input_text
        from core.history_links import URLHistoryManager
        self.history_manager = URLHistoryManager()

    def get_input(self) -> str:
        global _LIVE_INSTANCE
        if 'unittest' in sys.modules or not sys.stdin.isatty():
            return self.fallback_input()
        console.show_cursor(False)
        import core.ui
        old_menu_active = core.ui._MENU_ACTIVE
        core.ui._MENU_ACTIVE = True
        self.history_manager.reload()
        try:
            self.input_text = ""
            self.cursor_pos = 0
            self.suggestion = ""
            with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                core.ui._LIVE_INSTANCE = live
                while True:
                    live.update(self._render(), refresh=True)
                    key = get_key_with_esc()
                    if not key:
                        return self.fallback_input()
                    
                    if key in ('[A', 'OA'): # Up Arrow
                        self.input_text = self.history_manager.get_up(self.input_text)
                        self.cursor_pos = len(self.input_text)
                        self._update_suggestion()
                    elif key in ('[B', 'OB'): # Down Arrow
                        self.input_text = self.history_manager.get_down(self.input_text)
                        self.cursor_pos = len(self.input_text)
                        self._update_suggestion()
                    elif key in ('[D', 'OD'): # Left Arrow
                        if self.cursor_pos > 0:
                            self.cursor_pos -= 1
                    elif key in ('[C', 'OC'): # Right Arrow
                        if self.cursor_pos < len(self.input_text):
                            self.cursor_pos += 1
                    elif key in ('[H', '[1~', 'OH'): # Home
                        self.cursor_pos = 0
                    elif key in ('[F', '[4~', 'OF'): # End
                        self.cursor_pos = len(self.input_text)
                    elif len(key) > 1 and (key.startswith('[') or key.startswith('O')):
                        continue
                    elif key in ('\r', '\n'):
                        if self.suggestion and self.input_text != self.suggestion:
                            self.input_text = self.suggestion
                            self.cursor_pos = len(self.input_text)
                            self.suggestion = ""
                            continue
                        ret = self.input_text.strip()
                        self.history_manager.append(ret)
                        self.history_manager.index = len(self.history_manager.history)
                        return ret
                    elif key in ('\x7f', '\x08'): # Backspace
                        if self.cursor_pos > 0:
                            self.input_text = self.input_text[:self.cursor_pos - 1] + self.input_text[self.cursor_pos:]
                            self.cursor_pos -= 1
                        self._update_suggestion()
                        self.history_manager.index = len(self.history_manager.history)
                    elif key in ('ESC', '\x1b'):
                        self.input_text = ""
                        self.cursor_pos = 0
                        self.suggestion = ""
                        self.history_manager.index = len(self.history_manager.history)
                    elif key == '\x03': # Ctrl+C
                        clean_exit(forceful=True)
                    elif len(key) >= 1:
                        # Handle pastes that might contain newlines by stripping them
                        clean_key = "".join(c for c in key if c.isprintable())
                        if clean_key:
                            self.input_text = self.input_text[:self.cursor_pos] + clean_key + self.input_text[self.cursor_pos:]
                            self.cursor_pos += len(clean_key)
                            self._update_suggestion()
                            self.history_manager.index = len(self.history_manager.history)
                        
                        # If the paste had a newline, auto-submit
                        if '\n' in key or '\r' in key:
                            ret = self.input_text.strip()
                            if ret:
                                self.history_manager.append(ret)
                                return ret
        except Exception:
            return self.fallback_input()
        finally:
            core.ui._LIVE_INSTANCE = None
            console.show_cursor(True)
            core.ui._MENU_ACTIVE = old_menu_active

    def fallback_input(self) -> str:
        console.print("[menu]Paste URL:[/menu]")
        from core.ui import theme_input
        return theme_input("[menu]❯ [/menu]")

    def _update_suggestion(self):
        if not self.input_text:
            self.suggestion = ""
            return
        
        val = self.input_text.lower()
        # If input is a URL or a file path, immediately suppress any command suggestions
        if val.startswith("http") or val.startswith("www") or "/" in val or "\\" in val or "." in val:
            self.suggestion = ""
            return
            
        commands = ["bake", "clean", "doctor", "exit", "help", "lyrs", "sc-lyrics", "settings", "site", "slice", "subs", "tts", "vacuum", "version"]
        for cmd in commands:
            if cmd.startswith(val) and len(val) < len(cmd):
                self.suggestion = cmd
                return
        self.suggestion = ""

    def _render(self) -> Table:
        show_tips = self.config.get("show_tips", True, force_reload=True)
        
        table = Table.grid(padding=(0, 0))
        table.add_column("main", width=88)
        
        group_content = []
        
        prompt_text = Text(no_wrap=True)
        prompt_text.append("Paste URL:\n", style="menu")
        prompt_text.append("❯ ", style="menu")
        
        # Split text at cursor position and render the block cursor
        before_cursor = self.input_text[:self.cursor_pos]
        after_cursor  = self.input_text[self.cursor_pos:]

        prompt_text.append(before_cursor, style="selected")

        at_end = self.cursor_pos >= len(self.input_text)
        if at_end:
            # End-of-text: always show solid block cursor
            prompt_text.append("█", style="selected")
        else:
            # Mid-text: highlight the char under the cursor with reverse video (always visible)
            prompt_text.append(after_cursor[0], style="bold reverse")
            prompt_text.append(after_cursor[1:], style="selected")
            
        # Suggestion remainder only shown when cursor is at end
        suggestion_remainder = ""
        if at_end and self.suggestion and self.suggestion.startswith(self.input_text):
            suggestion_remainder = self.suggestion[len(self.input_text):]
            prompt_text.append(suggestion_remainder, style="unselected")
            
        # We want the input block to always occupy a fixed number of lines to prevent UI jumping.
        W = 88
        display_len = len("❯ ") + len(self.input_text) + len(suggestion_remainder)
        occupied_lines = (display_len + W - 1) // W
        if occupied_lines < 1:
            occupied_lines = 1
            
        empty_lines = 2 - occupied_lines
        if empty_lines < 0:
            empty_lines = 0
            
        prompt_text.append("\n" * empty_lines)
        
        group_content.append(prompt_text)
        
        if show_tips:
            tip_text = Text()
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("bake", style="warning")
            tip_text.append(" to edit & embed audio metadata/cover art.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("vacuum", style="warning")
            tip_text.append(" to download all from vacuum.txt.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("clean", style="warning")
            tip_text.append(" to purge temp files & cache.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("doctor", style="warning")
            tip_text.append(" to run system diagnostics.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("exit", style="warning")
            tip_text.append(" to quit.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("help", style="warning")
            tip_text.append(" for guide docs.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("lyrs", style="warning")
            tip_text.append(" to search & download synced lyrics (.lrc).\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("sc-lyrics", style="warning")
            tip_text.append(" to batch auto-sync missing .lrc files.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("settings", style="warning")
            tip_text.append(" to configure.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("site", style="warning")
            tip_text.append(" to view supported site database.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("slice", style="warning")
            tip_text.append(" to slice webtoon/manhua vertical strips.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("subs", style="warning")
            tip_text.append(" to generate AI subtitles.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("tts", style="warning")
            tip_text.append(" to generate Audiobooks.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("version", style="warning")
            tip_text.append(" to show version & environment info.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Paste any supported URL to archive.\n", style="info")
            tip_text.append("To hide, go to settings > Quick Guide > Hide", style="unselected")
            
            tip_panel = Panel(
                tip_text,
                title="[info]Quick Guide[/info]",
                border_style="menu",
                expand=False,
                width=88
            )
            group_content.append(tip_panel)
            
        table.add_row(Group(*group_content))
        return table

def show_help_tui():
    """Renders help.md in the console and waits for ESC key to exit."""
    startup_clear()
    print_banner()
    
    help_path = Path(__file__).parent.parent / "docs" / "help.md"
    if not help_path.exists():
        console.print("[error]● Help documentation file not found![/error]")
        time.sleep(2)
        return
        
    try:
        from rich.markdown import Markdown
        with open(help_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        md_renderable = Markdown(md_content)
        
        help_panel = Panel(
            md_renderable,
            title="[bold menu]❖ Zine Help Center[/bold menu]",
            border_style="menu",
            expand=False,
            width=88
        )
        
        startup_clear()
        print_banner()
        console.print(help_panel)
        console.print("\n[success]Press ESC to return to Zine Scraper[/success]")
        
        while True:
            key = get_key_with_esc()
            if key == 'ESC' or key == '\x1b':
                break
            elif key == '\x03': # Ctrl+C
                clean_exit(forceful=True)
            time.sleep(0.05)
    except Exception as e:
        console.print(f"[error]Error rendering help documentation: {e}[/error]")
        time.sleep(2)

def show_site_tui():
    """Renders the comprehensive, split-panel supported sites database table."""
    try:
        from core.site_tui import SiteDatabaseTUI
        tui = SiteDatabaseTUI()
        tui.run()
    except Exception as e:
        console.print(f"[error]Failed to load Site Database TUI: {e}[/error]")
        import time
        time.sleep(2)

def main():
    if config.is_first_launch():
        config._defer_save = True
        config_file = paths.get_config_file()
        if config_file.exists():
            try:
                os.remove(config_file)
            except Exception:
                pass
        run_first_launch_setup(paths, storage, config)

    # ── Ensure library structure is intact on every launch ───────────────────
    try:
        from core.library import scaffold_library, clean_temp
        lib_root_str = config.get("download_base")
        if lib_root_str:
            from pathlib import Path as _Path
            lib_root = _Path(lib_root_str).resolve()
            paths.set_downloads_root(lib_root)
            scaffold_library(lib_root, storage)   # no-op if dirs already exist
            clean_temp(lib_root, storage)          # auto-clean temp on startup
    except Exception:
        pass  # never block launch due to library scaffold errors

    cli_args = sys.argv[1:]
    if cli_args:
        raw_arg = cli_args[0].strip()
        first_arg = raw_arg.lower()
        if first_arg in ["--help", "-h", "-?", "help", "?", "--h"]:
            from core.cli_help import print_cli_help
            print_cli_help()
            sys.exit(0)
        elif first_arg in ["--version", "-v", "-v", "version", "ver", "--ver", "--verson"]:
            from core.cli_help import print_cli_version
            print_cli_version()
            sys.exit(0)
        elif first_arg in ["--doctor", "-doctor", "doctor", "check"]:
            from core.cli_help import run_cli_doctor
            run_cli_doctor()
            sys.exit(0)
        elif first_arg in ["--sites", "-sites", "sites", "list"]:
            from core.cli_help import print_cli_sites
            print_cli_sites()
            sys.exit(0)
        elif first_arg in ["--clean", "-clean", "clean"]:
            from core.cli_help import run_cli_clean
            run_cli_clean()
            sys.exit(0)
        elif raw_arg.startswith("-") and not re.match(r"^--(\d+|[aA])\b", raw_arg) and not first_arg.startswith(("--batch", "--vacuum", "--meta", "--metadata")):
            from core.cli_help import handle_unknown_flag
            handle_unknown_flag(raw_arg)
            sys.exit(2)

    first_run = True
    while True:
        history.reload()
        startup_clear()
        print_banner()

        try:
            if first_run and cli_args:
                first_run = False
                url = " ".join(cli_args)
                console.print(f"[menu]CLI Input[/menu]      : [site]{escape(url)}[/site]")
                console.print("")
            else:
                prompt = MainPrompt(paths, config)
                url = prompt.get_input()
            
            if not url:
                continue
            
            logging.info(f"User Input: '{url}'")
            # Extract flags from url input
            flags = []
            batch_quick_grab = False
            chapter_limit = None
            batch_all = False
            only_metadata = bool(re.search(r"--(?:meta|metadata)\b", url, re.IGNORECASE))
            if only_metadata:
                flags.append("--meta")

            flag_matches = re.findall(r"--(\d+|[aA])\b", url)
            for flag_str in flag_matches:
                if flag_str.lower() == 'a':
                    batch_all = True
                    if "--a" not in flags:
                        flags.append("--a")
                else:
                    val = int(flag_str)
                    if val == 0:
                        batch_quick_grab = True
                        if "--0" not in flags:
                            flags.append("--0")
                    else:
                        chapter_limit = val
                        if f"--{val}" not in flags:
                            flags.append(f"--{val}")

            # Strip all flags to get pure command / path / url candidate
            clean_candidate = re.sub(r"(?i)\s*--(?:meta|metadata|vacuum|batch|all|\d+|[aA])\b", "", url).strip()
            clean_lower = clean_candidate.lower()

            # 1. Exit Commands
            if clean_lower in ["exit", "quit", "q", "/exit"]:
                logging.info("User requested exit.")
                clean_exit(forceful=False)

            # 2. Explicit Queue Commands
            elif clean_lower in ["vacuum", "/vacuum", "batch", "/batch"] or clean_lower.startswith(("vacuum ", "/vacuum ", "batch ", "/batch ")) or re.search(r"(?i)(?:^|\s)(?:--vacuum|--batch|-vacuum|-batch|/vacuum|/batch)\b", url):
                url_input = clean_candidate
                if any(clean_lower.startswith(pfx) for pfx in ("vacuum ", "/vacuum ", "batch ", "/batch ")):
                    cleaned_path = clean_candidate.split(" ", 1)[1].strip()
                else:
                    cleaned_path = re.sub(r"(?i)(?:^|\s)(?:--vacuum|--batch|-vacuum|-batch|/vacuum|/batch)\b", "", url_input).strip()

                if cleaned_path:
                    sanitized = sanitize_user_path(cleaned_path)
                    custom_file = Path(sanitized).expanduser().resolve()
                    if custom_file.exists() and custom_file.is_file():
                        logging.info(f"User launched vacuum queue with file: {custom_file}")
                        handle_vacuum_queue(history, storage, custom_file=custom_file, default_only_metadata=only_metadata, default_flags=flags, default_chapter_limit=chapter_limit, default_quick_grab=batch_quick_grab, default_all=batch_all)
                    else:
                        console.print(f"[error]● Queue file not found:[/error] [site]{escape(str(custom_file))}[/site]")
                        time.sleep(2)
                else:
                    handle_vacuum_queue(history, storage, default_only_metadata=only_metadata, default_flags=flags, default_chapter_limit=chapter_limit, default_quick_grab=batch_quick_grab, default_all=batch_all)

            # 3. Direct File Path Queue Detection (e.g. "path/to/file.txt" --meta)
            elif (lambda p: p.exists() and p.is_file())(Path(sanitize_user_path(clean_candidate)).expanduser().resolve()):
                custom_file = Path(sanitize_user_path(clean_candidate)).expanduser().resolve()
                logging.info(f"User launched file queue: {custom_file} (only_metadata={only_metadata})")
                handle_vacuum_queue(history, storage, custom_file=custom_file, default_only_metadata=only_metadata, default_flags=flags, default_chapter_limit=chapter_limit, default_quick_grab=batch_quick_grab, default_all=batch_all)
                if cli_args:
                    break

            # 4. Built-in Tools & Menus
            elif clean_lower in ["settings", "/settings"]:
                launch_settings_tui()
            elif clean_lower in ["help", "/help", "--help", "-h"]:
                show_help_tui()
            elif clean_lower in ["site", "/site", "sites"]:
                show_site_tui()
            elif clean_lower in ["doctor", "/doctor", "--doctor"]:
                from core.cli_help import run_cli_doctor
                startup_clear()
                run_cli_doctor()
                from core.ui import prompt_return
                prompt_return("Press Enter to return to main menu...")
            elif clean_lower in ["clean", "/clean", "--clean"]:
                from core.cli_help import run_cli_clean
                startup_clear()
                run_cli_clean()
                from core.ui import prompt_return
                prompt_return("Press Enter to return to main menu...")
            elif clean_lower in ["version", "--version", "-v"]:
                from core.cli_help import print_cli_version
                startup_clear()
                print_cli_version()
                from core.ui import prompt_return
                prompt_return("Press Enter to return to main menu...")
            elif clean_lower in ["slice", "/slice", "slicer"]:
                from core.image_slicer import run_image_slicer_tui
                run_image_slicer_tui()
            elif clean_lower in ["subs", "/subs", "subtitles"]:
                from core.subtitle_engine import run_subtitle_tui
                run_subtitle_tui()
            elif clean_lower in ["tts", "/tts", "audiobook", "audiobooks"]:
                startup_clear()
                print_banner()
                tts_opts = [
                    ("🌬️ Breeze TTS 2 (GGUF / Vulkan C++ — Voice Design & Cloning)", "breeze"),
                    ("🎙️ Qwen3 TTS (ComfyUI Workflow Server)", "qwen")
                ]
                from core.ui import BoxSelector
                selected_engine = BoxSelector(tts_opts, title="Audiobook TTS Engine", width=84).select()
                if selected_engine == "breeze":
                    breeze_path = str(paths.get_breeze_tts_dir())
                    if breeze_path not in sys.path:
                        sys.path.insert(0, breeze_path)
                    import breeze_engine
                    breeze_engine.run_breeze_tui()
                elif selected_engine == "qwen":
                    qwen_path = str(paths.get_qwen_tts_dir())
                    if qwen_path not in sys.path:
                        sys.path.insert(0, qwen_path)
                    import book_tts
                    book_tts.run_tts_tui()
            elif clean_lower in ["lyrs", "/lyrs", "lyrics", "/lyrics"]:
                from core.lyrics_engine import run_lyrics_tui
                run_lyrics_tui()
            elif clean_lower in ["bake", "/bake"]:
                from core.bake_engine import run_bake_tui
                run_bake_tui()
            elif clean_lower in ["sc-lyrics", "/sc-lyrics", "sc_lyrics", "sclyrs"]:
                from core.lyrics_engine import run_batch_lyrics_tui
                run_batch_lyrics_tui()

            # 5. Media URL Execution
            else:
                # Headless if launched via CLI args (no interactive TUI needed in that path)
                is_headless = bool(cli_args)

                route_url(
                    clean_candidate,
                    history,
                    storage,
                    batch_path=None,
                    is_batch=is_headless,
                    batch_quick_grab=batch_quick_grab,
                    batch_all=batch_all,
                    flags=flags,
                    chapter_limit=chapter_limit,
                    only_metadata=only_metadata
                )

                if cli_args:
                    break

        except KeyboardInterrupt:
            clean_exit(forceful=True)

if __name__ == "__main__":
    main()
