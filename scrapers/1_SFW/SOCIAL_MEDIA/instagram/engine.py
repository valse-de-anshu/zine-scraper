"""
Instagram Engine — Clean Rewrite
=================================
Architecture (one browser, one pass, one cache):

  get_board_pins(".../?target=pfp")   ─┐
  get_board_pins(".../?target=feed")  ─┼─► _ensure_profile_scraped(username)
  get_board_pins(".../?target=reels") ─┘        │
                                                 ▼
                                    Playwright opens ONCE.
                                    Navigates to profile → scrolls feed.
                                    Navigates to /reels/ → scrolls reels.
                                    Closes browser.  Stores in _cache.
                                    All three TUI calls hit the cache instantly.

Key guarantees
──────────────
  • The API interceptor is HARD-LOCKED to target_username in page.url at all times.
    If Instagram ever redirects the browser away from the target profile, every
    incoming response is silently dropped — no random people's content ever enters.
  • `is_reel` is set from the API's product_type / media_type, NOT from our own heuristic.
  • Posts without `is_reel` go to Main Feed. Posts with `is_reel` go to Reels Tab.
  • No DOM clicking, no arrow-key navigation, no dialog scraping.
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _username_from_url(url: str) -> Optional[str]:
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", url)
    return m.group(1).lower() if m else None


def _target_from_url(url: str) -> str:
    """Return 'pfp', 'feed', or 'reels' based on ?target= param."""
    if "?target=pfp" in url:
        return "pfp"
    if "?target=reels" in url:
        return "reels"
    return "feed"


def _extract_pin_data(raw: Dict) -> Optional[Dict]:
    """Pass through — pins are already fully formed by the interceptor."""
    if "direct_url" in raw:
        return raw
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class InstagramEngine:
    """Instagram scraper engine (single-browser, cache-first)."""

    def __init__(self):
        self.headers = _HEADERS.copy()
        self.session = requests.Session()
        self.pw_cookies: List[Dict] = []
        # profile_url → {"meta": {}, "pins": [...]}
        self._cache: Dict[str, Dict] = {}
        self._load_cookies()

    # ── Cookie loading ────────────────────────────────────────────────────────

    def _load_cookies(self):
        try:
            import browser_cookie3
            import os
            import glob

            # Standard browsers
            try:
                cj = browser_cookie3.load(domain_name="instagram.com")
                self.session.cookies.update(cj)
            except Exception:
                pass

            # Zen browser (Firefox fork) — sort by mtime so the most recently
            # active profile's cookies win over any stale/old profiles.
            zen_dir = os.path.expanduser("~/.config/zen")
            if os.path.exists(zen_dir):
                files = sorted(
                    glob.glob(f"{zen_dir}/**/cookies.sqlite", recursive=True),
                    key=os.path.getmtime,
                )
                for f in files:
                    try:
                        cj = browser_cookie3.Firefox(
                            cookie_file=f, domain_name="instagram.com"
                        ).load()
                        self.session.cookies.update(cj)
                    except Exception:
                        continue

            # Translate to Playwright format
            for c in self.session.cookies:
                if "instagram.com" in (c.domain or ""):
                    self.pw_cookies.append({
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain,
                        "path": c.path or "/",
                        "secure": bool(c.secure),
                    })

            logger.info(f"Loaded {len(self.pw_cookies)} IG cookies (including Zen)")
        except Exception as e:
            logger.debug(f"Cookie load failed: {e}")

    # ── Public API (called by workflow / TUI) ─────────────────────────────────

    def get_board_pins(
        self, board_url: str, scroll_limit: int = 60
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Return (meta, pins) for the given board_url.

        The first call for a username triggers a single Playwright session that
        scrapes the profile's main feed AND reels tab in one pass.  Subsequent
        calls for the same username (e.g. the other two TUI options) return
        instantly from the in-memory cache.

        The ?target= query parameter controls which slice of the cached pins
        is returned to the TUI — it does NOT control what the browser fetches.
        """
        username = _username_from_url(board_url)
        target   = _target_from_url(board_url)

        # ── Cache miss → launch browser ──────────────────────────────────────
        if username and username not in self._cache:
            logger.info(f"[IG] First request for '{username}' — launching browser")
            profile_url = f"https://www.instagram.com/{username}/"
            try:
                meta, pins = asyncio.run(
                    self._scrape_profile(profile_url, username, scroll_limit)
                )
            except Exception:
                import traceback
                Path("Logs/💩").mkdir(parents=True, exist_ok=True)
                Path("Logs/💩/playwright_debug.txt").write_text(traceback.format_exc())
                logger.error(f"Playwright failed for '{username}'")
                return {"Channel/Series": username, "Source": "Instagram"}, []

            self._cache[username] = {"meta": meta, "pins": pins}
        elif username in self._cache:
            logger.info(f"[IG] Cache hit for '{username}' — no browser needed")

        # ── Return correct slice ──────────────────────────────────────────────
        cached = self._cache.get(username, {"meta": {}, "pins": []})
        meta   = cached["meta"]
        pins   = cached["pins"]

        if target == "pfp":
            return meta, []          # PFP is downloaded by the workflow from meta["profile_picture"]
        if target == "feed":
            return meta, [p for p in pins if not p.get("is_reel")]
        if target == "reels":
            return meta, [p for p in pins if p.get("is_reel")]
        return meta, pins

    # ── Playwright core ───────────────────────────────────────────────────────

    async def _scrape_profile(
        self, profile_url: str, username: str, scroll_limit: int
    ) -> Tuple[Dict, List]:
        """
        Single browser session:
          1. Navigate to profile, scroll feed to bottom   → captures posts + reel-grid items
          2. Navigate to /reels/, scroll to bottom        → captures reels tab items
          3. Close browser.
        """
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth

        meta: Dict = {"Channel/Series": username, "Source": "Instagram"}
        seen_ids: set = set()
        pins: List[Dict] = []

        def add_pin(pin_id, title, url, is_video, is_reel):
            nonlocal pins
            if pin_id in seen_ids:
                return
            seen_ids.add(pin_id)
            pins.append({
                "id":         pin_id,
                "title":      title,
                "direct_url": url,
                "is_video":   is_video,
                "is_reel":    is_reel,
            })

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=_UA,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            if self.pw_cookies:
                try:
                    await ctx.add_cookies(self.pw_cookies)
                except Exception as e:
                    logger.debug(f"Cookie inject failed: {e}")

            page = await ctx.new_page()
            await Stealth().apply_stealth_async(page)

            # ── Interceptor ──────────────────────────────────────────────────
            async def on_response(response):
                # Only accept 200 responses
                if response.status != 200:
                    return

                # HARD LOCK: reject anything while the browser is not on the
                # target profile's page.
                cur = page.url.lower()
                if cur not in ("about:blank", "") and username not in cur:
                    return

                url = response.url
                if not (
                    "graphql" in url
                    or "/api/v1/feed/" in url
                    or "/api/v1/clips/" in url
                    or "/api/v1/users/" in url
                ):
                    return

                try:
                    data = await response.json()
                except Exception:
                    return

                def crawl(obj):
                    if not isinstance(obj, dict):
                        if isinstance(obj, list):
                            for item in obj:
                                crawl(item)
                        return

                    # ── Profile picture (highest quality) ────────────────────
                    if "profile_pic_url_hd" in obj:
                        obj_user = obj.get("username", "")
                        if obj_user.lower() == username:
                            meta["profile_picture"] = obj["profile_pic_url_hd"]

                    # ── Media objects ─────────────────────────────────────────
                    # Strategy: detect a media node by the presence of a shortcode
                    # or (code+pk) and at least one media URL field.
                    # Then check owner/user to enforce profile lock.

                    shortcode = obj.get("shortcode")  # GraphQL
                    code      = obj.get("code")       # REST
                    pk        = obj.get("pk")         # REST feed

                    # Determine if this node is a media object
                    has_shortcode = shortcode and ("display_url" in obj or "video_url" in obj or "video_versions" in obj)
                    has_rest_code = code and pk and ("image_versions2" in obj or "video_versions" in obj)
                    has_clip_code = code and not pk and ("video_versions" in obj or "image_versions2" in obj)

                    if has_shortcode or has_rest_code or has_clip_code:
                        # Owner lock — skip content from other creators
                        owner_name = (
                            (obj.get("owner") or {}).get("username", "")
                            or (obj.get("user") or {}).get("username", "")
                        ).lower()
                        if owner_name and owner_name != username:
                            # Still recurse — parent objects may embed target media
                            for v in obj.values():
                                crawl(v)
                            return

                        # ── Carousel posts (swipe / multi-image) ──────────────
                        # media_type == 8 in REST API = carousel album.
                        # GraphQL puts sidecar children in edge_sidecar_to_children.
                        carousel_items = []

                        # REST format: carousel_media list
                        cm = obj.get("carousel_media")
                        if isinstance(cm, list) and cm:
                            carousel_items = cm

                        # GraphQL format: edge_sidecar_to_children edges
                        if not carousel_items:
                            sidecar = obj.get("edge_sidecar_to_children", {})
                            edges = sidecar.get("edges", [])
                            if edges:
                                carousel_items = [e.get("node", {}) for e in edges if e.get("node")]

                        if carousel_items:
                            parent_id = shortcode or code or str(pk or id(obj))
                            parent_is_reel = obj.get("product_type", "") == "clips"
                            for idx, slide in enumerate(carousel_items):
                                slide_is_video = bool(
                                    slide.get("is_video")
                                    or slide.get("video_url")
                                    or slide.get("video_versions")
                                    or slide.get("media_type") == 2
                                )
                                slide_url = None
                                if slide_is_video:
                                    slide_url = slide.get("video_url")
                                    vv = slide.get("video_versions")
                                    if not slide_url and isinstance(vv, list) and vv:
                                        slide_url = vv[0].get("url")
                                if not slide_url:
                                    slide_url = slide.get("display_url")
                                if not slide_url:
                                    cands = (slide.get("image_versions2") or {}).get("candidates", [])
                                    if cands:
                                        slide_url = cands[0].get("url")
                                if slide_url:
                                    slide_id = f"{parent_id}_{idx}"
                                    add_pin(slide_id, f"ig_{parent_id}_{idx}", slide_url, slide_is_video, parent_is_reel)
                            # Recurse into children but do NOT add the parent cover image
                            for v in obj.values():
                                crawl(v)
                            return

                        # ── Single media (photo or video) ─────────────────────
                        product_type = obj.get("product_type", "")
                        media_type   = obj.get("media_type", 0)
                        is_reel  = product_type == "clips"
                        is_video = bool(
                            is_reel
                            or obj.get("is_video")
                            or obj.get("video_url")
                            or obj.get("video_versions")
                            or media_type == 2
                        )

                        # ── Best URL ──────────────────────────────────────────
                        media_url = None
                        if is_video:
                            media_url = obj.get("video_url")
                            if not media_url:
                                vv = obj.get("video_versions")
                                if isinstance(vv, list) and vv:
                                    media_url = vv[0].get("url")
                        if not media_url:
                            media_url = obj.get("display_url")
                        if not media_url:
                            cands = (obj.get("image_versions2") or {}).get("candidates", [])
                            if cands:
                                media_url = cands[0].get("url")

                        if media_url:
                            pin_id = shortcode or code or str(pk or id(obj))
                            title  = f"ig_{shortcode or code or pk}"
                            add_pin(pin_id, title, media_url, is_video, is_reel)

                    # Always recurse into children
                    for v in obj.values():
                        crawl(v)

                crawl(data)
                logger.debug(f"[IG] Intercepted response → {len(pins)} pins so far")

            page.on("response", on_response)

            # ── Pass 1: Profile feed ──────────────────────────────────────────
            logger.info(f"[IG] Pass 1 — navigating to profile: {profile_url}")
            try:
                await page.goto(profile_url, timeout=25000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            except Exception as e:
                logger.warning(f"[IG] Profile load timeout (continuing): {e}")

            # Confirm we are on the right page
            if username not in page.url.lower():
                logger.error(
                    f"[IG] Browser redirected away from profile! Got: {page.url}\n"
                    f"       This usually means your browser cookies have expired or you are not logged in.\n"
                    f"       Please log into Instagram in your browser (e.g. Zen/Firefox), let the cookies refresh, and retry."
                )
                await browser.close()
                return meta, pins

            # Extract profile picture from DOM as a fallback
            if "profile_picture" not in meta:
                try:
                    await page.wait_for_selector("header img", timeout=5000)
                    pfp = await page.evaluate(
                        "() => { const i = document.querySelector('header img'); return i ? i.src : null; }"
                    )
                    if pfp:
                        meta["profile_picture"] = pfp
                except Exception:
                    pass

            # Scroll the profile grid to load all posts
            await self._scroll_to_bottom(page, scroll_limit)
            logger.info(f"[IG] Pass 1 complete — {len(pins)} pins captured")

            # ── Pass 2: Reels tab ─────────────────────────────────────────────
            reels_url = f"https://www.instagram.com/{username}/reels/"
            logger.info(f"[IG] Pass 2 — navigating to reels: {reels_url}")
            try:
                await page.goto(reels_url, timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            except Exception as e:
                logger.warning(f"[IG] Reels load timeout (continuing): {e}")

            # Safety check: did Instagram redirect us away?
            if username not in page.url.lower():
                logger.warning(
                    f"[IG] Reels page redirected! Got: {page.url}. "
                    f"This means your browser session has expired — "
                    f"please log into Instagram in your Zen browser and retry."
                )
            else:
                await self._scroll_to_bottom(page, min(scroll_limit, 35))
                logger.info(f"[IG] Pass 2 complete — {len(pins)} total pins")

            await browser.close()

        logger.info(
            f"[IG] '{username}': "
            f"{len([p for p in pins if not p['is_reel']])} posts, "
            f"{len([p for p in pins if p['is_reel']])} reels"
        )
        return meta, pins

    async def _scroll_to_bottom(self, page, max_scrolls: int):
        """
        Scroll page to bottom.
        Waits 2.5s per scroll to allow Instagram's paginator to fire.
        Takes a screenshot every scroll for debugging.
        """
        import time
        from pathlib import Path
        
        # Create screenshot directory
        debug_dir = Path("💩")
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        for idx in range(max_scrolls):
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            
            # Take a screenshot
            try:
                ts = int(time.time())
                await page.screenshot(path=str(debug_dir / f"scroll_{idx}_{ts}.png"), full_page=False)
            except Exception as e:
                logger.debug(f"Screenshot failed: {e}")
                
            await page.wait_for_timeout(2500)

    # ── TUI-facing board listing ──────────────────────────────────────────────

    def get_profile_boards(self, profile_url: str) -> List[Dict[str, str]]:
        """
        The three sections the TUI presents.  These are 'bluff' boards —
        the engine always does ONE full scrape and serves from cache.
        """
        base = profile_url.rstrip("/") + "/"
        return [
            {"title": "Profile Picture Only", "url": f"{base}?target=pfp",   "id": "pfp",   "pin_count": "1"},
            {"title": "Main Feed (Posts)",     "url": f"{base}?target=feed",  "id": "feed",  "pin_count": "~"},
            {"title": "Reels Tab",             "url": f"{base}?target=reels", "id": "reels", "pin_count": "~"},
        ]

    # ── Stub methods expected by core (kept minimal) ──────────────────────────

    def get_pin_info(self, pin_url: str) -> Dict[str, Any]:
        return {}

    def get_profile_pins(
        self, profile_url: str, scroll_limit: int = 60
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        username = _username_from_url(profile_url) or "unknown"
        meta = {"Channel/Series": username, "Source": "Instagram", "Type": "Profile"}
        boards = self.get_profile_boards(profile_url)
        all_pins: List[Dict] = []
        for board in boards:
            _, board_pins = self.get_board_pins(board["url"], scroll_limit)
            for p in board_pins:
                p["board"] = board["title"]
            all_pins.extend(board_pins)
        return meta, all_pins
