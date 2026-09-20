import yt_dlp
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, Any, Callable, Optional, Union
import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from core.cover_utils import extract_cover_url

logger = logging.getLogger(__name__)

class VideoEngine:
    """Centralized engine for downloading videos using yt-dlp with rich metadata and cover extraction."""

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        # Common yt-dlp options to help with throttling/403
        self.common_ydl_opts = {
            'nocheckcertificate': True,
            'cachedir': False,
            'no_warnings': True,
            'ignoreerrors': False,
            'retries': 10,
            'fragment_retries': 10,
            'timeout': 60,
            'http_headers': self.headers,
            'concurrent_fragment_downloads': 5,
            'buffersize': 1024 * 1024,
            'http_chunk_size': 1048576,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web']
                },
                'youtubetab': {
                    'skip': ['authcheck']
                }
            }
        }
        try:
            from core.config import ConfigLayer
            from core.paths import PathAuthority
            from core.storage import StorageLayer
            cfg = ConfigLayer(PathAuthority(), StorageLayer())
            browser = cfg.get("cookies_browser")
            if browser and browser != "None":
                self.common_ydl_opts['cookiesfrombrowser'] = (str(browser), None, None, None)
        except Exception:
            pass

    def extract_playlist_info(self, url: str, playlist_limit: Optional[int] = None, playlist_start: Optional[int] = None) -> Dict[str, Any]:
        """Extracts flat info for a playlist or channel with multi-client rotation."""
        if playlist_limit is None:
            try:
                from core.config import ConfigLayer
                from core.paths import PathAuthority
                from core.storage import StorageLayer
                config = ConfigLayer(PathAuthority(), StorageLayer())
                playlist_limit = config.get("playlist_max_items", 100)
            except Exception:
                playlist_limit = 100

        client_waterfall = [
            ['android', 'ios', 'web'],
            ['web_creator', 'mweb', 'android'],
            ['ios', 'mweb', 'web'],
            ['android_music', 'android', 'web']
        ]
        last_exc = None
        for chain in client_waterfall:
            ydl_opts = self.common_ydl_opts.copy()
            ydl_opts.update({
                'quiet': True,
                'extract_flat': True,
                'dump_single_json': True,
                'ignoreconfig': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': chain
                    },
                    'youtubetab': {
                        'skip': ['authcheck']
                    }
                }
            })
            if playlist_limit and playlist_limit > 0:
                ydl_opts['playlistend'] = playlist_limit
            if playlist_start and playlist_start > 0:
                ydl_opts['playliststart'] = playlist_start

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        return info
            except Exception as e:
                last_exc = e
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Could not extract playlist metadata from {url}")

    def extract_video_info(self, url: str, fast: bool = False) -> Dict[str, Any]:
        """Extracts full info for a single video with multi-client rotation."""
        client_waterfall = [
            ['android', 'ios', 'web'],
            ['web_creator', 'mweb', 'android'],
            ['ios', 'mweb', 'web'],
            ['android_music', 'android', 'web']
        ]
        last_exc = None
        for chain in client_waterfall:
            ydl_opts = self.common_ydl_opts.copy()
            ydl_opts.update({
                'quiet': True,
                'dump_single_json': True,
                'noplaylist': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': chain
                    },
                    'youtubetab': {
                        'skip': ['authcheck']
                    }
                }
            })
            if fast:
                ydl_opts.update({
                    'extract_flat': True,
                    'check_formats': False,
                    'ignoreconfig': True,
                    'noplugins': True,
                    'source_address': '0.0.0.0',
                })
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        return info
            except Exception as e:
                last_exc = e
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Could not extract video metadata from {url}")

    def download_video(self, url: str, output_dir: Path, progress_hook: Callable, raw_stream_url: str = None, is_audio: bool = False, custom_thumbnail: Path = None, fixed_title: str = None, fixed_artist: str = None, fixed_album: str = None, format_override: str = None, baking_callback: Callable = None, **kwargs) -> bool:
        """
        Downloads a video/audio.
        """
        import threading
        videos_dir = output_dir
        videos_dir.mkdir(parents=True, exist_ok=True)

        ext = "flac" if is_audio else "mp4"
        
        # If we have a fixed title, use it for the filename
        if fixed_title:
            clean_title = "".join([c for c in fixed_title if c.isalnum() or c in " .-_()'"]).strip()
            if len(clean_title) > 150:
                clean_title = clean_title[:150].strip()
        else:
            clean_title = "%(title)s [%(id)s]"

        project_root = Path(__file__).parent.parent
        poop_dir = project_root / "💩"
        poop_dir.mkdir(parents=True, exist_ok=True)
        
        tmp_path = poop_dir / f"{clean_title}.{ext}"
        final_dest = videos_dir / f"{clean_title}.{ext}"

        import tempfile
        import os
        import shutil

        temp_batch = poop_dir / f"{clean_title}_batch.txt"

        # ── Parallel lyrics fetch: start background thread NOW, before yt-dlp ──
        # This way the lyrics waterfall runs concurrently with the download.
        prefetched_lrc_lines = []
        prefetched_lrc_source = [None]
        lrc_ready = threading.Event()

        def _bg_lyrics_fetch():
            if not is_audio:
                lrc_ready.set()
                return
            try:
                from core.lyrics_engine import waterfall_fetch_lyrics, clean_track_string
                t = clean_track_string(fixed_title or "")
                a = clean_track_string(fixed_artist or "")
                if t:
                    lines, src = waterfall_fetch_lyrics(t, a)
                    prefetched_lrc_lines.extend(lines)
                    prefetched_lrc_source[0] = src
            except Exception as e:
                logger.debug(f"Background lyrics fetch error: {e}")
            finally:
                lrc_ready.set()

        if is_audio and (fixed_title or fixed_artist):
            lyric_thread = threading.Thread(target=_bg_lyrics_fetch, daemon=True)
            lyric_thread.start()
        else:
            lrc_ready.set()
            lyric_thread = None

        try:
            target = raw_stream_url if raw_stream_url else url
            if ".m3u8" in target and not is_audio:
                success = self._download_custom_hls(target, tmp_path, progress_hook, fixed_title, custom_thumbnail, baking_callback)
                if success and tmp_path.exists():
                    shutil.move(str(tmp_path), str(final_dest))
                return success
                
            with open(temp_batch, 'w', encoding='utf-8') as f:
                f.write(target + '\n')
            
            import shutil
            ytdlp_bin = shutil.which("yt-dlp") or "yt-dlp"
            cmd = [
                ytdlp_bin,
                "--batch-file", str(temp_batch),
                "-o", str(poop_dir / f"{clean_title}.%(ext)s"),
                "--no-playlist",
                "--retries", "15",
                "--fragment-retries", "15",
                "--concurrent-fragments", "8",
                "--no-check-certificate",
                "--no-warnings",
                "--socket-timeout", "30"
            ]
            
            if shutil.which("aria2c"):
                aria_args = kwargs.get(
                    "downloader_args",
                    "aria2c:-c -x 8 -s 8 -k 2M --file-allocation=none --connect-timeout=20 --timeout=30 --max-tries=15 --retry-wait=2 --allow-overwrite=true --auto-file-renaming=false"
                )
                cmd.extend([
                    "--downloader", "aria2c",
                    "--downloader-args", aria_args
                ])
            
            for k, v in self.headers.items():
                cmd.extend(["--add-header", f"{k}:{v}"])
                
            if is_audio:
                cmd.extend([
                    "-x",
                    "--audio-format", "flac",
                    "--audio-quality", "0",
                    "--embed-metadata",
                    "--embed-thumbnail"
                ])
            else:
                if ".mp4" in target or ".m3u8" in target:
                    pass # Do not pass any format flag for direct streams
                else:
                    fmt = format_override or os.environ.get("ZINE_QUALITY") or "bestvideo*+bestaudio/best"
                    cmd.extend(["-f", fmt])
                
                cmd.extend([
                    "--merge-output-format", "mp4",
                    "--embed-metadata",
                    "--embed-thumbnail"
                ])
                
            logger.info(f"Invoking yt-dlp: {' '.join(cmd)}")
            success = self._run_ytdlp_subprocess(cmd, progress_hook, str(tmp_path))
            
            if success:
                # Find the generated file in our shared poop_dir that matches our clean_title
                generated = None
                for f in poop_dir.iterdir():
                    if f.is_file() and f.name.startswith(clean_title) and not f.name.endswith('.txt') and not f.name.endswith('.part') and not f.name.endswith('.ytdl'):
                        generated = f
                        break
                
                if generated and generated.exists():
                    real_filename = generated.name
                    real_final_dest = videos_dir / real_filename
                    shutil.move(str(generated), str(real_final_dest))

                    # Move companion subtitle / lyrics files matching clean_title
                    sub_dest_dir = (videos_dir / "subtitle") if not is_audio else ((videos_dir.parent / "lyrics") if videos_dir.name == "audio" else videos_dir)
                    sub_dest_dir.mkdir(parents=True, exist_ok=True)

                    for sub_file in poop_dir.iterdir():
                        if sub_file.is_file() and sub_file.name.startswith(clean_title):
                            if sub_file.suffix.lower() in ['.srt', '.vtt', '.ass'] and not is_audio:
                                try:
                                    shutil.move(str(sub_file), str(sub_dest_dir / sub_file.name))
                                except Exception:
                                    pass
                            elif sub_file.suffix.lower() in ['.lrc'] and is_audio:
                                try:
                                    shutil.move(str(sub_file), str(sub_dest_dir / sub_file.name))
                                except Exception:
                                    pass
                    
                    if custom_thumbnail and custom_thumbnail.exists():
                        self._apply_custom_metadata(real_final_dest, custom_thumbnail, is_audio, fixed_title, fixed_artist, fixed_album)
                    
                    # ── Lyrics: always use real embedded metadata from the downloaded file ──
                    # The parallel pre-fetch thread warmed the disk cache.
                    # Now read the REAL title/artist that yt-dlp --embed-metadata wrote,
                    # and search with that — cache hit if pre-warm matched, accurate
                    # fresh search if the processed name was too different.
                    if is_audio:
                        try:
                            from core.lyrics_engine import auto_fetch_lyrics
                            auto_fetch_lyrics(real_final_dest)
                        except Exception as e:
                            logger.debug(f"Auto lyrics fetch error: {e}")

                    return True
                else:
                    return False
            return False
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"Download failed for {target}: {e}")
            return False
        finally:
            if temp_batch.exists():
                try:
                    temp_batch.unlink()
                except Exception:
                    pass

    def _run_ytdlp_subprocess(self, cmd, progress_hook, fallback_filename) -> bool:
        import subprocess
        import re
        
        def to_bytes(value_str, unit):
            try:
                val = float(value_str)
                u = unit.lower()
                if 'gib' in u or 'gb' in u:
                    return int(val * 1024 * 1024 * 1024)
                if 'mib' in u or 'mb' in u:
                    return int(val * 1024 * 1024)
                if 'kib' in u or 'kb' in u:
                    return int(val * 1024)
                return int(val)
            except Exception:
                return 0

        def parse_eta(eta_str):
            if not eta_str or eta_str.lower() == 'unknown':
                return None
            
            if 's' in eta_str or 'm' in eta_str or 'h' in eta_str:
                total_seconds = 0
                import re
                for val, unit in re.findall(r'(\d+)([smh])', eta_str.lower()):
                    if unit == 'h': total_seconds += int(val) * 3600
                    elif unit == 'm': total_seconds += int(val) * 60
                    elif unit == 's': total_seconds += int(val)
                return total_seconds if total_seconds > 0 else None

            parts = eta_str.split(':')
            try:
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
            except Exception:
                pass
            return None

        import time
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, stdin=subprocess.DEVNULL)
            except Exception as e:
                logger.error(f"Failed to start yt-dlp subprocess on attempt {attempt+1}: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(2)
                    continue
                return False

            progress_re = re.compile(
                r'\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+)(KiB|MiB|GiB|B)\s+at\s+([\d.]+|Unknown)(?:(KiB/s|MiB/s|GiB/s|B/s))?\s+ETA\s+([\d:]+|Unknown)'
            )
            ffmpeg_re = re.compile(
                r'size=\s*([\d.]+)(KiB|MiB|GiB|B|kB|mB|gB|kb|mb|gb)\s+time=([\d:]+)'
            )
            aria_re = re.compile(
                r'\[#[\da-f]+\s+([\d.]+)(KiB|MiB|GiB|B)/([\d.]+)(KiB|MiB|GiB|B)\(([\d]+)%\).*?DL:([\d.]+)(KiB|MiB|GiB|B|Unknown).*?(?:ETA:([\dsmh]+))?'
            )

            current_file = fallback_filename
            
            def to_bytes(val, unit):
                if val.lower() == "unknown": return 0
                u = unit.lower().replace('b', '').replace('i', '').replace('s', '')
                multipliers = {'k': 1024, 'm': 1024**2, 'g': 1024**3}
                try:
                    return int(float(val) * multipliers.get(u, 1))
                except Exception:
                    return 0
            
            def iter_lines():
                buf = ""
                while True:
                    char = process.stdout.read(1)
                    if not char:
                        if buf:
                            yield buf
                        break
                    if char in ('\r', '\n'):
                        if buf:
                            yield buf
                            buf = ""
                    else:
                        buf += char

            for line in iter_lines():
                line = line.strip()
                if not line:
                    continue

                if "[download] Destination:" in line:
                    parts = line.split("Destination:")
                    if len(parts) > 1:
                        current_file = parts[1].strip()
                        
                m_aria = aria_re.search(line)
                if m_aria and progress_hook:
                    dl_val, dl_unit, tot_val, tot_unit, pct, spd_val, spd_unit, eta_str = m_aria.groups()
                    d = {
                        "status": "downloading",
                        "filename": current_file,
                        "downloaded_bytes": to_bytes(dl_val, dl_unit),
                        "total_bytes": to_bytes(tot_val, tot_unit),
                        "speed": to_bytes(spd_val, spd_unit),
                        "eta": parse_eta(eta_str) if eta_str else None
                    }
                    progress_hook(d)
                    continue
                
                m_prog = progress_re.search(line)
                if m_prog and progress_hook:
                    pct, tot_val, tot_unit, spd_val, spd_unit, eta_str = m_prog.groups()
                    d = {
                        "status": "downloading",
                        "filename": current_file,
                        "downloaded_bytes": to_bytes(tot_val, tot_unit) * (float(pct) / 100.0) if pct else 0,
                        "total_bytes": to_bytes(tot_val, tot_unit),
                        "speed": to_bytes(spd_val, spd_unit) if spd_val else 0,
                        "eta": parse_eta(eta_str) if eta_str else None
                    }
                    progress_hook(d)
                    continue

                if "[download]" in line and progress_hook:
                    # Catch retry or generic messages so the UI doesn't freeze at "Starting..."
                    msg = line.split("[download]")[-1].strip()
                    if "Destination:" not in msg and "%" not in msg:
                        progress_hook({"status": msg[:40] + "..." if len(msg)>40 else msg, "filename": current_file})
                        
                if "ERROR:" in line:
                    logger.error(f"[yt-dlp Error] {line}")
                    if progress_hook:
                        msg = line.split("ERROR:")[-1].strip()
                        progress_hook({"status": f"Error: {msg[:30]}...", "filename": current_file})
                    
                match = progress_re.search(line)
                if match:
                    percent = float(match.group(1))
                    total_str = match.group(2)
                    total_unit = match.group(3)
                    speed_str = match.group(4)
                    speed_unit = match.group(5) or 'B/s'
                    eta_str = match.group(6)
                    
                    total_bytes = to_bytes(total_str, total_unit)
                    downloaded_bytes = int(total_bytes * (percent / 100.0))
                    
                    speed = 0.0
                    if speed_str != 'Unknown':
                        speed = float(to_bytes(speed_str, speed_unit.replace('/s', '')))
                        
                    eta = parse_eta(eta_str)
                    
                    d = {
                        "status": "downloading",
                        "filename": current_file,
                        "downloaded_bytes": downloaded_bytes,
                        "total_bytes": total_bytes,
                        "speed": speed,
                        "eta": eta
                    }
                    if progress_hook:
                        progress_hook(d)
                else:
                    match_ffmpeg = ffmpeg_re.search(line)
                    if match_ffmpeg:
                        size_str = match_ffmpeg.group(1)
                        size_unit = match_ffmpeg.group(2)
                        downloaded_bytes = to_bytes(size_str, size_unit)
                        d = {
                            "status": "downloading",
                            "filename": current_file,
                            "downloaded_bytes": downloaded_bytes,
                            "total_bytes": 0,
                            "speed": 0,
                            "eta": None
                        }
                        if progress_hook:
                            progress_hook(d)
                            
                if "[download] 100% of" in line or "[download] 100.0% of" in line:
                    d = {
                        "status": "finished",
                        "filename": current_file
                    }
                    if progress_hook:
                        progress_hook(d)

            process.wait()
            if process.returncode == 0:
                return True
            
            logger.error(f"yt-dlp subprocess failed with exit code {process.returncode} on attempt {attempt+1}/{max_attempts}")
            if attempt < max_attempts - 1:
                time.sleep(2)
                
        return False

    def _apply_custom_metadata(self, media_path: Path, cover_path: Path, is_audio: bool, title: str = None, artist: str = None, album: str = None):
        """Uses ffmpeg to bake the custom cover AND forced metadata (Title, Artist, Album) into the media file."""
        import subprocess
        from core.cover_utils import ensure_compatible_image_for_ffmpeg
        effective_cover, temp_to_clean = ensure_compatible_image_for_ffmpeg(cover_path)
        try:
            tmp_path = media_path.with_suffix(".meta.tmp" + media_path.suffix)
            
            import shutil
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
            cmd = [ffmpeg_bin, "-y", "-i", str(media_path)]
            if effective_cover and effective_cover.exists():
                cmd.extend(["-i", str(effective_cover)])
            
            # Map streams
            if effective_cover and effective_cover.exists():
                if is_audio:
                    cmd.extend(["-map", "0:a", "-map", "1:0"])
                else:
                    cmd.extend(["-map", "0", "-map", "1"])
            else:
                cmd.extend(["-map", "0"])

            cmd.extend(["-c", "copy"])

            # Metadata overrides
            if title:
                cmd.extend(["-metadata", f"title={title}"])
            if artist:
                cmd.extend(["-metadata", f"artist={artist}"])
            if album:
                cmd.extend(["-metadata", f"album={album}"])

            # Cover disposition
            if effective_cover and effective_cover.exists():
                if is_audio:
                    cmd.extend(["-disposition:v", "attached_pic"])
                else:
                    cmd.extend(["-disposition:v:1", "attached_pic"])
                
                cmd.extend(["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"])

            # MP3 specific
            if is_audio and media_path.suffix.lower() == ".mp3":
                cmd.extend(["-id3v2_version", "3"])

            cmd.append(str(tmp_path))
            
            subprocess.run(cmd, check=True, capture_output=True)
            if tmp_path.exists():
                media_path.unlink()
                tmp_path.rename(media_path)
                return True
            return False
        except Exception as e:
            logger.error(f"FFmpeg metadata/cover application failed: {e}")
            return False
        finally:
            if temp_to_clean and temp_to_clean.exists():
                try:
                    temp_to_clean.unlink()
                except Exception:
                    pass

    def save_metadata(self, root_dir: Path, info: Dict[str, Any], source: str, cover_url: Optional[str] = None):
        """Saves metadata.json inside .zine/ folder and cover.jpg in root content folder."""
        from core.history import _is_quick_grab_dir
        if _is_quick_grab_dir(root_dir):
            return
            
        from core.metadata_engine import MetadataEngine, ZineMetadataPayload
        is_music = source.lower() in ["idagio", "soundcloud", "music"]
        media_type = "Song" if is_music else "Channel"
        title = info.get('album') or info.get('uploader') or info.get('channel') or info.get('title') or "Unknown"
        author = info.get('artist') or info.get('uploader') or info.get('channel') or ""
        payload = ZineMetadataPayload(
            title=title,
            type=media_type,
            author=author,
            description=info.get('description', ''),
            url=info.get('webpage_url') or info.get('original_url') or ""
        )
        MetadataEngine.save_metadata(root_dir, payload)

        # Try to download cover/avatar
        thumb_url = cover_url
        if not thumb_url:
            thumbnails = info.get('thumbnails', [])
            if thumbnails:
                # Get the highest resolution thumbnail
                best_thumb = max(thumbnails, key=lambda x: x.get('width', 0) * x.get('height', 0) if x.get('width') else 0)
                thumb_url = best_thumb.get('url')
        
        if not thumb_url:
            # Fallback to manual extraction
            try:
                resp = requests.get(info.get('webpage_url') or info.get('original_url'), headers=self.headers, timeout=15)
                soup = BeautifulSoup(resp.text, 'html.parser')
                from core.cover_utils import extract_cover_url
                thumb_url = extract_cover_url(soup, info.get('webpage_url') or info.get('original_url'))
            except Exception:
                pass

        if thumb_url:
            if not thumb_url.startswith('http'):
                # Handle relative URLs
                from urllib.parse import urljoin
                base_url = info.get('webpage_url') or info.get('original_url')
                thumb_url = urljoin(base_url, thumb_url)

            from core.cover_utils import download_verified_cover
            download_verified_cover(thumb_url, root_dir, headers=self.headers)

    def _download_custom_hls(self, playlist_url: str, tmp_path: Path, progress_hook: Callable, fixed_title: str, custom_thumbnail: Path, baking_callback: Callable = None) -> bool:
        """
        Downloads HLS stream (.m3u8), strips fake PNG headers from segments,
        concatenates them, and converts to final MP4 using ffmpeg.
        """
        import requests
        import re
        import os
        import time
        from urllib.parse import urljoin
        from concurrent.futures import ThreadPoolExecutor

        logger.info(f"Custom HLS Downloader started for: {playlist_url}")
        
        try:
            import subprocess
            import json
            import base64
            
            from core.paths import get_system_script
            import sys
            venv_python = sys.executable
            script_path = get_system_script("hls_extractor.py")
            
            headers_b64 = base64.b64encode(json.dumps(self.headers).encode('utf-8')).decode('utf-8')
            
            cmd = [str(venv_python), str(script_path), playlist_url, str(tmp_path), headers_b64]
            logger.info(f"Invoking HLS Extractor: {' '.join(cmd)}")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL, bufsize=1)
            
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "error" in data:
                        logger.error(f"[HLS Extractor Error] {data['error']}")
                    if data.get("baking"):
                        if baking_callback:
                            baking_callback()
                    elif progress_hook:
                        progress_hook(data)
                except json.JSONDecodeError:
                    logger.error(f"[HLS Extractor Output] {line}")

            process.wait()
            if process.returncode != 0:
                logger.error(f"HLS Extractor failed with exit code {process.returncode}")
                return False

            # Apply metadata and cover just like main yt-dlp flow
            if tmp_path.exists():
                
                # Cleanup leftover files
                videos_dir = tmp_path.parent
                for pat in ["*Frag*", "*.ytdl", "*.part"]:
                    for junk in videos_dir.glob(pat):
                        if not junk.name.endswith('.mp4') and not junk.name.endswith('.flac'):
                            junk.unlink(missing_ok=True)
                return True
                
            return False

        except Exception as e:
            pass
            return False

def is_internet_active() -> bool:
    import urllib.request
    try:
        # Use cloudflare DNS IP to avoid DNS resolution dependency first
        urllib.request.urlopen('https://1.1.1.1', timeout=3)
        return True
    except Exception:
        pass
    try:
        urllib.request.urlopen('https://www.google.com', timeout=3)
        return True
    except Exception:
        pass
    return False

def handle_internet_loss() -> bool:
    """
    Checks if internet is lost. If lost, pauses and waits for connection restoration.
    Fires a background whistleblower thread to check connection status automatically
    while allowing manual 'wake up' input. Stops active Live TUI rendering to prevent overlapping.
    """
    if is_internet_active():
        return False
        
    import getpass
    import sys
    import time
    import select
    from core.ui import console, get_theme_input_ansi, _LIVE_INSTANCE
    from butler.whistleblower import start_whistleblower, stop_whistleblower, is_internet_restored
    
    # Pause and stop the current active Live visualizer so the tree disappears
    active_live = _LIVE_INSTANCE
    import core.ui as ui
    # If another thread is already displaying the connection lost TUI, wait for it to finish and return
    if not ui._connection_restored_event.is_set():
        ui._connection_restored_event.wait()
        return True
        
    # Acquire the lock to prevent concurrent threads from duplicating the prompt
    with ui._internet_loss_lock:
        if not ui._connection_restored_event.is_set():
            ui._connection_restored_event.wait()
            return True
            
        # We are the first thread to encounter the outage. Clear the event so other threads block.
        ui._connection_restored_event.clear()
        
        old_menu_active = ui._MENU_ACTIVE
        ui._MENU_ACTIVE = True
    
        if active_live:
            try:
                active_live.stop()
            except Exception:
                pass
                
        # Temporarily restore termios configuration to cooked mode so the user can type!
        if ui._tty_fd is not None and ui._old_tty_settings is not None:
            try:
                import termios
                termios.tcsetattr(ui._tty_fd, termios.TCSADRAIN, ui._old_tty_settings)
            except Exception:
                pass
                
        username = getpass.getuser()
        console.print(f"\n[error]✘ Connection lost![/error] [warning]I've got your back, {username}... pausing download queue.[/warning]\n")
        
        restored_flag = [False]
        def on_restored():
            restored_flag[0] = True
            
        start_whistleblower(on_restored)
    
    # Print clean input prompt — 3 helper lines + prompt indicator
    console.print(f"[menu]Once the internet is back, write [sexy_pink]\"wake up\"[/sexy_pink] to resume (or type [bold]\"exit\"[/bold] to cancel):[/menu]")
    console.print("[unselected]  (A background checker is running and will resume automatically when online.)[/unselected]")
    console.print("[unselected]  (If automatic resume fails, type \"wake up\" manually to force it and report the bug.)[/unselected]")
    console.print("[menu]❯ [/menu]", end="")
    sys.stdout.write(get_theme_input_ansi())
    sys.stdout.flush()
    
    try:
        while True:
            if restored_flag[0]:
                sys.stdout.write("\033[0m")
                sys.stdout.flush()
                sys.stdout.flush()
                console.print(f"[success]● Connection restored, starting the engine please wait...[/success]")
                time.sleep(1.5)
                ui._MENU_ACTIVE = old_menu_active
                
                from butler.whistleblower import _active_tui_callback
                if _active_tui_callback:
                    try:
                        _active_tui_callback()
                    except Exception:
                        pass
                
                return True
                
            # Non-blocking wait for input up to 1 second
            rlist, _, _ = select.select([sys.stdin], [], [], 1.0)
            if rlist:
                try:
                    val = sys.stdin.readline().strip().lower()
                except Exception:
                    val = ""
                sys.stdout.write("\033[0m")
                sys.stdout.flush()
                
                # Normalize spelling inputs
                norm_val = val.replace(" ", "").replace("-", "").replace("_", "")
                
                # Fuzzy matches for exit
                if norm_val in ["exit", "exi", "exitt", "quit", "q", "cancel", "c"]:
                    console.print("[info]● Exiting download queue...[/info]")
                    sys.exit(0)
                # Fuzzy matches for wake up
                elif norm_val in ["wakeup", "wake", "wackup", "waekup", "wakeapp", "wakeu", "wukup", "wakup"]:
                    if is_internet_restored():
                        sys.stdout.flush()
                        console.print(f"[success]● Connection restored, starting the engine please wait...[/success]")
                        time.sleep(1.5)
                        ui._MENU_ACTIVE = old_menu_active
                        
                        from butler.whistleblower import _active_tui_callback
                        if _active_tui_callback:
                            try:
                                _active_tui_callback()
                            except Exception as e:
                                pass
                        
                        return True
                    else:
                        sys.stdout.flush()
                        console.print(f"[warning]✘ Connection is still offline. Please verify your network and try again.[/warning]")
                        time.sleep(2)
                        console.print("[menu]❯ [/menu]", end="")
                        sys.stdout.write(get_theme_input_ansi())
                        sys.stdout.flush()
                else:
                    # Clear invalid input line instantly to keep screen perfectly clean
                    sys.stdout.write("\r\033[K\033[A\r\033[K")
                    sys.stdout.flush()
                    # Reprint prompt indicator
                    console.print("[menu]❯ [/menu]", end="")
                    sys.stdout.write(get_theme_input_ansi())
                    sys.stdout.flush()
    finally:
        stop_whistleblower()
        ui._INTERNET_DOWN = False
        ui._connection_restored_event.set()
        # Restore raw mode if active_live was running
        if ui._tty_fd is not None:
            try:
                import termios
                mode = termios.tcgetattr(ui._tty_fd)
                mode[0] = mode[0] & ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
                mode[2] = mode[2] & ~(termios.CSIZE | termios.PARENB)
                mode[2] = mode[2] | termios.CS8
                mode[3] = mode[3] & ~(termios.ECHO | termios.ICANON | termios.IEXTEN)
                mode[3] = mode[3] | termios.ISIG
                termios.tcsetattr(ui._tty_fd, termios.TCSADRAIN, mode)
            except Exception:
                pass
        # Resume the Live visualizer since the process is starting again
        if active_live:
            try:
                active_live.start()
            except Exception:
                pass


def vtt_to_srt(vtt_text: str) -> str:
    """
    Converts WebVTT format text to standard SubRip (.srt) format text.
    Handles timestamp formatting (period -> comma), strips WEBVTT headers,
    cue styling/positioning tags, and ensures valid sequential 1-based cue numbers.
    """
    if not vtt_text or not isinstance(vtt_text, str):
        return ""

    # If it's already an SRT format (starts with a digit cue number and has --> with commas), return as is
    if re.match(r'^\s*\d+\s*\n\s*\d{2}:\d{2}:\d{2},\d{3}\s*-->', vtt_text):
        return vtt_text.strip() + "\n"

    lines = vtt_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ts_pattern = re.compile(
        r'(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})'
    )

    def normalize_timestamp(m):
        h1 = m.group(1) or "00"
        if len(h1) == 1: h1 = "0" + h1
        m1, s1, ms1 = m.group(2), m.group(3), m.group(4)

        h2 = m.group(5) or "00"
        if len(h2) == 1: h2 = "0" + h2
        m2, s2, ms2 = m.group(6), m.group(7), m.group(8)

        return f"{h1}:{m1}:{s1},{ms1} --> {h2}:{m2}:{s2},{ms2}"

    cues = []
    current_cue = {"time": "", "lines": []}
    in_header = True
    in_style = False

    for line in lines:
        stripped = line.strip()
        if in_header:
            if stripped.startswith("WEBVTT") or stripped.startswith("NOTE") or stripped.startswith("REGION"):
                continue
            if stripped.startswith("STYLE"):
                in_style = True
                continue
            if in_style:
                if stripped == "":
                    in_style = False
                continue
            if stripped == "":
                in_header = False
                continue

        match = ts_pattern.search(line)
        if match:
            in_header = False
            if current_cue["time"] and current_cue["lines"]:
                cues.append(current_cue)
            current_cue = {"time": normalize_timestamp(match), "lines": []}
        elif current_cue["time"]:
            if stripped == "":
                if current_cue["lines"]:
                    cues.append(current_cue)
                    current_cue = {"time": "", "lines": []}
            else:
                # Strip cue settings or inline styling tags like <c.color>, <00:01.000>
                clean_line = re.sub(r'<\/?c[^>]*>', '', line)
                clean_line = re.sub(r'<\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}>', '', clean_line)
                clean_line = clean_line.strip()
                if clean_line:
                    current_cue["lines"].append(clean_line)

    if current_cue["time"] and current_cue["lines"]:
        cues.append(current_cue)

    srt_blocks = []
    for idx, cue in enumerate(cues, 1):
        srt_blocks.append(f"{idx}\n{cue['time']}\n" + "\n".join(cue["lines"]))

    return "\n\n".join(srt_blocks).strip() + "\n" if srt_blocks else ""


def save_subtitle_as_srt(content: Union[str, bytes], dest_dir: Path, base_name: str, lang: Optional[str] = None) -> Path:
    """
    Saves subtitle content as .srt in dest_dir.
    Converts VTT to SRT if content is WebVTT.
    Returns the path to the saved .srt file.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")
    else:
        text = str(content)

    srt_text = vtt_to_srt(text) or text

    stem = f"{base_name}.{lang}" if lang else base_name
    dest_file = dest_dir / f"{stem}.srt"
    dest_file.write_text(srt_text, encoding="utf-8")
    return dest_file


def migrate_and_clean_subtitles(video_dir: Path, subtitle_dir: Path):
    """
    Ensures no subtitle files (.srt, .vtt, .ass) sit directly in video_dir.
    Migrates any loose subtitles into subtitle_dir, converting .vtt to .srt and unlinking .vtt.
    """
    if not video_dir.exists():
        return
    subtitle_dir.mkdir(parents=True, exist_ok=True)

    # Migrate loose subtitles from video_dir to subtitle_dir
    for sub in list(video_dir.glob("*.vtt")) + list(video_dir.glob("*.srt")) + list(video_dir.glob("*.ass")):
        if sub.is_file() and sub.parent == video_dir:
            dest_srt = subtitle_dir / f"{sub.stem}.srt"
            if sub.suffix.lower() == ".vtt":
                try:
                    text = sub.read_text(encoding="utf-8-sig", errors="replace")
                    srt_text = vtt_to_srt(text) or text
                    dest_srt.write_text(srt_text, encoding="utf-8")
                    sub.unlink(missing_ok=True)
                except Exception:
                    pass
            elif sub.suffix.lower() == ".srt":
                if not dest_srt.exists():
                    shutil.move(str(sub), str(dest_srt))
                else:
                    sub.unlink(missing_ok=True)
            elif sub.suffix.lower() == ".ass":
                if not dest_srt.exists():
                    shutil.move(str(sub), str(subtitle_dir / sub.name))
                else:
                    sub.unlink(missing_ok=True)

    # Also clean any legacy .vtt in subtitle_dir itself by converting to .srt
    for vtt in list(subtitle_dir.glob("*.vtt")):
        if vtt.is_file():
            try:
                dest_srt = subtitle_dir / f"{vtt.stem}.srt"
                text = vtt.read_text(encoding="utf-8-sig", errors="replace")
                srt_text = vtt_to_srt(text) or text
                dest_srt.write_text(srt_text, encoding="utf-8")
                vtt.unlink(missing_ok=True)
            except Exception:
                pass

