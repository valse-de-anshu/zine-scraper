import yt_dlp
import json
import logging
from pathlib import Path
from typing import Dict, Any, Callable, Optional
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
            'ignoreerrors': True, # We handle errors via file verification
            'retries': 10,
            'fragment_retries': 10,
            'timeout': 60,
            'http_headers': self.headers,
            'concurrent_fragment_downloads': 5,
            'buffersize': 1024 * 1024,
            'http_chunk_size': 1048576,
        }

    def extract_playlist_info(self, url: str, playlist_limit: Optional[int] = None, playlist_start: Optional[int] = None) -> Dict[str, Any]:
        """Extracts flat info for a playlist or channel to get total counts and metadata."""
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
                playlist_limit = config.get("playlist_max_items", 100)
            except Exception:
                playlist_limit = 100

        if playlist_limit and playlist_limit > 0:
            ydl_opts['playlistend'] = playlist_limit

        if playlist_start and playlist_start > 0:
            ydl_opts['playliststart'] = playlist_start

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def extract_video_info(self, url: str, fast: bool = False) -> Dict[str, Any]:
        """Extracts full info for a single video."""
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
                'source_address': '0.0.0.0',
            })
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def download_video(self, url: str, output_dir: Path, progress_hook: Callable, raw_stream_url: str = None, is_audio: bool = False, custom_thumbnail: Path = None, fixed_title: str = None, fixed_artist: str = None, format_override: str = None, baking_callback: Callable = None) -> bool:
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
                "--write-subs",
                "--write-auto-subs",
                "--all-subs",
                "--embed-subs",
                "--retries", "10",
                "--fragment-retries", "10",
                "--concurrent-fragments", "16",
                "--no-check-certificate",
                "--no-warnings",
                "--socket-timeout", "5"
            ]
            
            if shutil.which("aria2c"):
                cmd.extend([
                    "--downloader", "aria2c",
                    "--downloader-args", "aria2c:-x 16 -s 16 -k 1M --file-allocation=none"
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
                    
                    if custom_thumbnail and custom_thumbnail.exists():
                        self._apply_custom_metadata(real_final_dest, custom_thumbnail, is_audio, fixed_title, fixed_artist)
                    
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

    def _apply_custom_metadata(self, media_path: Path, cover_path: Path, is_audio: bool, title: str = None, artist: str = None):
        """Uses ffmpeg to bake the custom cover AND forced metadata into the media file."""
        import subprocess
        try:
            tmp_path = media_path.with_suffix(".meta.tmp" + media_path.suffix)
            
            import shutil
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
            cmd = [ffmpeg_bin, "-y", "-i", str(media_path)]
            if cover_path and cover_path.exists():
                cmd.extend(["-i", str(cover_path)])
            
            # Map streams
            if cover_path and cover_path.exists():
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

            # Cover disposition
            if cover_path and cover_path.exists():
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

    def save_metadata(self, root_dir: Path, info: Dict[str, Any], source: str, cover_url: Optional[str] = None):
        """Saves metadata.json inside .zine/ folder and cover.jpg in root content folder."""
        from core.history import _is_quick_grab_dir
        if _is_quick_grab_dir(root_dir):
            return
            
        if source.lower() not in ["idagio", "soundcloud", "music"]:
            meta_dir = root_dir / ".zine"
            meta_dir.mkdir(parents=True, exist_ok=True)
            
            meta_path = meta_dir / "metadata.json"
            
            # Migration: Move metadata.json from root or metadata/ if it exists
            for old_loc in [root_dir / "metadata.json", root_dir / "metadata" / "metadata.json"]:
                if old_loc.exists() and not meta_path.exists():
                    try:
                        old_loc.rename(meta_path)
                    except Exception: pass
            
            # Only overwrite metadata if we are processing a playlist/channel, or if it doesn't exist.
            if not meta_path.exists() or info.get('_type') == 'playlist':
                metadata = {
                    "channel_name": info.get('uploader') or info.get('channel') or info.get('title') or "Unknown",
                    "channel_id": info.get('uploader_id') or info.get('channel_id') or info.get('id') or "Unknown",
                    "source": source,
                    "url": info.get('webpage_url') or info.get('original_url') or "",
                    "total_videos": len(info.get('entries', [])) if info.get('_type') == 'playlist' else 1,
                    "description": info.get('description', ''),
                }
                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)

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

            from urllib.parse import urlparse
            ext = Path(urlparse(thumb_url).path).suffix or ".jpg"
            cover_path = root_dir / f"cover{ext}"
            if not cover_path.exists():
                try:
                    resp = requests.get(thumb_url, headers=self.headers, timeout=15)
                    resp.raise_for_status()
                    with open(cover_path, 'wb') as f:
                        f.write(resp.content)
                except Exception as e:
                    logger.error(f"Failed to download cover from {thumb_url}: {e}")

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
            
            project_root = Path(__file__).parent.parent
            import sys
            venv_python = sys.executable
            script_path = project_root / "scrapers" / "hls_extractor.py"
            
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
