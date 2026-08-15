import logging
from typing import Dict, Any, List, Tuple
from .engine import IdagioEngine

logger = logging.getLogger(__name__)

class IdagioScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "music"
        self.engine = IdagioEngine()

    def get_metadata_and_videos(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Fetches Idagio album/playlist/track metadata and the list of entries.
        Returns (metadata, videos, raw_info).
        """
        # For Idagio, we use extract_video_info (full extraction) because 
        # extract_flat: True (in extract_playlist_info) misses track titles.
        info = self.engine.extract_video_info(self.url)
             
        is_playlist = info.get('_type') == 'playlist'
        
        # Artist extraction
        # Idagio usually provides 'artist' or 'artists'
        artist = info.get('artist') or info.get('uploader')
        if not artist and info.get('artists'):
            artist = ", ".join(info['artists'])
        if not artist:
            artist = "Unknown Artist"

        # Thumbnail extraction
        thumbnail = info.get('thumbnail')
        if not thumbnail and info.get('thumbnails'):
            thumbnail = info['thumbnails'][-1].get('url')

        metadata = {
            "Channel/Series": info.get('title') or "Unknown Idagio Content",
            "Source": "Idagio",
            "Total Videos": len(info.get('entries', [])) if is_playlist else 1,
            "ID": info.get('id') or "Unknown",
            "Thumbnail": thumbnail
        }
        
        videos = []
        if is_playlist:
            entries = info.get('entries', [])
            for idx, entry in enumerate(entries):
                if entry:
                    track_thumb = entry.get('thumbnail')
                    if not track_thumb and entry.get('thumbnails'):
                        track_thumb = entry['thumbnails'][-1].get('url')
                    
                    # For music, we store the artist in 'upload_date' field 
                    # as per orchestrator.py's process_video implementation for music type.
                    track_artist = entry.get('artist') or entry.get('uploader') or artist

                    videos.append({
                        "url": entry.get('webpage_url') or entry.get('url'),
                        "title": entry.get('title', f"Track {idx+1}"),
                        "id": entry.get('id', str(idx)),
                        "upload_date": track_artist,
                        "thumbnail": track_thumb or thumbnail
                    })
        else:
            videos.append({
                "url": info.get('webpage_url') or self.url,
                "title": info.get('title', "Unknown Track"),
                "id": info.get('id', "Unknown"),
                "upload_date": artist,
                "thumbnail": thumbnail
            })
            
        return metadata, videos, info
