import logging
from typing import Dict, Any, List, Tuple
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

class SoundcloudScraper:
    def __init__(self, url: str):
        # Strip the ?in= context parameter from single tracks inside a playlist
        if "?in=" in url:
            url = url.split("?in=")[0]
            
        # Reject playlists gracefully by flagging them for the TUI
        self.is_banned_playlist = False
        if "/sets/" in url.split("?")[0]:
            self.is_banned_playlist = True
            
        self.url = url
        self.scraper_type = "music"
        self.engine = VideoEngine()
        self.is_playlist = False
        
    def get_metadata_and_videos(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        info = self.engine.extract_video_info(self.url)
        if not info:
            raise RuntimeError("Could not extract metadata. This usually means the track is a SoundCloud GO+ premium track (DRM protected), geoblocked, or deleted!")
            
        user_dict = info.get('user') or {}
        channel_name = info.get('uploader') or user_dict.get('username') or info.get('title') or "SoundCloud Artist"
        metadata = {
            "Channel/Series": channel_name,
            "Source": "SoundCloud",
            "Total Videos": 1,
            "ID": info.get('uploader_id') or info.get('id', "Unknown")
        }
        
        track_thumb = info.get('thumbnail')
        if not track_thumb and info.get('thumbnails'):
            track_thumb = info['thumbnails'][-1].get('url')

        videos = [{
            "url": info.get('webpage_url') or info.get('original_url') or self.url,
            "title": info.get('title', "SoundCloud Track"),
            "id": info.get('id', "Unknown"),
            "upload_date": info.get('uploader') or info.get('user', {}).get('username') or channel_name,
            "thumbnail": track_thumb
        }]
            
        return metadata, videos, info
