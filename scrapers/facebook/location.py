import sys
import time
from pathlib import Path
from typing import Optional, Any
from core.ui import Selector, get_theme_input_ansi, console

def get_save_path(
    url: str,
    scraper: Any,
    is_batch: bool,
    batch_path: Optional[Path],
    default_root: Path,
    store_layer: Any,
) -> Optional[Path]:
    if batch_path is not None:
        return Path(batch_path)

    if not is_batch and sys.stdin.isatty():
        from core.ui import startup_clear, print_banner, console, active_status
        startup_clear()
        print_banner()

        import re
        display_url = url
        profile_display_name = None
        EXCLUDED_HEADINGS = {
            "Personal details", "Details", "Education", "Work", "Places lived",
            "Contact and basic info", "Contact info", "Links", "Intro", "Featured",
            "Family and relationships", "Details about you", "Life events",
            "Highlights", "Posts", "Pinned post", "Other posts", "Filters",
            "About", "Reels", "Photos", "Friends", "People you may know",
            "Videos", "Check-ins", "Likes", "Groups", "Events", "Sports",
            "Music", "Books", "Movies", "TV shows", "Other names",
        }
        with active_status("[info]Wait... let me read the profile!![/info]", spinner="dots"):
            try:
                from scrapers.facebook.engine import FacebookEngine
                from playwright.sync_api import sync_playwright
                engine = FacebookEngine()
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    ctx = browser.new_context(user_agent=engine.headers["User-Agent"], viewport={"width": 1280, "height": 800})
                    if engine.pw_cookies:
                        ctx.add_cookies(engine.pw_cookies)
                    pg = ctx.new_page()
                    pg.goto(url, wait_until="domcontentloaded", timeout=12000)
                    pg.wait_for_timeout(2500)

                    # Strategy 1: "Add Friend <name>" button aria-label (reliable even without login)
                    import re as _re
                    for el in pg.query_selector_all('[role="button"][aria-label]'):
                        lbl = el.get_attribute("aria-label") or ""
                        m = _re.match(r'^(?:Add Friend|Follow|Message)\s+(.+)$', lbl)
                        if m:
                            profile_display_name = m.group(1).strip()
                            break

                    # Strategy 2: profile cover photo's sibling name link aria-label
                    if not profile_display_name:
                        cover_link = pg.query_selector('a[role="link"][aria-label="View profile cover photo"]')
                        if cover_link:
                            # next sibling link is the profile name link
                            sibling = pg.evaluate("""
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
                            """, cover_link)
                            if sibling and len(sibling.strip()) > 1:
                                profile_display_name = sibling.strip()

                    # Strategy 3: h1 → h2 → h3, filtered + max 60 chars (no activity sentences)
                    if not profile_display_name:
                        def _pick_name(selector):
                            for h in pg.query_selector_all(selector):
                                txt = " ".join(h.inner_text().strip().split())
                                if (txt and txt not in EXCLUDED_HEADINGS
                                        and not txt.startswith("http")
                                        and len(txt) > 1 and len(txt) <= 80
                                        and not any(kw in txt for kw in (" updated ", " shared ", " posted ", " added ", " is ", " was "))):
                                    return txt
                            return None
                        profile_display_name = _pick_name("h1") or _pick_name("h2") or _pick_name("h3")

                    # Strategy 4: page <title> tag
                    if not profile_display_name:
                        title = pg.title()
                        if title and "|" in title:
                            candidate = title.split("|")[0].strip()
                            if candidate.lower() not in ("facebook", ""):
                                profile_display_name = candidate

                    browser.close()
            except Exception:
                pass

        if not profile_display_name:
            m_id = re.search(r"id=(\d+)", url)
            if m_id:
                profile_display_name = f"ID {m_id.group(1)}"
            else:
                m = re.search(r"facebook\.com/([^/?#]+)", url)
                profile_display_name = m.group(1) if m else "Facebook Profile"

        console.print(f"[menu]Site[/menu]         : [title]Facebook[/title]")
        console.print(f"[menu]Username[/menu]     : [title]{profile_display_name}[/title]")
        console.print(f"[menu]URL[/menu]          : [unselected]{display_url}[/unselected]")
        console.print(f"[menu]Save Path[/menu]    : [info]{default_root}[/info]\n")

        loc_choice = Selector([
            ("Use Default Location", "DEFAULT"),
            ("Select Custom Location", "CUSTOM"),
            ("Back", "BACK"),
        ], "Save Location").select()
    else:
        loc_choice = "DEFAULT"

    if loc_choice == "BACK":
        return None
    if loc_choice == "DEFAULT":
        return default_root

    # CUSTOM branch
    while True:
        console.print("\n[menu]Enter Folder Path (Empty to cancel): [/menu]", end="")
        sys.stdout.write(get_theme_input_ansi())
        sys.stdout.flush()
        custom_path_str = input().strip()
        sys.stdout.write("\033[0m")
        sys.stdout.flush()

        if not custom_path_str:
            for _ in range(2):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            return None

        is_valid, err_msg = store_layer.validate_directory(Path(custom_path_str))
        if not is_valid:
            console.print(f"\n[error]Invalid directory.[/error]")
            console.print(f"[warning]Reason:\n{err_msg}[/warning]")
            time.sleep(2)
            for _ in range(4):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            continue
        
        return Path(custom_path_str)
