"""
scrapers/hanime_red/tui.py
--------------------------
Hanime.red TUI — Hentai-category flow.

Route logic:
  Batch Mode             → Zero prompts. Link type decides (series -> Vacuum, episode -> Quick Grab), flags (--0, --N) respected.
  Single Episode         → Quick Grab → video only, flat folder, no metadata
  Whole Franchise        → Vacuum     → all episodes in video/ subfolder, metadata & cover saved

The Vacuum / Quick Grab label is NEVER shown in wizard. Label is always "Hentai".
Save Location prompt is NEVER shown — path is derived automatically from user choice.
"""

import re
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
from .scraper import HanimeRedScraper
from .workflow import run_workflow

logger = logging.getLogger(__name__)


def handle_hanime_red_tui(
    url: str,
    tracker: HistoryLayer,
    library_root: Path,
    storage_layer: StorageLayer,
    scraper: HanimeRedScraper,
    is_batch_mode: bool = False,
    batch_path: Optional[Path] = None,
):
    """
    TUI flow for HanimeRed.
    Stage 1 — Load metadata
    Stage 2 — Single / Franchise selector (zero prompts if batch mode)
    Stage 3 — Kick off workflow (path auto-resolved from choice)
    """
    startup_clear()
    print_banner()

    # ── Stage 1: Fetch metadata ──────────────────────────────────────────
    metadata, videos, info = None, None, None

    with active_status("[info]Loading HanimeRed metadata...[/info]", spinner="dots"):
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
        console.print("[error]Could not retrieve HanimeRed metadata.[/error]")
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

    # ── Stage 2: Single vs Franchise Resolution ──────────────────────────
    is_serie_url = bool(re.search(r'/serie(?:s)?/', url))
    is_vacuum = False
    scraper.franchise_structure = "flat"

    if is_batch_mode:
        # Zero interactive prompts in batch mode! Link logic + flags decide.
        if getattr(scraper, "_force_vacuum", False) or getattr(scraper, "_batch_all", False):
            is_vacuum = True
            scraper.is_playlist = True
        elif getattr(scraper, "_batch_quick_grab", False):
            is_vacuum = False
            scraper.is_playlist = False
            if videos:
                videos[:] = videos[:1]
                metadata["Total Videos"] = 1
        elif is_serie_url:
            is_vacuum = True
            scraper.is_playlist = True
        else:
            # Episode link in batch defaults to Quick grab (single episode)
            is_vacuum = False
            scraper.is_playlist = False
            norm_url = url.rstrip("/")
            filtered = [v for v in videos if v.get("url", "").rstrip("/") == norm_url]
            videos[:] = filtered if filtered else videos[:1]
            metadata["Total Videos"] = len(videos)

        if not getattr(scraper, "_force_vacuum", False) and not getattr(scraper, "_batch_all", False):
            chapter_limit = getattr(scraper, "_chapter_limit", None)
            if chapter_limit and isinstance(chapter_limit, int) and chapter_limit > 0:
                if videos and len(videos) > chapter_limit:
                    videos[:] = videos[:chapter_limit]
                    metadata["Total Videos"] = len(videos)

    else:
        # Interactive mode
        if sys.stdin.isatty():
            # If user entered series page, default options are Whole Franchise or Single Episode
            choice = Selector([
                ("Whole Franchise", "franchise"),
                ("Single Episode", "single"),
            ] if is_serie_url else [
                ("Single Episode", "single"),
                ("Whole Franchise", "franchise"),
            ], "Download", vertical=True).select()

            if choice == "single":
                if len(videos) > 1 and sys.stdin.isatty():
                    norm_url = url.rstrip("/")
                    default_idx = 0
                    for i, v in enumerate(videos):
                        if v.get("url", "").rstrip("/") == norm_url:
                            default_idx = i
                            break
                    ep_options = [(v.get("title", f"Episode {i+1}"), i) for i, v in enumerate(videos)]
                    selected_idx = Selector(ep_options, "Select Episode", vertical=True, default_index=default_idx).select()
                    if isinstance(selected_idx, int) and 0 <= selected_idx < len(videos):
                        videos[:] = [videos[selected_idx]]
                    else:
                        return
                else:
                    norm_url = url.rstrip("/")
                    filtered = [v for v in videos if v.get("url", "").rstrip("/") == norm_url]
                    videos[:] = filtered if filtered else videos[:1]
                metadata["Total Videos"] = len(videos)
                scraper.is_playlist = False
                is_vacuum = False
            elif choice == "franchise":
                scraper.is_playlist = True
                is_vacuum = True
            else:
                return
        else:
            scraper.is_playlist = is_serie_url
            is_vacuum = is_serie_url

    # ── Stage 3: Resolve target path directly from choice ─────────────────
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
            target_root = lib / "Vacuum"  /  "HanimeRed"
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

    if not is_batch_mode and sys.stdin.isatty():
        try:
            from core.ui import wait_for_return
            wait_for_return("Download finished. Press Enter to return...")
        except (EOFError, KeyboardInterrupt):
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

    handle_hanime_red_tui(
        url=url,
        tracker=tracker,
        library_root=library_root,
        storage_layer=storage_layer,
        scraper=scraper,
        is_batch_mode=is_batch,
        batch_path=batch_path,
    )
