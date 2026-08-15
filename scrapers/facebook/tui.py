"""
scrapers/facebook/tui.py
------------------------
Site-specific TUI layer for Facebook.
Prompts the user for a Facebook profile URL or username, shows section selection menus
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
from .scraper import FacebookScraper
from .location import get_save_path
from .workflow import run_workflow

logger = logging.getLogger(__name__)

_LIVE_INSTANCE = None


def _normalize_fb_url(raw: str) -> str:
    """
    Accepts either a full Facebook profile URL or a bare username/ID and
    returns a clean canonical profile URL:
        'vivat.sukpongsun.9'                        → 'https://www.facebook.com/vivat.sukpongsun.9/'
        'https://www.facebook.com/vivat.sukpongsun.9' → 'https://www.facebook.com/vivat.sukpongsun.9/'
        'https://www.facebook.com/profile.php?id=61577298388778' → 'https://www.facebook.com/profile.php?id=61577298388778'
    """
    raw = raw.strip()
    if not raw:
        return ""

    if "facebook.com" in raw:
        if "profile.php?id=" in raw or "id=" in raw:
            return raw
        match = re.search(r"facebook\.com/([^/?#]+)", raw)
        if match:
            username = match.group(1)
            return f"https://www.facebook.com/{username}/"
        return raw

    if re.fullmatch(r"[A-Za-z0-9._-]{1,50}", raw):
        return f"https://www.facebook.com/{raw}/"

    return ""


def _prompt_profile_url(is_batch: bool) -> str:
    if is_batch or not sys.stdin.isatty():
        return ""

    startup_clear()
    print_banner()
    console.print("[menu]Site[/menu]         : [title]Facebook[/title]")
    console.print("[info]Enter a profile URL or username to scrape.[/info]")
    console.print("[unselected]Example : https://www.facebook.com/vivat.sukpongsun.9[/unselected]\n")

    raw = console.input("[site]❯ Profile URL / Username :[/site] ").strip()
    return raw


def handle_facebook_tui(
    url: str,
    tracker: HistoryLayer,
    scraper: FacebookScraper,
    target_root: Path,
    storage_layer: StorageLayer,
    is_batch: bool = False
):
    if not url:
        raw = _prompt_profile_url(is_batch)
        if not raw:
            console.print("[warning]No URL entered. Returning to menu.[/warning]")
            time.sleep(1)
            return
        url = _normalize_fb_url(raw)
        if not url:
            console.print(f"[error]Could not recognise '{raw}' as a Facebook URL or username.[/error]")
            time.sleep(2)
            return
        scraper = FacebookScraper(url)

    normalized = _normalize_fb_url(url)
    if normalized:
        url = normalized
        if scraper.url != url:
            _flag = getattr(scraper, "_batch_quick_grab", False)
            scraper = FacebookScraper(url)
            scraper._batch_quick_grab = _flag

    link_type = scraper.get_link_type()

    EXCLUDED_HEADINGS = {
        "Personal details", "Details", "Education", "Work", "Places lived",
        "Contact and basic info", "Contact info", "Links", "Intro", "Featured",
        "Family and relationships", "Details about you", "Life events",
        "Highlights", "Posts", "Pinned post", "Other posts", "Filters",
        "About", "Reels", "Photos", "Friends", "People you may know",
        "Videos", "Check-ins", "Likes", "Groups", "Events", "Sports",
        "Music", "Books", "Movies", "TV shows", "Other names",
    }
    profile_display_name = None

    with active_status("[info]Scouting Facebook profile...[/info]", spinner="dots"):
        try:
            from playwright.sync_api import sync_playwright
            engine = scraper.engine
            with sync_playwright() as _pw:
                _br = _pw.chromium.launch(headless=True)
                _ctx = _br.new_context(user_agent=engine.headers["User-Agent"], viewport={"width": 1280, "height": 800})
                if engine.pw_cookies:
                    _ctx.add_cookies(engine.pw_cookies)
                _pg = _ctx.new_page()
                _pg.goto(url, wait_until="domcontentloaded", timeout=12000)
                _pg.wait_for_timeout(2500)

                # Strategy 1: "Add Friend <name>" / "Follow <name>" button aria-label
                for _el in _pg.query_selector_all('[role="button"][aria-label]'):
                    _lbl = _el.get_attribute("aria-label") or ""
                    _m = re.match(r'^(?:Add Friend|Follow|Message)\s+(.+)$', _lbl)
                    if _m:
                        profile_display_name = _m.group(1).strip()
                        break

                # Strategy 2: profile cover photo sibling name link aria-label
                if not profile_display_name:
                    _cover = _pg.query_selector('a[role="link"][aria-label="View profile cover photo"]')
                    if _cover:
                        _sib = _pg.evaluate("""
                            el => {
                                let s = el.nextElementSibling;
                                while (s) {
                                    if (s.tagName === 'A' && s.getAttribute('role') === 'link') {
                                        return s.getAttribute('aria-label');
                                    }
                                    s = s.nextElementSibling;
                                }
                                return null;
                            }
                        """, _cover)
                        if _sib and len(_sib.strip()) > 1:
                            profile_display_name = _sib.strip()

                # Strategy 3: h1 → h2 → h3, filtered + no activity sentences
                if not profile_display_name:
                    def _pick_name(selector):
                        for _h in _pg.query_selector_all(selector):
                            _txt = " ".join(_h.inner_text().strip().split())
                            if (_txt and _txt not in EXCLUDED_HEADINGS
                                    and not _txt.startswith("http")
                                    and 1 < len(_txt) <= 80
                                    and not any(kw in _txt for kw in (" updated ", " shared ", " posted ", " added ", " is ", " was "))):
                                return _txt
                        return None
                    profile_display_name = _pick_name("h1") or _pick_name("h2") or _pick_name("h3")

                # Strategy 4: page <title> tag
                if not profile_display_name:
                    _title = _pg.title()
                    if _title and "|" in _title:
                        _candidate = _title.split("|")[0].strip()
                        if _candidate.lower() not in ("facebook", ""):
                            profile_display_name = _candidate

                if link_type == "profile":
                    boards = scraper.engine.get_profile_boards(url)
                else:
                    boards = [{"url": url, "title": "Single Item", "id": "single"}]
                _br.close()
        except Exception as e:
            console.print(f"[error]Failed to scout profile: {e}[/error]")
            time.sleep(2)
            return



    if not profile_display_name:
        _m_id = re.search(r"id=(\d+)", url)
        if _m_id:
            profile_display_name = f"ID {_m_id.group(1)}"
        else:
            _m = re.search(r"facebook\.com/([^/?#]+)", url)
            profile_display_name = _m.group(1) if _m else "Facebook User"

    profile_name = profile_display_name

    # OS System Notification Dispatch when scouting finishes
    try:
        from butler.notify import send_os_notification
        send_os_notification(f"Facebook: {profile_name}", f"Scouting complete! Found {len(boards)} section(s) for {profile_name}.", is_success=True)
    except Exception as e:
        logger.debug(f"Failed to send scouting notification: {e}")

    if not boards:
        console.print("[warning]No media content found on profile.[/warning]")
        time.sleep(2)
        return

    selected_boards = boards
    if link_type == "profile":
        startup_clear()
        print_banner()
        console.print(f"[menu]Site[/menu]         : [title]Facebook[/title]")
        console.print(f"[menu]Username[/menu]     : [title]{profile_name}[/title]")
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
                
            if any(b.get("id") == "BACK" for b in selected_boards):
                return
                
            selected_boards = [b for b in selected_boards if b.get("id") != "BACK"]
        else:
            selected_boards = [b for b in board_options if b.get("id") != "BACK"]
            if getattr(scraper, '_batch_quick_grab', False):
                selected_boards = selected_boards[:1]

    startup_clear()
    print_banner()

    run_workflow(selected_boards, tracker, scraper, target_root, storage_layer, profile_name)


def handle_tui(url, tracker, location_manager, scraper, batch_path=None, is_batch=False):
    """Unified handshake wrapper for Facebook TUI."""
    from core.paths import get_container_root
    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_root = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
    if not target_root:
        return
    handle_facebook_tui(url, tracker, scraper, target_root, location_manager, is_batch=is_batch)
