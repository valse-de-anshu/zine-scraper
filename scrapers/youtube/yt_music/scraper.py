import logging
import re
import requests
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, List, Tuple, Optional
from .engine import YoutubeMusicEngine

logger = logging.getLogger(__name__)

class YoutubeMusicScraper:
    """
    Isolated scraper for YouTube Music (music.youtube.com).
    Handles single tracks, albums, playlists, and artist discographies.
    """

    def __init__(self, url: str):
        self.raw_url = url
        self.url = self._normalize_music_url(url)
        self.scraper_type = "music"
        self.engine = YoutubeMusicEngine()
        self.is_playlist = False

    def _normalize_music_url(self, url: str) -> str:
        """Cleans and standardizes YouTube Music URLs."""
        url = url.strip()
        parsed = urlparse(url)
        
        # If it's a watch link with an auto-generated radio list (list=RD...), clean it to single track
        if "/watch" in parsed.path:
            qs = parse_qs(parsed.query)
            vid_id = qs.get("v", [None])[0]
            list_id = qs.get("list", [None])[0]
            
            # If it has a true playlist/album list ID (PL... or OLAK5uy...), keep it
            if list_id and (list_id.startswith("PL") or list_id.startswith("OLAK5uy")):
                pass
            elif vid_id:
                # Strip radio/mix context (list=RD...) to isolate single song
                return f"https://music.youtube.com/watch?v={vid_id}"

        # Standardize browse album links
        if "/browse/VL" in parsed.path:
            album_id = parsed.path.split("/browse/VL")[-1]
            return f"https://music.youtube.com/playlist?list={album_id}"

        return url

    def get_link_type(self) -> str:
        """
        Identifies whether the link is a single track, playlist/album, or artist.
        Returns 'single', 'playlist', 'album', or 'artist'.
        """
        url_lower = self.url.lower()
        if "/channel/" in url_lower or "/artist/" in url_lower:
            return "artist"
        if "list=olak5uy" in url_lower or "/album/" in url_lower:
            return "album"
        if "list=" in url_lower or "/playlist" in url_lower:
            return "playlist"
        return "single"

    def _clean_artist_name(self, raw_artist: Optional[str]) -> str:
        """Removes YouTube auto-generated '- Topic' suffix and cleans placeholder names."""
        if not raw_artist:
            return ""
        cleaned = raw_artist.strip()
        if cleaned.endswith(" - Topic"):
            cleaned = cleaned[:-8].strip()
        if cleaned.lower() in ["youtube music", "various artists - topic"]:
            return ""
        return cleaned

    def _clean_album_title(self, raw_title: Optional[str]) -> str:
        """Removes 'Album - ' or 'Playlist - ' prefixes added by YouTube Music."""
        if not raw_title:
            return "YouTube Music"
        cleaned = re.sub(r'^(Album|Playlist|EP|Single)\s*-\s*', '', raw_title.strip(), flags=re.IGNORECASE).strip()
        return cleaned or "YouTube Music"

    def _scrape_googleusercontent_artwork(self, page_url: str) -> Optional[str]:
        """Directly parses ultra-high-resolution artwork from YouTube Music web page."""
        try:
            r = requests.get(page_url, headers=self.engine.headers, timeout=8)
            if r.status_code == 200:
                raw_urls = re.findall(r'https://[a-zA-Z0-9\._-]+\.googleusercontent\.com/[^\"\'\s<>\\,]+', r.text)
                for u in raw_urls:
                    if "=w" in u or "=s" in u:
                        # Upgrade to 1200x1200 ultra-HD resolution
                        high_res = re.sub(r'=w\d+-h\d+[^\"\'\s]*', '=w1200-h1200-l90-rj', u)
                        return high_res
        except Exception:
            pass
        return None

    def _pick_best_thumbnail(self, info: Dict[str, Any], vid_id: Optional[str] = None) -> Optional[str]:
        """Picks the highest resolution reachable thumbnail URL."""
        thumbnails = info.get("thumbnails", [])
        if thumbnails:
            # Check for googleusercontent URLs first
            for t in reversed(thumbnails):
                u = t.get("url") if isinstance(t, dict) else str(t)
                if u and "googleusercontent.com" in u:
                    return re.sub(r'=w\d+-h\d+[^\"\'\s]*', '=w1200-h1200-l90-rj', u)

            # Check for signed playlist thumbnails
            for t in reversed(thumbnails):
                u = t.get("url") if isinstance(t, dict) else str(t)
                if u and "?" in u:
                    return u

            # Fallback to last thumbnail
            last_u = thumbnails[-1].get("url") if isinstance(thumbnails[-1], dict) else str(thumbnails[-1])
            if last_u:
                return last_u

        if vid_id:
            return f"https://i.ytimg.com/vi/{vid_id}/maxresdefault.jpg"
        return info.get("thumbnail")

    def get_metadata_and_videos(
        self,
        playlist_limit: Optional[int] = None,
        playlist_start: Optional[int] = None
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Extracts high-fidelity YouTube Music metadata and track listings.
        Returns (metadata, videos, raw_info).
        """
        link_type = self.get_link_type()

        if link_type == "single":
            info = self.engine.extract_track_info(self.url, fast=False)
            self.is_playlist = False

            raw_artist = info.get("artist") or info.get("uploader") or info.get("channel") or info.get("creator")
            clean_artist = self._clean_artist_name(raw_artist) or "Unknown Artist"
            raw_title = info.get("track") or info.get("title") or "Unknown Track"
            title = self._clean_album_title(raw_title)
            raw_album = info.get("album") or "Single"
            album = self._clean_album_title(raw_album)

            vid_id = info.get("id")
            thumb = self._scrape_googleusercontent_artwork(self.url) or self._pick_best_thumbnail(info, vid_id)

            metadata = {
                "Channel/Series": clean_artist,
                "Artist": clean_artist,
                "Title": title,
                "Album": album,
                "Source": "YouTube Music",
                "Total Videos": 1,
                "ID": vid_id or "Unknown",
                "Thumbnail": thumb,
                "Duration": info.get("duration"),
            }

            tracks = [{
                "url": info.get("webpage_url") or self.url,
                "title": title,
                "id": vid_id or "Unknown",
                "artist": clean_artist,
                "album": album,
                "uploader": clean_artist,
                "thumbnail": thumb,
                "duration": info.get("duration"),
                "upload_date": info.get("upload_date"),
                "track_number": 1
            }]

            return metadata, tracks, info

        else:
            # Playlist or Album
            info = self.engine.extract_playlist_info(self.url, playlist_limit=playlist_limit, playlist_start=playlist_start)
            self.is_playlist = True

            raw_title = info.get("title") or "Playlist"
            album_title = self._clean_album_title(raw_title)

            entries = info.get("entries", [])
            first_vid_id = entries[0].get("id") if (entries and entries[0]) else None
            cover_thumb = self._scrape_googleusercontent_artwork(self.url) or self._pick_best_thumbnail(info, first_vid_id)

            # Extract artist from tracks if playlist-level artist is missing or generic
            raw_artist = info.get("artist") or info.get("uploader") or info.get("channel")
            clean_artist = self._clean_artist_name(raw_artist)

            entry_artists = []
            for e in entries:
                if e:
                    a = self._clean_artist_name(e.get("artist") or e.get("uploader"))
                    if a:
                        entry_artists.append(a)

            if not clean_artist and entry_artists:
                first_artist = entry_artists[0]
                if all(a == first_artist for a in entry_artists):
                    clean_artist = first_artist
                else:
                    clean_artist = "Various Artists"
            elif not clean_artist:
                clean_artist = "YouTube Music"

            metadata = {
                "Channel/Series": f"{clean_artist} - {album_title}" if clean_artist != "Various Artists" else album_title,
                "Artist": clean_artist,
                "Album": album_title,
                "Source": "YouTube Music",
                "Total Videos": len(entries),
                "ID": info.get("id") or "playlist",
                "Thumbnail": cover_thumb
            }

            tracks = []
            for idx, entry in enumerate(entries, 1):
                if not entry:
                    continue

                vid_id = entry.get("id")
                track_url = f"https://music.youtube.com/watch?v={vid_id}" if vid_id else (entry.get("url") or "")
                raw_track_title = entry.get("title") or f"Track {idx}"
                track_title = self._clean_album_title(raw_track_title)
                
                track_artist = self._clean_artist_name(entry.get("artist") or entry.get("uploader")) or clean_artist
                track_thumb = self._pick_best_thumbnail(entry, vid_id) or cover_thumb

                tracks.append({
                    "url": track_url,
                    "title": track_title,
                    "id": vid_id or str(idx),
                    "artist": track_artist,
                    "album": album_title,
                    "uploader": track_artist,
                    "thumbnail": track_thumb,
                    "duration": entry.get("duration"),
                    "track_number": idx
                })

            return metadata, tracks, info
