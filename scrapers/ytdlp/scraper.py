import logging
from typing import Dict, Any, List, Tuple
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

class YtDlpScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        self.engine = VideoEngine()
        self.is_playlist = False
        
    def get_metadata_and_videos(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        # Try flat first to check if it's a playlist/channel
        info = self.engine.extract_playlist_info(self.url)
        
        # Handle redirects/shortlinks
        if info.get('_type') == 'url' or info.get('_type') is None:
             info = self.engine.extract_video_info(self.url)
             
        self.is_playlist = info.get('_type') == 'playlist'
        
        # If it's a single video and we didn't just extract full info, do it now
        if not self.is_playlist and info.get('_type') != 'playlist':
             info = self.engine.extract_video_info(self.url)
        
        channel_name = info.get('uploader') or info.get('channel') or info.get('title') or "Unknown"
        metadata = {
            "Channel/Series": channel_name,
            "Source": info.get('extractor_key') or "Unknown",
            "Total Videos": len(info.get('entries', [])) if self.is_playlist else 1,
            "ID": info.get('uploader_id') or info.get('channel_id') or info.get('id') or "Unknown",
            "Thumbnail": info.get('thumbnail') or (info.get('thumbnails', [{}])[-1].get('url') if info.get('thumbnails') else None)
        }

        videos = []
        if self.is_playlist:
            entries = info.get('entries', [])
            for idx, entry in enumerate(entries):
                if entry:
                    track_thumb = entry.get('thumbnail')
                    if not track_thumb and entry.get('thumbnails'):
                        track_thumb = entry['thumbnails'][-1].get('url')

                    videos.append({
                        "url": entry.get('url') or entry.get('webpage_url'),
                        "title": entry.get('title', f"Video {idx+1}"),
                        "id": entry.get('id', str(idx)),
                        "upload_date": entry.get('uploader') or entry.get('channel') or channel_name,
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
                "upload_date": info.get('uploader') or info.get('channel') or channel_name,
                "thumbnail": track_thumb
            })
            
        return metadata, videos, info
