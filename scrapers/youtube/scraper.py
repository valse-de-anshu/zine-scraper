import logging
from typing import Dict, Any, List, Tuple, Optional
from .engine import YoutubeEngine

logger = logging.getLogger(__name__)

class YoutubeScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        self.engine = YoutubeEngine()
        self.is_playlist = False
        
    def get_link_type(self) -> str:
        """
        Identifies the type of YouTube link.
        Returns 'channel', 'playlist', or 'single'.
        """
        url_lower = self.url.lower()
        if "/@" in url_lower or "/channel/" in url_lower or "/c/" in url_lower or "/user/" in url_lower:
            return "channel"
        if "list=" in url_lower:
            return "playlist"
        return "single"

    def _scrape_single_video_metadata(self, url: str) -> Dict[str, Any]:
        """Fast-path streaming HTTP metadata scraper for single YouTube watch links."""
        import requests
        import re
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, stream=True, timeout=10)
        if r.status_code != 200:
            raise Exception("Failed to fetch YouTube page")
            
        title, author, thumb, video_id, upload_date = None, None, None, None, None
        html_chunks = []
        for chunk in r.iter_content(chunk_size=8192, decode_unicode=True):
            if not chunk:
                break
            html_chunks.append(chunk)
            html_so_far = "".join(html_chunks)
            
            if not title:
                m = re.search(r'<meta name="title"\s+content="([^"]+)"', html_so_far) or re.search(r'<title>([^<]+)</title>', html_so_far)
                if m: title = m.group(1)
            if not author:
                m = re.search(r'<link itemprop="name"\s+content="([^"]+)"', html_so_far) or re.search(r'"author"\s*:\s*"([^"]+)"', html_so_far)
                if m: author = m.group(1)
            if not thumb:
                m = re.search(r'<link itemprop="thumbnailUrl"\s+href="([^"]+)"', html_so_far) or re.search(r'<meta property="og:image"\s+content="([^"]+)"', html_so_far)
                if m: thumb = m.group(1)
            if not video_id:
                m = re.search(r'"videoId"\s*:\s*"([^"]+)"', html_so_far)
                if m: video_id = m.group(1)
            if not upload_date:
                m = re.search(r'itemprop="datePublished"\s+content="([^"T]+)', html_so_far)
                if m: upload_date = m.group(1)
                
            if title and author and thumb and video_id and upload_date:
                break
                
        r.close()
        if not video_id:
            video_id = url.split("/")[-1].split("?")[0].split("v=")[-1]
            
        return {
            "id": video_id,
            "title": title or "Unknown Video",
            "uploader": author or "Unknown Uploader",
            "thumbnail": thumb or "",
            "thumbnails": [{"url": thumb or ""}],
            "upload_date": upload_date,
            "extractor_key": "Youtube",
            "_type": "video",
            "entries": []
        }

    def get_metadata_and_videos(self, playlist_limit: Optional[int] = None, playlist_start: Optional[int] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Fetches channel/playlist metadata and the list of videos.
        Returns (metadata, videos, raw_info).
        """
        link_type = self.get_link_type()
        if link_type == "single":
            try:
                info = self._scrape_single_video_metadata(self.url)
                self.is_playlist = False
            except Exception:
                info = self.engine.extract_video_info(self.url, fast=True)
                self.is_playlist = False
        else:
            # If it's a channel root URL, append /videos so yt-dlp gets videos instead of playlists
            if "/@" in self.url and not any(sub in self.url.lower() for sub in ["/videos", "/shorts", "/streams", "/playlists", "list="]):
                self.url = self.url.rstrip("/") + "/videos"
                
            info = self.engine.extract_playlist_info(self.url, playlist_limit=playlist_limit, playlist_start=playlist_start)
            
            # Handle redirects/shortlinks
            if info.get('_type') == 'url' or info.get('_type') is None:
                 redirect_url = info.get('url') or ""
                 if "list=" in redirect_url.lower() or "list=" in self.url.lower():
                      target_url = redirect_url if "list=" in redirect_url.lower() else self.url
                      info = self.engine.extract_playlist_info(target_url, playlist_limit=playlist_limit, playlist_start=playlist_start)
                 else:
                      try:
                          info = self._scrape_single_video_metadata(self.url)
                      except Exception:
                          info = self.engine.extract_video_info(self.url, fast=True)
                 
            self.is_playlist = info.get('_type') == 'playlist'
            
            # If it's a single video and we didn't just extract full info, do it now
            if not self.is_playlist and info.get('_type') != 'playlist':
                 try:
                     info = self._scrape_single_video_metadata(self.url)
                 except Exception:
                     info = self.engine.extract_video_info(self.url, fast=True)
        
        # Prioritize avatar (uploader_url or channel_id/avatar)
        # yt-dlp usually provides 'thumbnails' which might include banners.
        # We try to find a square-ish thumbnail or the uploader's avatar.
        avatar_url = None
        if info.get('thumbnails'):
             # Look for the last thumbnail which is usually high res, 
             # but try to avoid wide banners (width/height ratio > 1.5)
             for thumb in reversed(info['thumbnails']):
                 w = thumb.get('width', 0)
                 h = thumb.get('height', 1)
                 if w > 0 and (w / h) < 1.5:
                     avatar_url = thumb.get('url')
                     break
             if not avatar_url:
                 avatar_url = info['thumbnails'][-1].get('url')

        channel_name = info.get('uploader') or info.get('channel') or info.get('title') or "Unknown"
        metadata = {
            "Channel/Series": channel_name,
            "Source": info.get('extractor_key') or "Unknown",
            "Total Videos": len(info.get('entries', [])) if self.is_playlist else 1,
            "ID": info.get('uploader_id') or info.get('channel_id') or info.get('id') or "Unknown",
            "Thumbnail": avatar_url
        }
        if self.is_playlist and self.get_link_type() == "playlist":
            metadata["Playlist"] = info.get('title') or "Unknown"
        
        videos = []
        if self.is_playlist:
            entries = info.get('entries', [])
            for idx, entry in enumerate(entries):
                if entry:
                    track_thumb = entry.get('thumbnail')
                    if not track_thumb and entry.get('thumbnails'):
                        track_thumb = entry['thumbnails'][-1].get('url')

                    # Enforce fully qualified absolute YouTube URL using ID
                    vid_id = entry.get('id')
                    raw_url = entry.get('url') or entry.get('webpage_url')
                    if vid_id:
                        video_url = f"https://www.youtube.com/watch?v={vid_id}"
                    else:
                        video_url = raw_url or ""

                    videos.append({
                        "url": video_url,
                        "raw_url": str(raw_url),
                        "title": entry.get('title', f"Video {idx+1}"),
                        "id": vid_id or str(idx),
                        "uploader": entry.get('uploader') or entry.get('channel') or channel_name,
                        "thumbnail": track_thumb
                    })
        else:
            track_thumb = info.get('thumbnail')
            if not track_thumb and info.get('thumbnails'):
                track_thumb = info['thumbnails'][-1].get('url')

            videos.append({
                "url": info.get('webpage_url') or info.get('original_url') or self.url,
                "title": info.get('title', "Unknown"),
                "id": info.get('id', "Unknown"),
                "uploader": info.get('uploader') or info.get('channel') or channel_name,
                "thumbnail": track_thumb,
                "upload_date": info.get('upload_date')
            })
            
        return metadata, videos, info
