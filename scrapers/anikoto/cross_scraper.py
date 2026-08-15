import logging
import requests
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional, Callable

logger = logging.getLogger(__name__)

def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def fallback_cross_scraper(
    failed_title: str, 
    failed_episode: int, 
    folder: Path, 
    stats_callback: Callable, 
    progress_data: Optional[dict] = None
) -> bool:
    """
    Called when a scraper completely fails (all domains/chunks dead).
    Creates a 'web' to search alternative sources (Anikoto) for the specific anime
    and seamlessly routes the download without breaking the batch orchestrator loop.
    """
    pass
    
    if progress_data:
        progress_data["status"] = "Web Fallback: Searching Anikoto..."
    
    import re
    clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', failed_title).strip()
    search_url = f"https://anikototv.to/search?keyword={quote_plus(clean_title)}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        r = requests.get(search_url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')
        
        links = soup.select('a')
        best_match = None
        best_score = 0.0
        
        for link in links:
            title = link.text.strip()
            href = link.get('href', '')
            if '/watch/' in href:
                score = _similar(failed_title, title)
                if score > best_score:
                    best_score = score
                    best_match = href
                    
        if best_match and best_score > 0.7:
            if best_match.startswith('http'):
                base_url = best_match
            else:
                base_url = f"https://anikototv.to{best_match}"
                
            if '/ep-' in base_url:
                base_url = base_url.split('/ep-')[0]
                
            new_url = f"{base_url}/ep-{failed_episode}"
            pass
            
            if progress_data:
                progress_data["status"] = "Web Fallback: Found on Anikoto"
            
            # Dynamically load Anikoto scraper to rip the video
            from scrapers.anikoto.scraper import AnikotoScraper
            scraper = AnikotoScraper(new_url)
            meta, videos, info = scraper.get_metadata_and_videos()
            
            # Find the episode object that matches our target
            target_video = None
            for v in videos:
                if str(failed_episode) in v.get('title', '') or f"ep-{failed_episode}" in v.get('url', ''):
                    target_video = v
                    break
                    
            if not target_video:
                # If we couldn't match exactly by list, construct a dummy video object to pass to the extractor
                target_video = {
                    "url": new_url, 
                    "title": f"Ep {failed_episode} - {failed_title}", 
                    "data_ids": videos[-1].get("data_ids", "") if videos else ""
                }
                
            if progress_data:
                progress_data["status"] = "Web Fallback: Resolving stream..."
            
            stream_info = scraper.resolve_episode_stream(target_video)
            if stream_info and stream_info.get("m3u8_url"):
                raw_stream = stream_info["m3u8_url"]
                referer = stream_info.get("referer")
                
                if referer:
                    scraper.engine.headers["Referer"] = referer
                    scraper.engine.headers["Origin"] = referer.rstrip("/")
                    
                if progress_data:
                    progress_data["status"] = "Web Fallback: Downloading..."
                    
                success = scraper.engine.download_video(
                    new_url, folder, stats_callback,
                    raw_stream_url=raw_stream,
                    is_audio=False,
                    custom_thumbnail=None,
                    fixed_title=target_video.get("title", f"Ep {failed_episode} - {failed_title}"),
                    fixed_artist=None,
                    format_override="best[ext=mp4]/best",
                )
                
                if success:
                    pass
                return success
            else:
                pass
                
    except Exception as e:
        pass
        
    pass
    if progress_data:
        progress_data["status"] = "Web Fallback Failed"
    return False
