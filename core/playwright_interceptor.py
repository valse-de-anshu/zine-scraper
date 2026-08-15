import asyncio
import json
import logging
import sys
import glob
import os
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Keywords that identify the video source API endpoint
SOURCE_KEYWORDS = [
    "getSources", "getSourcesNew", "sourcesTruck",
    # megaplay.buzz specific
    "apivid", "api/source", "getSource", "sources.php",
]


def _bootstrap_venv() -> bool:
    """
    Attempt to import playwright. If it fails, search for a Python virtual
    environment (venv / .venv / env) in the project root and add its
    site-packages to sys.path.

    This lets the scraper run from system Python on any device without any
    hardcoded paths — as long as the user has run the wizard setup (or
    manually created the venv).

    Returns True if playwright is importable after the attempt.
    """
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        pass

    # Walk up from this file to find the project root (contains orchestrator.py)
    search_root = Path(__file__).resolve().parent
    for _ in range(4):  # max 4 levels up
        if (search_root / "orchestrator.py").exists():
            break
        search_root = search_root.parent

    venv_candidates = ["venv", ".venv", "env", ".env"]
    for venv_name in venv_candidates:
        venv_path = search_root / venv_name
        if not venv_path.is_dir():
            continue
        # Find site-packages (python version agnostic)
        site_pkgs = glob.glob(str(venv_path / "Lib" / "site-packages")) if os.name == "nt" else glob.glob(str(venv_path / "lib" / "python*" / "site-packages"))
        for sp in site_pkgs:
            if sp not in sys.path:
                sys.path.insert(0, sp)
                logger.debug(f"[Playwright] Added venv site-packages: {sp}")

    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        logger.error(
            "[Playwright] playwright not found. Run the wizard setup or manually run:\n"
            "  ./venv/bin/pip install playwright\n"
            "  ./venv/bin/playwright install chromium"
        )
        return False


async def _intercept_embed(embed_url: str) -> Optional[str]:
    """
    Loads an embed URL in headless Chromium and intercepts the
    internal getSources response body using Playwright route interception.

    Returns the raw JSON body string, or None if not found.
    """
    # Bootstrap venv site-packages FIRST so playwright import succeeds
    # when running from system Python (e.g. `python3 orchestrator.py`)
    if not _bootstrap_venv():
        return None

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error(
            "[Playwright] playwright not importable even after venv bootstrap. "
            "Run: ./venv/bin/pip install playwright && ./venv/bin/playwright install chromium"
        )
        return None

    captured = {"body": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        sources_event = asyncio.Event()

        async def intercept_route(route):
            req_url = route.request.url
            if any(kw in req_url for kw in SOURCE_KEYWORDS):
                logger.debug(f"[Playwright] Intercepted: {req_url}")
                try:
                    response = await route.fetch()
                    body = await response.text()
                    captured["body"] = body
                    sources_event.set()
                    await route.fulfill(response=response)
                except Exception as e:
                    logger.warning(f"[Playwright] Route fetch error: {e}")
                    sources_event.set()
                    await route.continue_()
            elif ".m3u8" in req_url:
                logger.debug(f"[Playwright] Intercepted m3u8 directly: {req_url}")
                captured["body"] = json.dumps({"sources": [{"file": req_url}]})
                sources_event.set()
                await route.continue_()
            else:
                await route.continue_()

        await page.route("**/*", intercept_route)

        try:
            try:
                await page.goto(embed_url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                logger.warning(f"[Playwright] Embed navigation warning/timeout (continuing anyway): {e}")
            
            # Fast-fail if the page title indicates an error (e.g. MegaPlay Error)
            try:
                title = await page.title()
                if "Error" in title or "404" in title or "Suspended" in title:
                    await browser.close()
                    return None
            except Exception:
                pass
                
            try:
                await page.click('button[aria-label="Play video"], .play-button, .vjs-big-play-button, .plyr__control--overlaid, #play-button, video', timeout=3000, force=True)
            except Exception:
                try:
                    viewport = page.viewport_size
                    if viewport:
                        await page.mouse.click(viewport['width'] / 2, viewport['height'] / 2)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            await asyncio.wait_for(sources_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(f"[Playwright] Timeout waiting for stream sources to appear on: {embed_url}")

        await browser.close()

    return captured["body"]


def intercept_embed_sync(embed_url: str) -> Optional[str]:
    """Synchronous wrapper around the async Playwright interceptor."""
    try:
        return asyncio.run(_intercept_embed(embed_url))
    except RuntimeError:
        # If already inside an event loop (e.g. Jupyter), use nest_asyncio
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_intercept_embed(embed_url))


def parse_sources(body: str) -> Dict[str, Any]:
    """
    Parses the intercepted getSources JSON body and extracts:
      - m3u8_url: the raw HLS stream URL
      - subtitles: list of subtitle track dicts  {'url', 'label'}
      - referer: the CDN origin needed for downloading
      - intro / outro timestamps (for skip markers)
    """
    result = {
        "m3u8_url": None,
        "subtitles": [],
        "referer": None,
        "intro": None,
        "outro": None,
    }

    try:
        data = json.loads(body)
    except Exception:
        logger.error(f"[Playwright] Could not parse JSON: {body[:200]}")
        return result

    sources = data.get("sources", [])

    # Case A: dict with a single "file" key  {"file": "...m3u8"}
    if isinstance(sources, dict):
        result["m3u8_url"] = sources.get("file") or sources.get("url")

    # Case B: list of source dicts
    elif isinstance(sources, list) and sources:
        for s in sources:
            url = s.get("file") or s.get("src") or s.get("url", "")
            if url and ".m3u8" in url:
                result["m3u8_url"] = url
                break

    # Case C: encrypted base64 string (uncommon on vidtube, log it)
    elif isinstance(sources, str):
        logger.warning(f"[Playwright] Sources appear AES-encrypted (len={len(sources)})")

    # Subtitle tracks
    for track in data.get("tracks", []):
        file_url = track.get("file", "")
        label = track.get("label", "Unknown")
        kind = track.get("kind", "")
        if file_url and kind in ("captions", "subtitles"):
            result["subtitles"].append({"url": file_url, "label": label})

    # Timing markers
    result["intro"] = data.get("intro")
    result["outro"] = data.get("outro")

    return result


def get_stream(embed_url: str) -> Dict[str, Any]:
    """
    High-level entry point.
    Given an embed URL (e.g. vidtube.site/stream/.../sub), returns:
      {
        "m3u8_url": "https://...",
        "subtitles": [...],
        "referer": "https://vidtube.site/",
        "intro": {...},
        "outro": {...},
      }
    Returns empty dict on failure.
    """
    from urllib.parse import urlparse
    referer = f"{urlparse(embed_url).scheme}://{urlparse(embed_url).netloc}/"

    body = intercept_embed_sync(embed_url)
    if not body:
        return {}

    result = parse_sources(body)
    result["referer"] = referer
    return result
