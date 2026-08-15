"""
scrapers/pinterest/tui.py
--------------------------
Site-specific TUI layer for Pinterest.
Handles board selection menus (MultiSelector) and delegates execution to workflow.py.
"""

import sys
import time
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.ui import (
    console, startup_clear, print_banner, MultiSelector, active_status
)
from core.history import HistoryLayer
from core.storage import StorageLayer
from .scraper import PinterestScraper
from .location import get_save_path
from .workflow import run_workflow

logger = logging.getLogger(__name__)

def handle_pinterest_tui(
    url: str,
    tracker: HistoryLayer,
    scraper: PinterestScraper,
    target_root: Path,
    storage_layer: StorageLayer,
    is_batch: bool = False
):
    """
    Pinterest Stage 1 TUI Menu selector.
    """
    link_type = scraper.get_link_type()

    with active_status("[info]Scouting Pinterest...[/info]", spinner="dots"):
        try:
            if link_type == "profile":
                boards = scraper.engine.get_profile_boards(url)
                user_match = re.search(r"pinterest\.[a-z\.]+/([^/?#]+)", url)
                profile_name = user_match.group(1) if user_match else "Unknown User"
            else:
                user_match = re.search(r"pinterest\.[a-z\.]+/([^/?#]+)", url)
                profile_name = user_match.group(1) if user_match else "Unknown User"
                # If it's a single pin, the profile_name becomes "pin" but is ignored in workflow anyway
                import urllib.parse
                raw_title = url.split("/")[-2] if url.endswith("/") else url.split("/")[-1]
                boards = [{
                    "url": url,
                    "title": urllib.parse.unquote(raw_title).replace("-", " ").title(),
                    "id": "single"
                }]
        except Exception as e:
            console.print(f"[error]Failed to scout profile: {e}[/error]")
            time.sleep(2)
            return

    if not boards:
        console.print("[warning]No boards found or profile is private.[/warning]")
        time.sleep(2)
        return

    selected_boards = boards
    if link_type == "profile":
        startup_clear()
        print_banner()
        console.print(f"[menu]Title[/menu]        : [title]Pinterest[/title]")
        console.print(f"[menu]Profile[/menu]      : [title]{profile_name}[/title]")
        console.print(f"[menu]Found[/menu]        : [info]{len(boards)} Boards[/info]\n")
        console.print("  [dim italic]* Disclaimer: Pinterest chronically lies about their pin counts to look good.[/dim italic]")
        console.print("  [dim italic]  If a board advertises '300 Pins' but we only extract 280, don't panic![/dim italic]")
        console.print("  [dim italic]  Our scraper pulls the true, un-deleted reality. Pinterest just likes to hallucinate.[/dim italic]\n")

        board_options = []
        for b in boards:
            count = b.get("pin_count", "Unknown")
            board_options.append({
                "name": b["title"],
                "url": b["url"],
                "title": b["title"],
                "id": b.get("id"),
                "right_text": f"{count} Pins"
            })

        board_options.append({
            "name": "Back",
            "url": "BACK",
            "title": "Back",
            "id": "BACK",
            "right_text": "",
            "is_action": True
        })

        if not is_batch and sys.stdin.isatty():
            selected_boards = MultiSelector(board_options, "Select Boards to Scrape").select()
            if not selected_boards:
                console.print("[warning]No boards selected.[/warning]")
                time.sleep(1)
                return
                
            if any(b.get("id") == "BACK" for b in selected_boards):
                return
                
            selected_boards = [b for b in selected_boards if b.get("id") != "BACK"]
        else:
            selected_boards = [b for b in board_options if b.get("id") != "BACK"]
            if getattr(scraper, '_batch_quick_grab', False):
                selected_boards = selected_boards[:1]

    startup_clear()
    print_banner()

    # Call run_workflow in workflow.py
    run_workflow(selected_boards, tracker, scraper, target_root, storage_layer, profile_name)

def handle_tui(url, tracker, location_manager, scraper, batch_path=None, is_batch=False):
    """Unified handshake wrapper for Pinterest TUI."""
    from core.paths import get_container_root
    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_root = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
    if not target_root:
        return
    handle_pinterest_tui(url, tracker, scraper, target_root, location_manager, is_batch=is_batch)
