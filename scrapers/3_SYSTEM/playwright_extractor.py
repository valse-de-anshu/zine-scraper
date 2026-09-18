import asyncio
import sys
import json
import glob
from pathlib import Path

def _bootstrap_venv():
    try:
        import playwright
        return True
    except ImportError:
        pass

    search_root = Path(__file__).resolve().parent
    for _ in range(4):
        if (search_root / "orchestrator.py").exists() or (search_root / "main.py").exists():
            break
        search_root = search_root.parent

    for venv_name in ["venv", ".venv", "env", ".env"]:
        venv_path = search_root / venv_name
        if not venv_path.is_dir():
            continue
        import os
        if os.name == "nt":
            site_pkgs = glob.glob(str(venv_path / "Lib" / "site-packages"))
        else:
            site_pkgs = glob.glob(str(venv_path / "lib" / "python*" / "site-packages"))
        for sp in site_pkgs:
            if sp not in sys.path:
                sys.path.insert(0, sp)
    try:
        import playwright
        return True
    except ImportError:
        return False

_bootstrap_venv()

# Setup root path dynamic imports
search_root = Path(__file__).resolve().parent
for _ in range(4):
    if (search_root / "orchestrator.py").exists() or (search_root / "main.py").exists():
        break
    search_root = search_root.parent
if str(search_root) not in sys.path:
    sys.path.insert(0, str(search_root))

import logging
from datetime import datetime
from core.paths import PathAuthority

paths = PathAuthority()
log_dir = paths.get_library_temp_root()
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / f"scraper_{datetime.now().strftime('%Y-%m-%d')}.log"

logger = logging.getLogger("playwright_extractor")
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(log_file, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(handler)

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
async def extract_stream(url):
    logger.info(f"Playwright Extractor starting for: {url}")
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        stream_url = None
        subtitles = []
        qualities_urls = []
        
        async def on_response(response):
            nonlocal stream_url
            u = response.url
            # Subtitle detection: catch .vtt/.srt URLs (including sub.vtt style paths)
            if (".vtt" in u or ".srt" in u or "sub.vtt" in u) and not any(x in u for x in ["adtng", "doubleclick", "/ads/", "analytics", "ping.gif", "sprite", "thumb"]):
                lang_label = "English"
                if "jpn" in u.lower() or "ja." in u.lower() or "japanese" in u.lower():
                    lang_label = "Japanese"
                elif "por" in u.lower() or "pt." in u.lower():
                    lang_label = "Portuguese"
                elif "spa" in u.lower() or "es." in u.lower():
                    lang_label = "Spanish"
                entry = {"url": u, "label": lang_label}
                if entry not in subtitles:
                    subtitles.append(entry)
                    logger.info(f"[Playwright] Intercepted subtitle VTT/SRT request: {u} (detected language: {lang_label})")
            
            # Intercept Miruro's secure API sources response — contains subtitle tracks as JSON
            if "secure/pipe" in u and "sources" in u:
                try:
                    logger.info(f"[Playwright] Intercepted secure/pipe request: {u}")
                    body = await response.json()
                    tracks = body.get("subtitles", []) or body.get("tracks", []) or body.get("captions", [])
                    logger.info(f"[Playwright] secure/pipe JSON contains {len(tracks)} subtitle tracks")
                    for track in tracks:
                        sub_url = track.get("url", "")
                        if not sub_url:
                            continue
                        lang = track.get("lang") or track.get("label") or "English"
                        entry = {"url": sub_url, "label": lang}
                        if entry not in subtitles:
                            subtitles.append(entry)
                            logger.info(f"[Playwright] Extracted subtitle track from secure/pipe: {lang} -> {sub_url}")
                except Exception as e:
                    logger.error(f"[Playwright] Failed to parse secure/pipe payload: {e}")
            
            if (".m3u8" in u or "videoplayback" in u or ".mp4" in u or "hanime.tv/hls/" in u) and ".gif" not in u.lower():
                if "hls/stream.m3u8" not in u and "/ads/" not in u and "adtng" not in u and "dreamserve" not in u: # ignore dead ones and ads
                    if not stream_url:
                        stream_url = u
                        logger.info(f"[Playwright] Intercepted video stream URL: {u}")
                    if u not in qualities_urls:
                        qualities_urls.append(u)
                        logger.info(f"[Playwright] Added stream quality option: {u}")
            
            # Special case for JWPlayer pings which contain the real URL in 'mu' parameter
            if "jwpltx.com" in u and "mu=" in u:
                import urllib.parse
                parsed = urllib.parse.urlparse(u)
                qs = urllib.parse.parse_qs(parsed.query)
                if "mu" in qs:
                    real_mp4 = qs["mu"][0]
                    should_replace = not stream_url
                    if stream_url:
                        if isinstance(stream_url, list):
                            should_replace = "ping.gif" in stream_url[0]
                        else:
                            should_replace = "ping.gif" in stream_url
                    
                    if should_replace:
                        stream_url = real_mp4
                    if real_mp4 not in qualities_urls:
                        qualities_urls.append(real_mp4)
                
        page.on("response", on_response)
        
        try:
            logger.info(f"[Playwright] Navigating browser to: {url}")
            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                logger.info(f"[Playwright] Page navigation loaded. Current URL: {page.url}")
            except Exception as e:
                logger.warning(f"[Playwright] page.goto warning/timeout (continuing anyway): {e}")
            # Wait for React hydration — 1.5s is enough for miruro.bz
            await page.wait_for_timeout(1500)

            # Click the video element directly — this is what triggers the player
            # on miruro.bz without needing a specific button selector
            try:
                logger.info(f"[Playwright] Attempting to click direct 'video' element...")
                await page.click('video', timeout=2000, force=True)
                logger.info(f"[Playwright] Successfully clicked direct 'video' element.")
            except Exception:
                logger.info(f"[Playwright] Direct video click failed, attempting play buttons...")
                # Fallback: try common play button selectors
                for sel in ['button[aria-label="Play"]', '.jw-icon-display', '[class*="play"]', '.vjs-big-play-button', '.plyr__control--overlaid', '#play-button']:
                    try:
                        await page.click(sel, timeout=800, force=True)
                        logger.info(f"[Playwright] Clicked play button selector: {sel}")
                        break
                    except Exception:
                        continue

            logger.info(f"[Playwright] Waiting for video stream URL to resolve...")
            # Poll for up to 12 seconds for the m3u8 to appear (was 30s)
            for _ in range(24):
                if stream_url:
                    break
                await page.wait_for_timeout(500)
            
            if stream_url:
                logger.info(f"[Playwright] Video stream resolved successfully. Waiting for subtitle tracks to fire...")
                # Once stream is found, wait up to 10s for subtitle tracks to fire dynamically
                for _ in range(20):
                    if subtitles:
                        break
                    await page.wait_for_timeout(500)
            else:
                logger.warning(f"[Playwright] Stream URL failed to resolve in time.")
        except KeyboardInterrupt:
            logger.warning(f"[Playwright] KeyboardInterrupt during page loading/waiting.")
            return {"url": None, "title": "Cancelled", "subtitles": [], "qualities_urls": []}
        except Exception as e:
            logger.error(f"[Playwright] Exception during wait/extraction: {e}", exc_info=True)
            
        try:
            title = await page.title()
            html = await page.content()
        except Exception as e:
            logger.warning(f"[Playwright] Failed to capture page content/title: {e}")
            title = "Unknown"
            html = ""

        logger.info(f"[Playwright] Finished execution. Resolved URL: {stream_url is not None}, Subtitles captured: {len(subtitles)}")
        await browser.close()
        return {"url": stream_url, "title": title, "subtitles": subtitles, "qualities_urls": qualities_urls, "html": html}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    url = sys.argv[1]
    result = asyncio.run(extract_stream(url))
    if result:
        print("JSON_RESULT:" + json.dumps(result))
        if not result.get("url"):
            sys.exit(1)
    else:
        print("FAILED: No result returned")
        sys.exit(1)
