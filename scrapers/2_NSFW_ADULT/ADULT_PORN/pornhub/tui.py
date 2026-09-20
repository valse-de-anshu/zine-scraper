"""
scrapers/pornhub/tui.py
------------------------
PornHub TUI — mirrors youtube/tui.py architecture.

Route logic:
  Model/channel URL  →  Vacuum  →  scrape ALL videos + metadata + cover.png
  Single video URL   →  Quick grab  →  video only, no subfolders, no metadata

Quality: defaults to 1080p (as per spec) but user can choose in TUI.
"""

import sys
import time
import logging
from pathlib import Path
from typing import Optional, Any

from core.ui import (
    console, startup_clear, print_banner, Selector, active_status,
)
from core.history import HistoryLayer
from core.storage import StorageLayer
from .scraper import PornHubScraper
from .location import get_save_path
from .workflow import run_workflow

logger = logging.getLogger(__name__)


def handle_pornhub_tui(
    url: str,
    tracker: HistoryLayer,
    library_root: Optional[Path],
    storage_layer: StorageLayer,
    scraper: PornHubScraper,
    is_batch_mode: bool = False,
    batch_path: Optional[Path] = None,
):
    """
    TUI flow for PornHub.
    - Interactive: Stage 1 (Metadata) -> Stage 2 (Quality) -> Stage 3 (Location) -> Stage 4 (Workflow)
    - Batch Mode: Zero interactive prompts, link logic decides vacuum/quick grab, honors flags (--0, limits)
    """
    startup_clear()
    print_banner()

    is_batch = is_batch_mode or not sys.stdin.isatty()
    link_type = scraper.get_link_type()
    is_vacuum = (link_type == "model")
    menu_label = "Batch" if is_batch else ("Vacuum" if is_vacuum else "Quick Grab")

    # ── Stage 1: Fetch metadata ──────────────────────────────────────────
    metadata, videos, info = None, None, None

    with active_status("[info]Loading PornHub metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos()
        except RuntimeError as geo_err:
            # Geo-block / VPN required
            console.print(f"\n[error]{geo_err}[/error]")
            time.sleep(2.5)
            return
        except Exception as e:
            console.print(f"[error]Failed to load metadata: {e}[/error]")
            time.sleep(2)
            return

    if not metadata or videos is None:
        console.print("[error]Could not retrieve PornHub metadata.[/error]")
        time.sleep(2)
        return

    channel_name = metadata.get("Channel/Series", "Unknown")

    # ── Batch Mode Bypass: Zero interactive prompts ──────────────────────
    if is_batch:
        if getattr(scraper, "_force_vacuum", False) or getattr(scraper, "_batch_all", False):
            is_vacuum = True
            scraper.is_playlist = True
        elif getattr(scraper, "_batch_quick_grab", False):
            if videos:
                videos = videos[:1]
                metadata["Total Videos"] = 1
            is_vacuum = False
            scraper.is_playlist = False
        else:
            scraper.is_playlist = is_vacuum

        if not getattr(scraper, "_force_vacuum", False) and not getattr(scraper, "_batch_all", False):
            chapter_limit = getattr(scraper, "_chapter_limit", None)
            if chapter_limit and isinstance(chapter_limit, int) and chapter_limit > 0:
                if videos and len(videos) > chapter_limit:
                    videos = videos[:chapter_limit]
                    metadata["Total Videos"] = len(videos)

        if batch_path is not None:
            target_root = Path(batch_path)
        else:
            from core.paths import get_container_root
            target_root = get_container_root(url, scraper, is_batch=True)

        run_workflow(
            url=url,
            tracker=tracker,
            target_root=target_root,
            metadata=metadata,
            videos=videos,
            info=info,
            scraper=scraper,
            quality="1080p",
            is_vacuum=is_vacuum,
            is_batch_mode=True,
        )
        return

    # ── Quality options ──────────────────────────────────────────────────
    quality_options = [
        ("1080p  (Full HD — recommended)", "1080p"),
        ("720p   (HD — smaller file size)", "720p"),
        ("480p   (Standard definition)",    "480p"),
        ("360p   (Low — fastest download)", "360p"),
        ("Back",                            "BACK"),
    ]

    def draw_header(quality: Optional[str] = None):
        startup_clear()
        print_banner()
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]{menu_label}[/site]")
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
        console.print(f"[menu]{'Model':<12}:[/menu] [title]{channel_name}[/title]")
        console.print(f"[menu]{'Videos':<12}:[/menu] [info]{metadata.get('Total Videos', len(videos))}[/info]")
        if quality:
            console.print(f"[menu]{'Quality':<12}:[/menu] [site]{quality}[/site]")

    # ── Interactive State Machine ─────────────────────────────────────────
    state   = 0
    quality = "1080p"

    while True:
        if state == 0:
            # Quality selection
            draw_header()
            quality = Selector(quality_options, "Quality", vertical=True, align_width=12).select()
            if quality == "BACK":
                return
            if quality == "toggle":
                # Toggle vacuum ↔ quick grab
                is_vacuum = not is_vacuum
                scraper.is_playlist = is_vacuum
                menu_label = "Vacuum" if is_vacuum else "Quick Grab"
                continue
            state = 1

        elif state == 1:
            # Save location
            draw_header(quality)

            if batch_path is not None:
                target_root = Path(batch_path)
            else:
                from core.paths import get_container_root
                default_container = get_container_root(url, scraper, is_batch=False)
                target_root = get_save_path(
                    url, scraper, is_batch=False, batch_path=batch_path,
                    default_root=default_container, store_layer=storage_layer
                )

            if not target_root:
                state = 0
                continue
            if target_root == "toggle":
                is_vacuum = not is_vacuum
                scraper.is_playlist = is_vacuum
                menu_label = "Vacuum" if is_vacuum else "Quick Grab"
                continue

            break  # proceed to download

    # ── Kick off workflow ────────────────────────────────────────────────
    run_workflow(
        url=url,
        tracker=tracker,
        target_root=target_root,
        metadata=metadata,
        videos=videos,
        info=info,
        scraper=scraper,
        quality=quality,
        is_vacuum=is_vacuum,
        is_batch_mode=False,
    )

    if sys.stdin.isatty():
        try:
            from core.ui import wait_for_return
            wait_for_return("Download finished. Press Enter to return...")
        except (EOFError, Exception):
            pass


def handle_tui(
    url: str,
    tracker: HistoryLayer,
    storage_layer: StorageLayer,
    scraper: Any,
    batch_path: Optional[Path] = None,
    is_batch: bool = False,
):
    """Unified handshake wrapper — called by core/funnel.py route_url()."""
    handle_pornhub_tui(
        url=url,
        tracker=tracker,
        library_root=None,
        storage_layer=storage_layer,
        scraper=scraper,
        is_batch_mode=is_batch,
        batch_path=batch_path,
    )
