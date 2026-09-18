"""
scrapers/idagio/tui.py
----------------------
Site-specific TUI layer for Idagio.
Conforms to the 7-file structure contract, delegating loops to workflow.py.
"""

import sys
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.ui import (
    console, startup_clear, print_banner, active_status
)
from core.history import HistoryLayer
from core.storage import StorageLayer
from .scraper import IdagioScraper
from .location import get_save_path
from .workflow import run_workflow

logger = logging.getLogger(__name__)

def handle_tui(url, tracker, location_manager, scraper, batch_path=None, is_batch=False):
    """Unified handshake wrapper for Idagio TUI."""
    # Metadata resolution
    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos()
            title = metadata.get("Channel/Series", "Unknown")
        except Exception as e:
            console.print(f"[error]Failed to fetch metadata: {e}[/error]")
            if not is_batch:
                console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
            else:
                time.sleep(1.5)
            return

    # Determine target path dynamically using get_container_root and location.py
    from core.paths import get_container_root
    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_path = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
    if not target_path:
        return

    # Show Summary
    startup_clear()
    print_banner()
    if is_batch:
        console.print(f"[menu]Menu[/menu]         : [site]Batch Mode[/site]")
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    cat_display = f"{target_path.parts[-2]} / {target_path.parts[-1]}" if len(target_path.parts) > 1 else target_path.name
    console.print(f"[menu]Category[/menu]     : [info]{cat_display}[/info]")
    console.print("")

    # Run the workflow
    run_workflow(url, tracker, location_manager, scraper, target_path, metadata, videos, info)
    if not is_batch:
        console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
