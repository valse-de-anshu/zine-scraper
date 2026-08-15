"""
scrapers/hentaihaven/tui.py
------------------------
HentaiHaven TUI — Hentai-category flow.

Route logic (entirely user-driven, NOT URL-driven):
  Single Episode         → Quick Grab → video only, flat folder, no metadata
  Whole Franchise (Flat) → Vacuum     → all episodes in one series folder
  Nested Subfolders      → Vacuum     → all episodes in nested season subfolders

The Vacuum / Quick Grab label is NEVER shown. Label is always "Hentai".
Save Location prompt is NEVER shown — path is derived automatically from user choice.
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
from scrapers.hentaihaven_co.scraper import HentaiHavenCoScraper
from .workflow import run_workflow

logger = logging.getLogger(__name__)


def handle_hentaihaven_tui(
    url: str,
    tracker: HistoryLayer,
    library_root: Path,
    storage_layer: StorageLayer,
    scraper: HentaiHavenCoScraper,
    is_batch_mode: bool = False,
    batch_path: Optional[Path] = None,
):
    """
    TUI flow for HentaiHaven.
    Stage 1 — Load metadata
    Stage 2 — Single / Franchise selector (always shown, drives everything)
    Stage 3 — Kick off workflow (path auto-resolved from choice)
    """
    startup_clear()
    print_banner()

    # ── Stage 1: Fetch metadata ──────────────────────────────────────────
    metadata, videos, info = None, None, None

    with active_status("[info]Loading HentaiHaven metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos()
        except RuntimeError as geo_err:
            console.print(f"\n[error]{geo_err}[/error]")
            time.sleep(3)
            return
        except Exception as e:
            console.print(f"[error]Failed to load metadata: {e}[/error]")
            time.sleep(2)
            return

    if not metadata or videos is None:
        console.print("[error]Could not retrieve HentaiHaven metadata.[/error]")
        time.sleep(2)
        return

    channel_name = metadata.get("Channel/Series", "Unknown")

    startup_clear()
    print_banner()
    console.print(f"[menu]{'Menu':<12}:[/menu] [site]Hentai[/site]")
    console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
    console.print(f"[menu]{'Series':<12}:[/menu] [title]{channel_name}[/title]")
    console.print(f"[menu]{'Episodes':<12}:[/menu] [info]{len(videos)}[/info]")
    console.print("")

    # ── Stage 2: Always ask Single vs Franchise ──────────────────────────
    is_vacuum = False
    scraper.franchise_structure = "flat"

    if is_batch_mode:
        # In batch mode: download all flat, no prompt
        scraper.is_playlist = True
        is_vacuum = True
    elif len(videos) == 1:
        # Only one episode exists — skip the prompt, just download it
        scraper.is_playlist = False
        is_vacuum = False
    else:

        if __import__("sys").stdin.isatty():
            choice = Selector([
                ("Single Episode", "single"),
                ("Whole Franchise (Flat Folder)", "flat"),
                ("Whole Franchise (Nested Subfolders)", "nested"),
            ], "Download", vertical=True).select()

            if choice == "single":
                norm_url = url.rstrip("/")
                filtered = [v for v in videos if v.get("url", "").rstrip("/") == norm_url]
                videos[:] = filtered if filtered else videos[:1]
                metadata["Total Videos"] = len(videos)
                scraper.is_playlist = False
                is_vacuum = False
            else:
                scraper.franchise_structure = choice
                scraper.is_playlist = True
                is_vacuum = True
        else:
            # Headless/piped: download all
            scraper.is_playlist = True
            is_vacuum = True

    # ── Stage 3: Resolve target path directly from user choice ─────────
    if batch_path is not None:
        target_root = Path(batch_path)
    else:
        from core.paths import PathAuthority
        import json
        pa = PathAuthority()
        lib = pa.get_downloads_root()
        cfg = pa.get_config_file()
        if cfg.exists():
            try:
                custom = json.load(open(cfg)).get("download_base")
                if custom:
                    lib = Path(custom)
            except Exception:
                pass
        if is_vacuum:
            target_root = lib / "Vacuum" / "Hentai" / "HentaiHavenCo"
        else:
            target_root = lib / "Quick grab"

    # ── Stage 4: Kick off workflow ────────────────────────────────────────
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
        is_batch_mode=is_batch_mode,
    )

    if not is_batch_mode:
        console.input("\n[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None

        pass
        try:
            input()
        except EOFError:
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
    from core.paths import PathAuthority
    library_root = PathAuthority().get_downloads_root()

    handle_hentaihaven_tui(
        url=url,
        tracker=tracker,
        library_root=library_root,
        storage_layer=storage_layer,
        scraper=scraper,
        is_batch_mode=is_batch,
        batch_path=batch_path,
    )
