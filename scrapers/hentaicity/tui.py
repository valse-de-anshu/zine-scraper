"""
scrapers/hentaicity/tui.py
--------------------------
HentaiCity TUI — handles both video and gallery content types.

Video URL  : https://www.hentaicity.com/video/<slug>.html
Gallery URL: https://www.hentaicity.com/gallery/<slug>.html

Route:
  Single episode / single gallery → Quick Grab (flat)
  Whole series / franchise        → Vacuum (creator subfolder)
"""

import time
import sys
import logging
from pathlib import Path
from typing import Optional, Any

from core.ui import console, startup_clear, print_banner, Selector, active_status
from core.history import HistoryLayer
from core.storage import StorageLayer
from .workflow import run_workflow

logger = logging.getLogger(__name__)


def handle_hentaicity_tui(
    url: str,
    tracker: HistoryLayer,
    library_root: Path,
    storage_layer: StorageLayer,
    scraper: Any,
    is_batch_mode: bool = False,
    batch_path: Optional[Path] = None,
):
    startup_clear()
    print_banner()

    # ── Stage 1: Load metadata ────────────────────────────────────────────
    metadata, videos, info = None, None, None

    with active_status("[info]Loading HentaiCity metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos()
        except Exception as e:
            console.print(f"[error]Failed to load metadata: {e}[/error]")
            time.sleep(2)
            return

    if not metadata or not videos:
        console.print("[error]Could not retrieve HentaiCity metadata.[/error]")
        time.sleep(2)
        return

    content_type = metadata.get("Content Type", "video")
    series_title = metadata.get("Channel/Series", "Unknown")
    total_items  = len(videos)

    startup_clear()
    print_banner()
    console.print(f"[menu]{'Menu':<12}:[/menu] [site]Hentai[/site]")
    console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
    console.print(f"[menu]{'Series':<12}:[/menu] [title]{series_title}[/title]")
    label = "Episodes" if content_type == "video" else "Images"
    console.print(f"[menu]{label:<12}:[/menu] [info]{total_items}[/info]")
    console.print("")

    # ── Stage 2: Single vs Franchise ──────────────────────────────────────
    is_vacuum = False
    scraper.franchise_structure = "flat"

    if is_batch_mode:
        scraper.is_playlist = True
        is_vacuum = True
    elif content_type == "gallery":
        # Gallery is always downloaded as a whole (it's a single album)
        is_vacuum = True
    elif total_items == 1:
        scraper.is_playlist = False
        is_vacuum = False
    else:
        if not sys.stdin.isatty():
            scraper.is_playlist = True
            is_vacuum = True
        else:
            choice = Selector([
                ("Single Episode", "single"),
                ("Whole Franchise (Flat Folder)", "flat"),
                ("Whole Franchise (Nested Subfolders)", "nested"),
            ], "Download", vertical=True).select()

            if choice == "single":
                norm = url.rstrip("/")
                filtered = [v for v in videos if v.get("url", "").rstrip("/") == norm]
                videos[:] = filtered if filtered else videos[:1]
                metadata["Total Videos"] = len(videos)
                scraper.is_playlist = False
                is_vacuum = False
            else:
                scraper.franchise_structure = choice
                scraper.is_playlist = True
                is_vacuum = True

    # ── Stage 3: Resolve target path ──────────────────────────────────────
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
            target_root = lib / "Vacuum" / "Hentai" / "HentaiCity"
        else:
            target_root = lib / "Quick grab"

    # ── Stage 4: Run workflow ─────────────────────────────────────────────
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

    handle_hentaicity_tui(
        url=url,
        tracker=tracker,
        library_root=library_root,
        storage_layer=storage_layer,
        scraper=scraper,
        is_batch_mode=is_batch,
        batch_path=batch_path,
    )
