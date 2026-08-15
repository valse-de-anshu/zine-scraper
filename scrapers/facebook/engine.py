"""
Facebook Engine
================
Site-isolated Facebook scraper engine supporting Profile Pictures/Photos, Main Feed/Timeline, and Reels.
Uses Playwright network interception and HTML/GraphQL parsing with local fallback mechanisms.
"""

import re
import json
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _profile_id_from_url(url: str) -> Optional[str]:
    """Extract a stable profile identifier from a Facebook URL.
    For profile.php?id=NNN returns 'profile.php?id=NNN'.
    For named profiles returns the slug (e.g. 'pachiart31').
    """
    # Numeric ID profiles: profile.php?id=NNN
    m_id = re.search(r"id=(\d+)", url)
    if m_id:
        return f"profile.php?id={m_id.group(1)}"
    # Named slug profiles
    m = re.search(r"facebook\.com/([^/?#]+)", url)
    slug = m.group(1) if m else None
    # Reject profile.php without id param — shouldn't happen but guard anyway
    if slug and slug.lower() == "profile.php":
        return None
    return slug


def _target_from_url(url: str) -> str:
    """Return 'pfp', 'photos', 'reels', or 'feed' based on ?target= param or path."""
    if "?target=pfp" in url:
        return "pfp"
    if "?target=photos" in url or "/photos" in url:
        return "photos"
    if "?target=reels" in url or "/reels" in url:
        return "reels"
    return "feed"


class FacebookEngine:
    """Site-isolated Facebook scraper engine."""

    def __init__(self):
        self.headers = _HEADERS.copy()
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self._cache: Dict[str, Dict] = {}
        self.pw_cookies: List[Dict] = []
        self._load_cookies()

    def _load_cookies(self):
        # 1. Standard browser_cookie3 auto-loader
        try:
            import browser_cookie3
            for loader in [browser_cookie3.chrome, browser_cookie3.firefox, browser_cookie3.edge]:
                try:
                    cj = loader(domain_name="facebook.com")
                    self.session.cookies.update(cj)
                except Exception:
                    pass
        except Exception:
            pass

        # 2. Zen Browser / custom Firefox SQLite cookie parser
        import os
        import sqlite3
        import shutil
        import tempfile

        zen_dir = os.path.expanduser("~/.config/zen")
        if os.path.exists(zen_dir):
            for root, dirs, files in os.walk(zen_dir):
                if "cookies.sqlite" in files:
                    db_path = os.path.join(root, "cookies.sqlite")
                    try:
                        # Copy to temp file to prevent 'database is locked' errors if browser is open
                        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
                            tmp_path = tmp.name
                        shutil.copy2(db_path, tmp_path)

                        conn = sqlite3.connect(tmp_path)
                        cur = conn.cursor()
                        cur.execute("SELECT host, name, value, path, isSecure, expiry FROM moz_cookies WHERE host LIKE '%facebook.com%'")
                        rows = cur.fetchall()
                        for host, name, value, path, is_secure, expiry in rows:
                            self.session.cookies.set(name, value, domain=host, path=path)
                            cookie_dict = {
                                "name": name,
                                "value": value,
                                "domain": host,
                                "path": path,
                                "secure": bool(is_secure),
                            }
                            if expiry and isinstance(expiry, (int, float)) and expiry > 0:
                                # Convert Firefox millisecond timestamps to seconds
                                exp_sec = int(expiry // 1000 if expiry > 10**11 else expiry)
                                cookie_dict["expires"] = exp_sec
                            self.pw_cookies.append(cookie_dict)
                        conn.close()
                        os.unlink(tmp_path)
                    except Exception as e:
                        logger.debug(f"Failed to read Zen cookies from {db_path}: {e}")

    def get_profile_boards(self, profile_url: str) -> List[Dict[str, str]]:
        profile = _profile_id_from_url(profile_url) or "profile"
        m_id = re.search(r"id=(\d+)", profile_url)
        if m_id:
            base_url = f"https://www.facebook.com/profile.php?id={m_id.group(1)}"
        else:
            base_url = f"https://www.facebook.com/{profile}"
        return [
            {"id": "photos", "title": "Photos",      "url": f"{base_url}&target=photos" if m_id else f"{base_url}?target=photos"},
            {"id": "reels",  "title": "Video Reels", "url": f"{base_url}&target=reels"  if m_id else f"{base_url}?target=reels"},
        ]

    def _ensure_profile_scraped(self, profile_id: str, base_url: str):
        if profile_id in self._cache:
            return

        collected_pins: Dict[str, List[Dict]] = {
            "photos": [],
            "reels": [],
            "feed": [],
        }

        # Build the canonical page URL for this profile
        m_id = re.search(r"id=(\d+)", profile_id)
        if m_id:
            profile_page_url = f"https://www.facebook.com/profile.php?id={m_id.group(1)}"
        else:
            profile_page_url = f"https://www.facebook.com/{profile_id}"

        meta = {
            "Title": profile_id,
            "Source": "Facebook",
            "ProfileUrl": profile_page_url,
        }

        # Try HTTP page fetch first — extract photos and reels from embedded JSON
        try:
            r = self.session.get(profile_page_url, timeout=10)
            if r.status_code == 200:
                # Search for photo URLs in embedded JSON scripts
                img_urls = set(re.findall(r'https://scontent[^"\']+\.(?:jpg|png|webp)[^"\']*', r.text))
                for i, img_url in enumerate(img_urls):
                    clean_url = img_url.replace("\\/", "/").replace("&amp;", "&")
                    collected_pins["photos"].append({
                        "id": f"{profile_id}_photo_{i+1}",
                        "title": f"photo_{i+1}",
                        "direct_url": clean_url,
                        "url": clean_url,
                        "is_video": False,
                    })

                reel_urls = set(re.findall(r'https://www\.facebook\.com/reel/\d+', r.text))
                for i, r_url in enumerate(reel_urls):
                    reel_id = r_url.rstrip("/").split("/")[-1]
                    collected_pins["reels"].append({
                        "id": reel_id,
                        "title": f"reel_{reel_id}",
                        "direct_url": r_url,
                        "url": r_url,
                        "is_video": True,
                    })
        except Exception as e:
            logger.debug(f"Facebook HTTP scrape exception: {e}")

        # Attempt Playwright dynamic extraction by visiting specific subpages directly
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=_UA,
                    viewport={"width": 1280, "height": 800}
                )
                if self.pw_cookies:
                    context.add_cookies(self.pw_cookies)
                page = context.new_page()

                # 1. Load profile page to extract display name
                try:
                    page.goto(profile_page_url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(3000)

                    # Extract real human display name
                    display_name = None
                    EXCLUDED_HEADINGS = [
                        "Personal details", "Education", "Work", "Places lived",
                        "Contact and basic info", "Contact info", "Links", "Intro",
                        "Family and relationships", "Details about you", "Life events",
                        "Highlights", "Posts", "Pinned post", "Other posts", "Filters",
                        "About", "Reels", "Photos", "Friends", "People you may know"
                    ]
                    for h in page.query_selector_all("h1, h2"):
                        t = h.inner_text().strip()
                        if t and t not in EXCLUDED_HEADINGS and not t.startswith("http"):
                            display_name = t
                            break

                    if not display_name:
                        page_title = page.title()
                        if page_title and "Facebook" in page_title:
                            clean_t = page_title.split("|")[0].split("-")[0].strip()
                            if clean_t and clean_t.lower() != "facebook":
                                display_name = clean_t

                    if display_name:
                        meta["Title"] = " ".join(display_name.split())
                    elif profile_id:
                        meta["Title"] = profile_id.replace(".", " ").replace("_", " ").title()
                except Exception:
                    pass

                # 2. Scrape Photos subpage directly (/photos or ?sk=photos)
                try:
                    photos_url = (
                        f"https://www.facebook.com/profile.php?id={m_id.group(1)}&sk=photos"
                        if m_id else
                        f"https://www.facebook.com/{profile_id}/photos"
                    )
                    page.goto(photos_url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2000)
                    for _ in range(30):
                        page.evaluate("window.scrollBy(0, 1500)")
                        page.wait_for_timeout(400)

                    # Extract photo post links from DOM
                    photo_anchors = page.query_selector_all("a[href*='/photo'], a[href*='fbid=']")
                    for i, a in enumerate(photo_anchors):
                        href = a.get_attribute("href")
                        if href and ("photo" in href or "fbid=" in href):
                            full_url = href if href.startswith("http") else f"https://www.facebook.com{href}"
                            img_child = a.query_selector("img")
                            img_src = img_child.get_attribute("src") if img_child else full_url
                            if img_src:
                                clean_src = img_src.replace("&amp;", "&")
                                # Upgrade thumbnail parameter constraints to max dimensions
                                clean_src = re.sub(r"ctp=s\d+x\d+", "ctp=s960x960", clean_src)
                                clean_src = re.sub(r"stp=cp\d+[^\&]+", "stp=dst-jpg", clean_src)
                                clean_src = re.sub(r"p\d+x\d+/", "", clean_src)
                                p_id = f"{profile_id}_photo_{i+1}"
                                if not any(p["id"] == p_id for p in collected_pins["photos"]):
                                    collected_pins["photos"].append({
                                        "id": p_id,
                                        "title": f"photo_{i+1}",
                                        "direct_url": clean_src,
                                        "url": full_url,
                                        "is_video": False,
                                    })
                except Exception:
                    pass

                # 3. Scrape Reels subpage directly (/reels or ?sk=reels)
                try:
                    reels_url = (
                        f"https://www.facebook.com/profile.php?id={m_id.group(1)}&sk=reels"
                        if m_id else
                        f"https://www.facebook.com/{profile_id}/reels"
                    )
                    page.goto(reels_url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2000)
                    for _ in range(20):
                        page.evaluate("window.scrollBy(0, 1500)")
                        page.wait_for_timeout(400)

                    reel_anchors = page.query_selector_all("a[href*='/reel/']")
                    for i, a in enumerate(reel_anchors):
                        href = a.get_attribute("href")
                        if href and "/reel/" in href and not href.endswith("/reel/?s=tab"):
                            full_url = href if href.startswith("http") else f"https://www.facebook.com{href}"
                            reel_id = re.search(r"/reel/(\d+)", full_url)
                            rid = reel_id.group(1) if reel_id else f"{profile_id}_reel_{i+1}"
                            if not any(p["id"] == rid for p in collected_pins["reels"]):
                                collected_pins["reels"].append({
                                    "id": rid,
                                    "title": f"reel_{rid}",
                                    "direct_url": full_url,
                                    "url": full_url,
                                    "is_video": True,
                                })
                except Exception:
                    pass

                browser.close()
        except Exception as e:
            logger.debug(f"Facebook Playwright subpage extraction exception: {e}")

        self._cache[profile_id] = {
            "meta": meta,
            "pins": collected_pins,
        }

    def get_board_pins(self, section_url: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        profile_id = _profile_id_from_url(section_url) or "profile"
        target = _target_from_url(section_url)
        self._ensure_profile_scraped(profile_id, section_url)

        cached = self._cache.get(profile_id, {})
        meta = cached.get("meta", {"Title": profile_id, "Source": "Facebook"})
        pins_by_target = cached.get("pins", {})
        pins = pins_by_target.get(target, [])

        # Fallback for feed: merge photos and reels if feed empty
        if target == "feed" and not pins:
            pins = pins_by_target.get("photos", []) + pins_by_target.get("reels", [])

        return meta, pins

    def get_profile_pins(self, profile_url: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        return self.get_board_pins(profile_url)

    def get_pin_info(self, item_url: str) -> Dict[str, Any]:
        item_id = item_url.rstrip("/").split("/")[-1]
        is_reel = "/reel/" in item_url
        return {
            "id": item_id,
            "title": f"facebook_{item_id}",
            "direct_url": item_url,
            "url": item_url,
            "is_video": is_reel,
        }
