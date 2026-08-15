"""
scrapers/instagram/tui.py
--------------------------
Site-specific TUI layer for Instagram.
Prompts the user for a profile URL or username, shows board selection menus
(MultiSelector), and delegates execution to workflow.py.
"""

import sys
import re
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.ui import (
    console, startup_clear, print_banner, MultiSelector, active_status
)
from core.history import HistoryLayer
from core.storage import StorageLayer
from .scraper import InstagramScraper
from .location import get_save_path
from .workflow import run_workflow

logger = logging.getLogger(__name__)

_LIVE_INSTANCE = None


def _normalize_ig_url(raw: str) -> str:
    """
    Accepts either a full Instagram profile URL or a bare username and
    returns a clean canonical profile URL:
        'pujaa_singh47'                              → 'https://www.instagram.com/pujaa_singh47/'
        'https://www.instagram.com/pujaa_singh47/'  → 'https://www.instagram.com/pujaa_singh47/'
        'instagram.com/pujaa_singh47'               → 'https://www.instagram.com/pujaa_singh47/'
    Returns empty string if the input is not recognizable.
    """
    raw = raw.strip()
    if not raw:
        return ""

    # Already a full URL — normalise the trailing slash and strip query/fragment
    if "instagram.com" in raw:
        match = re.search(r"instagram\.com/([^/?#]+)", raw)
        if match:
            username = match.group(1)
            return f"https://www.instagram.com/{username}/"
        return raw  # pass through unchanged; let engine deal with it

    # Bare username (no domain) — must look like a valid IG handle
    # IG handles: 1–30 chars, letters/digits/underscores/periods only
    if re.fullmatch(r"[A-Za-z0-9_.]{1,30}", raw):
        return f"https://www.instagram.com/{raw}/"

    return ""  # unrecognizable input


def _prompt_profile_url(is_batch: bool) -> str:
    """
    Interactively ask the user for an Instagram profile URL or username.
    In batch / headless mode returns an empty string (caller must handle).
    """
    if is_batch or not sys.stdin.isatty():
        return ""

    startup_clear()
    print_banner()
    console.print("[menu]Site[/menu]         : [title]Instagram[/title]")
    console.print("[info]Enter a profile URL or @username to scrape.[/info]")
    console.print("[unselected]Examples : https://www.instagram.com/nasa/  or just  nasa[/unselected]\n")

    raw = console.input("[site]❯ Profile URL / Username :[/site] ").strip()
    return raw


def handle_instagram_tui(
    url: str,
    tracker: HistoryLayer,
    scraper: InstagramScraper,
    target_root: Path,
    storage_layer: StorageLayer,
    is_batch: bool = False
):
    """
    Instagram Stage 1 TUI Menu selector.

    If `url` is already a profile URL (supplied by the main funnel), we use it
    directly.  If it resolves to a non-profile link type (single pin / board)
    we fall through to single-board extraction without showing the section menu.
    """
    # ── Dynamic URL prompt ────────────────────────────────────────────────
    # The main funnel always supplies a URL, but it might be an old/cached
    # reference.  For profile URLs we always let the user optionally change it
    # right here — but only when the caller explicitly passes an empty string
    # (e.g. launched directly from a sub-menu rather than the URL bar).
    if not url:
        raw = _prompt_profile_url(is_batch)
        if not raw:
            console.print("[warning]No URL entered. Returning to menu.[/warning]")
            time.sleep(1)
            return
        url = _normalize_ig_url(raw)
        if not url:
            console.print(f"[error]Could not recognise '{raw}' as an Instagram URL or username.[/error]")
            time.sleep(2)
            return
        # Re-build the scraper with the new URL so get_link_type() works correctly
        scraper = InstagramScraper(url)

    # ── Normalise whatever URL the funnel passed us ────────────────────────
    # This handles the case where the user typed a username into the main URL
    # bar (which the funnel would pass here verbatim).
    normalized = _normalize_ig_url(url)
    if normalized:
        url = normalized
        if scraper.url != url:
            _flag = getattr(scraper, "_batch_quick_grab", False)
            scraper = InstagramScraper(url)
            scraper._batch_quick_grab = _flag

    link_type = scraper.get_link_type()

    # ── Scout / board listing ─────────────────────────────────────────────
    with active_status("[info]Scouting Instagram...[/info]", spinner="dots"):
        try:
            if link_type == "profile":
                boards = scraper.engine.get_profile_boards(url)
                user_match = re.search(r"instagram\.[a-z\.]+/([^/?#]+)", url)
                profile_name = user_match.group(1) if user_match else "Unknown User"
            else:
                boards = [{
                    "url": url,
                    "title": url.split("/")[-2].replace("-", " ").title(),
                    "id": "single"
                }]
                profile_name = boards[0]["title"]
        except Exception as e:
            console.print(f"[error]Failed to scout profile: {e}[/error]")
            time.sleep(2)
            return

    if not boards:
        console.print("[warning]No boards found or profile is private.[/warning]")
        time.sleep(2)
        return

    # ── Section selector (MultiSelector) ─────────────────────────────────
    selected_boards = boards
    if link_type == "profile":
        startup_clear()
        print_banner()
        console.print(f"[menu]Site[/menu]         : [title]Instagram[/title]")
        console.print(f"[menu]Profile[/menu]      : [title]{profile_name}[/title]")
        console.print(f"[menu]Found[/menu]        : [info]{len(boards)} Sections[/info]\n")

        board_options = []
        for b in boards:
            board_options.append({
                "name": b["title"],
                "url": b["url"],
                "title": b["title"],
                "id": b.get("id"),
                "right_text": "Live Extraction"
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
            selected_boards = MultiSelector(board_options, "Select Sections to Scrape").select()
            if not selected_boards:
                console.print("[warning]No sections selected.[/warning]")
                time.sleep(1)
                return
                
            # If user selected Back (either alone or with others), just return
            if any(b.get("id") == "BACK" for b in selected_boards):
                return
                
            # Filter out the Back option just in case it's in the list
            selected_boards = [b for b in selected_boards if b.get("id") != "BACK"]
        else:
            selected_boards = [b for b in board_options if b.get("id") != "BACK"]
            if getattr(scraper, '_batch_quick_grab', False):
                selected_boards = selected_boards[:1]

    startup_clear()
    print_banner()

    # ── Hand off to the download workflow ─────────────────────────────────
    run_workflow(selected_boards, tracker, scraper, target_root, storage_layer, profile_name)


def handle_tui(url, tracker, location_manager, scraper, batch_path=None, is_batch=False):
    """Unified handshake wrapper for Instagram TUI."""
    from core.paths import get_container_root
    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_root = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
    if not target_root:
        return
    handle_instagram_tui(url, tracker, scraper, target_root, location_manager, is_batch=is_batch)
