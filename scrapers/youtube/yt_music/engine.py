import os
import re
import shutil
import logging
import threading
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Callable, Optional, List
import yt_dlp
import requests

logger = logging.getLogger(__name__)

class YoutubeMusicEngine:
    """
    Isolated engine for YouTube Music audio extraction, FLAC conversion,
    metadata tagging, and synced lyrics fetching.
    """

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://music.youtube.com/",
        }
        self.common_ydl_opts = {
            'nocheckcertificate': True,
            'cachedir': False,
            'no_warnings': True,
            'ignoreerrors': True,
            'retries': 10,
            'fragment_retries': 10,
            'timeout': 60,
            'http_headers': self.headers,
            'concurrent_fragment_downloads': 5,
        }

    def extract_playlist_info(self, url: str, playlist_limit: Optional[int] = None, playlist_start: Optional[int] = None) -> Dict[str, Any]:
        """Extracts flat info for a YT Music playlist or album."""
        ydl_opts = self.common_ydl_opts.copy()
        ydl_opts.update({
            'quiet': True,
            'extract_flat': True,
            'dump_single_json': True,
            'ignoreconfig': True,
        })
        if playlist_limit is None:
            try:
                from core.config import ConfigLayer
                from core.paths import PathAuthority
                from core.storage import StorageLayer
                config = ConfigLayer(PathAuthority(), StorageLayer())
                playlist_limit = config.get("playlist_max_items", 200)
            except Exception:
                playlist_limit = 200

        if playlist_limit and playlist_limit > 0:
            ydl_opts['playlistend'] = playlist_limit
        if playlist_start and playlist_start > 0:
            ydl_opts['playliststart'] = playlist_start

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def extract_track_info(self, url: str, fast: bool = False) -> Dict[str, Any]:
        """Extracts metadata for a single YouTube Music track."""
        ydl_opts = self.common_ydl_opts.copy()
        ydl_opts.update({
            'quiet': True,
            'dump_single_json': True,
            'noplaylist': True,
        })
        if fast:
            ydl_opts.update({
                'extract_flat': True,
                'check_formats': False,
                'ignoreconfig': True,
                'noplugins': True,
            })
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def download_cover_art(
        self,
        folder: Path,
        thumbnails: Optional[List[Any]] = None,
        track_id: Optional[str] = None,
        cover_url: Optional[str] = None,
        filename_prefix: Optional[str] = None
    ) -> Optional[Path]:
        """
        Downloads high-resolution album cover art using a prioritized fallback waterfall.
        Saves cover.jpg / cover.png (or <filename_prefix>.jpg) in the target directory.
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)

        prefix = filename_prefix or "cover"
        existing = list(folder.glob(f"{prefix}.*"))
        if existing and existing[0].stat().st_size > 2048:
            return existing[0]

        candidates: List[str] = []

        # 1. Ultra-HD Google CDN URL
        if cover_url and "googleusercontent.com" in cover_url:
            high_res = re.sub(r'=w\d+-h\d+[^\"\'\s]*', '=w1200-h1200-l90-rj', cover_url)
            candidates.append(high_res)
            candidates.append(cover_url)

        # 2. Signed playlist/album thumbnail URLs
        if thumbnails:
            for t in reversed(thumbnails):
                u = t.get("url") if isinstance(t, dict) else str(t)
                if u and "googleusercontent.com" in u:
                    high_res = re.sub(r'=w\d+-h\d+[^\"\'\s]*', '=w1200-h1200-l90-rj', u)
                    if high_res not in candidates:
                        candidates.append(high_res)
                elif u and "?" in u and u not in candidates:
                    candidates.append(u)

        # 3. Provided cover_url
        if cover_url and cover_url not in candidates:
            candidates.append(cover_url)

        # 4. Track-specific maxresdefault / sddefault
        if track_id:
            candidates.append(f"https://i.ytimg.com/vi/{track_id}/maxresdefault.jpg")
            candidates.append(f"https://i.ytimg.com/vi/{track_id}/sddefault.jpg")
            candidates.append(f"https://i.ytimg.com/vi/{track_id}/hqdefault.jpg")

        # 5. Unsigned thumbnail URLs as fallback
        if thumbnails:
            for t in reversed(thumbnails):
                u = t.get("url") if isinstance(t, dict) else str(t)
                if u and u not in candidates:
                    candidates.append(u)

        for url_cand in candidates:
            try:
                r = requests.get(url_cand, headers=self.headers, timeout=8)
                if r.status_code == 200 and len(r.content) > 2048:
                    ext = ".png" if r.content.startswith(b"\x89PNG") else ".jpg"
                    cover_file = folder / f"{prefix}{ext}"
                    cover_file.write_bytes(r.content)
                    return cover_file
            except Exception:
                continue

        return None

    def download_video(
        self,
        url: str,
        output_dir: Path,
        progress_hook: Optional[Callable] = None,
        raw_stream_url: Optional[str] = None,
        is_audio: bool = True,
        custom_thumbnail: Optional[Path] = None,
        fixed_title: Optional[str] = None,
        fixed_artist: Optional[str] = None,
        fixed_album: Optional[str] = None,
        track_number: Optional[int] = None,
        track_id: Optional[str] = None,
        attempt: int = 1,
        **kwargs
    ) -> bool:
        """
        Downloads a YouTube Music track and converts it into high-fidelity FLAC audio
        with embedded metadata, album cover, and synced lyrics.
        Implements a 3-tier multi-client rotation waterfall for seamless playlist downloads.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        clean_title = "".join([c for c in (fixed_title or "track") if c.isalnum() or c in " .-_()'"]).strip()
        if not clean_title:
            clean_title = "track"
        if len(clean_title) > 150:
            clean_title = clean_title[:150].strip()

        # Filename format
        if track_number is not None:
            filename = f"{track_number:02d}. {clean_title}.flac"
        elif fixed_artist and fixed_title:
            clean_artist = "".join([c for c in fixed_artist if c.isalnum() or c in " .-_()'"]).strip()
            filename = f"{clean_artist} - {clean_title}.flac"
        else:
            filename = f"{clean_title}.flac"

        project_root = Path(__file__).resolve().parent.parent.parent.parent
        poop_dir = project_root / "💩"
        poop_dir.mkdir(parents=True, exist_ok=True)

        final_dest = output_dir / filename
        temp_token = f"ytm_{os.getpid()}_{track_id or 'audio'}"
        temp_outtmpl = poop_dir / f"{temp_token}.%(ext)s"

        # ── Background lyrics fetch ──────────────────────────────────────────
        lrc_parsed = []
        lrc_ready = threading.Event()

        def _bg_lyrics_fetch():
            try:
                from core.lyrics_engine import waterfall_fetch_lyrics, clean_track_string
                t = clean_track_string(fixed_title or "")
                a = clean_track_string(fixed_artist or "")
                if t:
                    lines, _ = waterfall_fetch_lyrics(t, a)
                    lrc_parsed.extend(lines)
            except Exception as e:
                logger.debug(f"Lyrics fetch error: {e}")
            finally:
                lrc_ready.set()

        if fixed_title or fixed_artist:
            lyric_thread = threading.Thread(target=_bg_lyrics_fetch, daemon=True)
            lyric_thread.start()
        else:
            lrc_ready.set()

        # ── Resolve Album Art to Embed ───────────────────────────────────────
        cover_to_embed = custom_thumbnail
        if not cover_to_embed or not Path(cover_to_embed).exists():
            existing_covers = [c for c in output_dir.glob("cover.*") if c.is_file() and c.stat().st_size > 2048]
            if existing_covers:
                cover_to_embed = existing_covers[0]
            elif track_id:
                cover_to_embed = self.download_cover_art(poop_dir, track_id=track_id, filename_prefix=f"cover_{temp_token}")

        # Standardize download URL
        download_url = url
        if track_id:
            download_url = f"https://www.youtube.com/watch?v={track_id}"
        elif "music.youtube.com" in download_url:
            download_url = download_url.replace("music.youtube.com", "www.youtube.com")

        # 3-Tier Multi-Client Rotation Waterfall
        client_rotation = [
            "android,web,default",
            "web_creator,mweb,android",
            "ios,mweb,web"
        ]
        chosen_client = client_rotation[(attempt - 1) % len(client_rotation)]

        ytdlp_bin = shutil.which("yt-dlp") or "yt-dlp"
        cmd = [
            ytdlp_bin,
            download_url,
            "-o", str(temp_outtmpl),
            "--no-playlist",
            "--retries", "10",
            "--fragment-retries", "10",
            "--concurrent-fragments", "5",
            "--no-check-certificate",
            "--no-warnings",
            "--socket-timeout", "15",
            "--extractor-args", f"youtube:player-client={chosen_client}",
            "-x",
            "--audio-format", "flac",
            "--audio-quality", "0",
        ]

        # Cookie integration from user settings
        try:
            from core.config import ConfigLayer
            from core.paths import PathAuthority
            from core.storage import StorageLayer
            cfg = ConfigLayer(PathAuthority(), StorageLayer())
            browser = cfg.get("cookies_browser")
            if browser and browser != "None":
                cmd.extend(["--cookies-from-browser", str(browser)])
        except Exception:
            pass

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )

            unit_map = {
                'B': 1, 'KIB': 1024, 'KB': 1000,
                'MIB': 1024**2, 'MB': 1000**2,
                'GIB': 1024**3, 'GB': 1000**3
            }

            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    if progress_hook and "[download]" in line:
                        m = re.search(r'\[download\]\s+([\d\.]+)%\s+of\s+~?([\d\.]+)(\w+)\s+at\s+~?([\d\.]+)(\w+/s)?', line)
                        if m:
                            try:
                                pct = float(m.group(1))
                                size_val = float(m.group(2))
                                size_unit = m.group(3).upper()
                                speed_val = float(m.group(4))
                                total_b = int(size_val * unit_map.get(size_unit, 1024**2))
                                dl_b = int((pct / 100.0) * total_b)
                                spd = int(speed_val * 1024**2)
                                progress_hook({
                                    'status': 'downloading',
                                    'downloaded_bytes': dl_b,
                                    'total_bytes': total_b,
                                    'speed': spd
                                })
                            except Exception:
                                pass
                    elif progress_hook and "[ExtractAudio]" in line:
                        progress_hook({'status': 'finished'})

            proc.wait()

            candidates = list(poop_dir.glob(f"{temp_token}*.flac"))
            if not candidates or candidates[0].stat().st_size < 1024:
                return False

            downloaded_flac = candidates[0]

            # Wait briefly for lyrics thread
            lrc_ready.wait(timeout=2.0)

            # Plain lyrics text for vorbis comment
            plain_lyrics = "\n".join(e.get("text", "") for e in lrc_parsed if isinstance(e, dict)) if lrc_parsed else None

            # ── Embed Vorbis / FLAC metadata & Cover Art ──────────────────────
            self._tag_flac_file(
                downloaded_flac,
                title=fixed_title,
                artist=fixed_artist,
                album=fixed_album,
                track_number=track_number,
                custom_thumb=cover_to_embed,
                lyrics=plain_lyrics
            )

            # Move final tagged FLAC to destination
            shutil.move(str(downloaded_flac), str(final_dest))

            # If synced lyrics were found, save companion .lrc file in destination
            if lrc_parsed:
                try:
                    from core.lyrics_engine import format_lrc
                    lrc_dest = final_dest.with_suffix(".lrc")
                    with open(lrc_dest, "w", encoding="utf-8") as lf:
                        lf.write(format_lrc(lrc_parsed))
                except Exception as e:
                    logger.debug(f"Failed to write .lrc file: {e}")

            # Clean up all temporary files in 💩
            for junk in poop_dir.glob(f"{temp_token}*"):
                try:
                    junk.unlink(missing_ok=True)
                except Exception:
                    pass
            for junk in poop_dir.glob(f"cover_{temp_token}*"):
                try:
                    junk.unlink(missing_ok=True)
                except Exception:
                    pass

            return final_dest.exists() and final_dest.stat().st_size > 1024

        except Exception as e:
            logger.error(f"YouTube Music download error: {e}")
            return False

    def _tag_flac_file(
        self,
        flac_path: Path,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        track_number: Optional[int] = None,
        custom_thumb: Optional[Path] = None,
        lyrics: Optional[str] = None
    ):
        """Tags the output FLAC file with rich Vorbis metadata and embeds album art."""
        try:
            from mutagen.flac import FLAC, Picture
            audio = FLAC(str(flac_path))

            if title:
                audio["TITLE"] = title
            if artist:
                audio["ARTIST"] = artist
            if album:
                audio["ALBUM"] = album
            if track_number is not None:
                audio["TRACKNUMBER"] = str(track_number)
            if lyrics:
                audio["LYRICS"] = lyrics

            # Embed front album cover art
            if custom_thumb and Path(custom_thumb).exists():
                thumb_data = Path(custom_thumb).read_bytes()
                if len(thumb_data) > 1024:
                    audio.clear_pictures()
                    pic = Picture()
                    pic.type = 3  # Cover (front)
                    pic.mime = "image/png" if thumb_data.startswith(b"\x89PNG") else "image/jpeg"
                    pic.data = thumb_data
                    audio.add_picture(pic)

            audio.save()
        except Exception as e:
            logger.debug(f"Mutagen FLAC tagging failed: {e}")

    def save_metadata(
        self,
        folder: Path,
        info: Dict[str, Any],
        source: str = "YouTube Music",
        cover_url: Optional[str] = None,
        thumbnails: Optional[List[Any]] = None,
        track_id: Optional[str] = None
    ):
        """Saves metadata JSON and downloads album cover art (for Vacuum mode only)."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)

        meta_file = folder / "metadata.json"
        try:
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        self.download_cover_art(
            folder,
            thumbnails=thumbnails or info.get("thumbnails"),
            track_id=track_id or info.get("id"),
            cover_url=cover_url or info.get("thumbnail")
        )
