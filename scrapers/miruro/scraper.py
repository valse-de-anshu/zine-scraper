"""
scrapers/miruro/scraper.py
----------------------------
Miruro scraper — supports miruro.to, miruro.ru, miruro.tv, miruro.bz

Pipeline:
  1. Extract Anilist ID from the URL.
  2. Fetch metadata from Miruro SSR payload (primary) or Anilist GraphQL API (fallback).
  3. Generate episode URLs for the whole series.
  4. During extraction, rewrite URL to miruro.ru to bypass Cloudflare timeouts.
  5. Use Playwright (via venv subprocess) to extract the stream.
"""

import logging
import os
import re
import json
import subprocess
from urllib.parse import urlparse
from typing import Dict, Any, List, Tuple, Optional
from core.video_engine import VideoEngine
from pathlib import Path

logger = logging.getLogger(__name__)

def _normalize_host(url: str) -> str:
    """Return the Miruro host from any supported variant."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"

class MiruroScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        self._host = _normalize_host(url)
        self.engine = VideoEngine()
        
        self.project_root = Path(__file__).parent.parent.parent
        if os.name == 'nt':
            self.venv_python = self.project_root / "venv" / "Scripts" / "python.exe"
        else:
            self.venv_python = self.project_root / "venv" / "bin" / "python"

    def _fetch_from_ssr_page(self, anilist_id: int) -> Optional[Dict[str, Any]]:
        """Attempts to fetch metadata directly from Miruro's page HTML/SSR payload."""
        try:
            try:
                from curl_cffi import requests as cffi_requests
                r = cffi_requests.get(self.url, impersonate="chrome120", timeout=12)
            except Exception:
                import requests
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
                r = requests.get(self.url, headers=headers, timeout=12)

            if r.status_code == 200:
                match = re.search(r'window\.__SSR_DATA__\s*=\s*(\{.+?\})(?:;|\s*</script>)', r.text)
                if match:
                    return json.loads(match.group(1))

                # Fallback to OpenGraph meta tags
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, 'html.parser')
                og_title = soup.find('meta', property='og:title') or soup.find('title')
                og_image = soup.find('meta', property='og:image')
                og_desc = soup.find('meta', property='og:description')

                title_text = og_title.get('content') if og_title and og_title.get('content') else (og_title.text if og_title else None)
                if title_text:
                    return {
                        "id": anilist_id,
                        "title": {"romaji": title_text, "english": title_text},
                        "coverImage": {"large": og_image.get('content') if og_image else f"https://img.anili.st/media/{anilist_id}"},
                        "description": og_desc.get('content', '') if og_desc else '',
                        "episodes": 1,
                        "genres": []
                    }
        except Exception as e:
            logger.debug(f"[Miruro] SSR direct fetch failed: {e}")

        # Fallback to Playwright SSR extractor if direct HTTP was blocked
        try:
            ssr_script = Path(__file__).parent / "ssr_extractor.py"
            if ssr_script.exists() and self.venv_python.exists():
                cmd = [str(self.venv_python), str(ssr_script), self.url]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
                for line in proc.stdout.splitlines():
                    if line.startswith("JSON_RESULT:"):
                        return json.loads(line.split("JSON_RESULT:", 1)[1])
        except Exception as e:
            logger.debug(f"[Miruro] Playwright SSR extraction failed: {e}")

        return None

    def _fetch_from_anilist(self, anilist_id: int) -> Optional[Dict[str, Any]]:
        """Fallback to AniList GraphQL API if available."""
        query = '''
        query ($id: Int) {
          Media(id: $id, type: ANIME) {
            id
            title { romaji english native }
            coverImage { large }
            description
            episodes
            genres
          }
        }
        '''
        try:
            import requests
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            r = requests.post(
                'https://graphql.anilist.co',
                json={'query': query, 'variables': {'id': anilist_id}},
                headers=headers,
                timeout=8
            )
            if r.status_code == 200:
                return r.json().get('data', {}).get('Media', {})
        except Exception as e:
            logger.debug(f"[Miruro] AniList GraphQL API error: {e}")
        return None

    def get_metadata_and_videos(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        # 1. Extract Anilist ID
        match = re.search(r'/(?:watch|info)/(\d+)', self.url)
        if not match:
            raise ValueError(f"Could not extract Anilist ID from {self.url}")
        anilist_id = int(match.group(1))

        # 2. Fetch metadata: Miruro SSR (primary) -> AniList GraphQL (fallback)
        data = self._fetch_from_ssr_page(anilist_id)
        if not data:
            data = self._fetch_from_anilist(anilist_id)

        if not data:
            # Generate fallback metadata from URL slug if all external services are unreachable
            slug_match = re.search(r'/(?:watch|info)/\d+/([^/?#]+)', self.url)
            slug_title = slug_match.group(1).replace("-", " ").title() if slug_match else f"Anime {anilist_id}"
            data = {
                "id": anilist_id,
                "title": {"romaji": slug_title, "english": slug_title},
                "coverImage": {"large": f"https://img.anili.st/media/{anilist_id}"},
                "description": "Metadata retrieved via Miruro fallback.",
                "episodes": 1,
                "genres": []
            }

        title_obj = data.get('title', {})
        title = title_obj.get('english') or title_obj.get('romaji') or title_obj.get('native') or f"Anime {anilist_id}"
        cover = data.get('coverImage', {}).get('large') or f"https://img.anili.st/media/{anilist_id}"
        status = data.get('status', 'FINISHED')
        total_episodes = data.get('episodes') or 1
        
        metadata = {
            "Channel/Series": title,
            "Source": "Miruro",
            "Genres": ", ".join(genres) if genres else "Unknown",
            "Description": synopsis,
            "Thumbnail": cover,
            "ID": str(anilist_id),
            "Status": status.replace("_", " ").title() if status else "Finished",
            "Total Videos": total_episodes
        }

        # 3. Generate episodes
        base_url = self.url.split('?ep=')[0]
        if "/info/" in base_url:
            base_url = base_url.replace("/info/", "/watch/")
            
        videos = []
        for i in range(1, total_episodes + 1):
            ep_url = f"{base_url}?ep={i}"
            videos.append({
                "url": ep_url,
                "title": f"Ep {i} - {title}",
                "id": f"{anilist_id}_ep{i}",
                "data_ids": "",
                "upload_date": 'UnknownDate',
            })

        info = {
            "id": str(anilist_id),
            "title": title,
            "description": synopsis,
            "thumbnail": cover,
        }

        return metadata, videos, info

    def resolve_episode_stream(self, episode: Dict[str, Any], force_domain: Optional[str] = None) -> Optional[Dict[str, Any]]:
        watch_url = episode.get("url", self.url)
        
        parsed = urlparse(watch_url)
        if force_domain:
            watch_url = watch_url.replace(parsed.netloc, force_domain)
        elif parsed.netloc not in ["www.miruro.ru", "www.miruro.tv", "www.miruro.to", "www.miruro.bz", "miruro.ru", "miruro.tv", "miruro.to", "miruro.bz"]:
            # Fallback to miruro.ru if the domain is completely unknown
            watch_url = watch_url.replace(parsed.netloc, "www.miruro.ru")
        
        current_domain = urlparse(watch_url).netloc
        logger.info(f"[Miruro] Resolving stream for {watch_url}")

        try:
            extractor_script = self.project_root / "scrapers" / "playwright_extractor.py"
            cmd = [str(self.venv_python), str(extractor_script), watch_url]
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
            
            if process.returncode != 0:
                logger.error(f"[Miruro] Playwright extractor failed with exit code {process.returncode}")
                if process.stderr:
                    logger.error(f"[Miruro] Playwright stderr: {process.stderr.strip()}")
            
            result = None
            for line in process.stdout.splitlines():
                if line.startswith("JSON_RESULT:"):
                    result = json.loads(line.split("JSON_RESULT:", 1)[1])
                    break
                    
            if result and result.get("url"):
                logger.info(f"[Miruro] Stream resolved: {result['url'][:60]}...")
                return {
                    "m3u8_url": result["url"],
                    "referer": f"https://{current_domain}/",
                    "subtitles": result.get("subtitles", []),
                    "qualities": result.get("qualities_urls", [])
                }
            else:
                logger.error(f"[Miruro] Failed to extract stream URL. Playwright stdout: {process.stdout.strip()}")
        except Exception as e:
            logger.error(f"[Miruro] Playwright execution error: {e}", exc_info=True)

        return None
