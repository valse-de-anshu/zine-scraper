import yt_dlp
import json
import logging
import subprocess
import os
import requests
from pathlib import Path
from typing import Dict, Any, Callable, Optional
from bs4 import BeautifulSoup
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)


def _write_yt_lyrics(audio_path: Path, prefetched_lines: list, source: str) -> None:
    """
    Write pre-fetched LRC lyrics to the correct path beside/inside the audio file.
    If prefetched_lines is empty, falls back to a full auto_fetch call using the file's own tags.
    """
    try:
        from core.lyrics_engine import format_lrc, _lrc_save_path, auto_fetch_lyrics
        if prefetched_lines:
            lrc_path = _lrc_save_path(audio_path)
            if not lrc_path.exists():
                lrc_path.parent.mkdir(parents=True, exist_ok=True)
                lrc_path.write_text(format_lrc(prefetched_lines), encoding="utf-8")
                logger.info(f"Lyrics written to {lrc_path} (source: {source})")
        else:
            # Background thread found nothing; try using embedded file tags
            auto_fetch_lyrics(audio_path)
    except Exception as e:
        logger.debug(f"_write_yt_lyrics error: {e}")


class YoutubeEngine(VideoEngine):
    """
    Extended VideoEngine for YouTube with support for Music mode and Custom Thumbnails.
    Uses ffmpeg subprocess to bake custom covers into media files.
    """

    def _get_channel_pfp_url(self, channel_url: str) -> Optional[str]:
        if not channel_url:
            return None
        try:
            resp = requests.get(channel_url, headers=self.headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Find og:image meta tag
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                return og_image.get('content')
                
            # Fallback to twitter:image
            twitter_image = soup.find('meta', name='twitter:image')
            if twitter_image and twitter_image.get('content'):
                return twitter_image.get('content')
        except Exception as e:
            logger.debug(f"Failed to scrape channel pfp from HTML: {e}")
        return None

    def save_metadata(self, root_dir: Path, info: Dict[str, Any], source: str, skip_cover: bool = False, channel_root: Optional[Path] = None):
        """Saves metadata.json inside .zine/ folder and cover.jpg in channel root content folder."""
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

        if skip_cover:
            return

        # Try to download cover/avatar (Saved in ROOT channel directory as cover.jpg)
        target_cover_dir = channel_root if channel_root else root_dir
        cover_path = target_cover_dir / "cover.jpg"
        
        if not cover_path.exists():
            thumb_url = None
            
            # Scrape the pfp (profile picture) from channel URL if possible
            channel_url = info.get('channel_url') or info.get('uploader_url')
            # If playlist, try to derive channel URL from webpage_url if it is channel-like
            if not channel_url and info.get('_type') == 'playlist' and 'channel' in (info.get('webpage_url') or ''):
                channel_url = info.get('webpage_url')
                
            if channel_url:
                thumb_url = self._get_channel_pfp_url(channel_url)
                
            if not thumb_url:
                thumbnails = info.get('thumbnails', [])
                if thumbnails:
                    # Prioritize square-ish thumbnails (aspect ratio ~1)
                    avatar_thumb = None
                    for thumb in reversed(thumbnails):
                        w = thumb.get('width', 0)
                        h = thumb.get('height', 1)
                        if w > 0 and (w / h) < 1.3: # Allow slight variations
                            avatar_thumb = thumb
                            break
                    
                    if not avatar_thumb:
                        avatar_thumb = thumbnails[-1]
 
                    thumb_url = avatar_thumb.get('url')
 
            if thumb_url:
                try:
                    import requests
                    r = requests.get(thumb_url, timeout=20)
                    r.raise_for_status()
                    
                    ct = r.headers.get("Content-Type", "").lower().split(";")[0].strip()
                    mime_map = {
                        "image/jpeg": ".jpg", "image/jpg": ".jpg",
                        "image/png": ".png", "image/webp": ".webp",
                        "image/avif": ".avif", "image/gif": ".gif"
                    }
                    real_ext = mime_map.get(ct, cover_path.suffix or ".jpg")
                    if cover_path.suffix.lower() != real_ext:
                        cover_path = cover_path.with_suffix(real_ext)
                        
                    with open(cover_path, "wb") as f:
                        f.write(r.content)
                except Exception as e:
                    logger.error(f"Failed to download cover from {thumb_url}: {e}")

    def download_video(
        self, 
        url: str, 
        output_dir: Path, 
        progress_hook: Callable, 
        raw_stream_url: str = None, 
        is_audio: bool = False, 
        custom_thumbnail: Optional[Path] = None, 
        fixed_title: Optional[str] = None, 
        fixed_artist: Optional[str] = None
    ) -> bool:
        """Override base VideoEngine method to use YouTube-specific logic."""
        mode = "music" if is_audio else "video"
        return self.download_youtube(
            url, 
            output_dir, 
            progress_hook, 
            mode=mode, 
            custom_thumbnail=custom_thumbnail,
            fixed_title=fixed_title,
            fixed_artist=fixed_artist
        )

    def download_youtube(
        self, 
        url: str, 
        output_dir: Path, 
        progress_hook: Callable, 
        mode: str = "video", 
        custom_thumbnail: Optional[Path] = None,
        quality: Optional[str] = None,
        audio_format: Optional[str] = None,
        fixed_title: Optional[str] = None,
        fixed_artist: Optional[str] = None
    ) -> bool:
        """
        Main entry point for downloading YouTube content with specific modes and quality.
        """
        is_music = "music" in mode
        videos_dir = output_dir
        videos_dir.mkdir(parents=True, exist_ok=True)

        ext = audio_format.lower() if (is_music and audio_format) else "flac" if is_music else "mp4"
        
        if fixed_title:
            clean_title = "".join([c for c in fixed_title if c.isalnum() or c in " .-_()"]).strip()
        else:
            clean_title = "downloaded_video"

        if custom_thumbnail:
            outtmpl = str(videos_dir / f"{clean_title}.tmp.%(ext)s")
            tmp_path = videos_dir / f"{clean_title}.tmp.{ext}"
        else:
            outtmpl = str(videos_dir / f"{clean_title}.%(ext)s")
            tmp_path = videos_dir / f"{clean_title}.{ext}"

        import tempfile
        import os
        import threading

        # ── Parallel lyrics fetch: start BEFORE yt-dlp so it runs concurrently ──
        prefetched_lrc_lines = []
        prefetched_lrc_source = [None]

        def _bg_lyrics_fetch():
            if not is_music:
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
                logger.debug(f"YT bg lyrics fetch error: {e}")

        if is_music and (fixed_title or fixed_artist):
            lyric_thread = threading.Thread(target=_bg_lyrics_fetch, daemon=True)
            lyric_thread.start()
        else:
            lyric_thread = None

        # Save URL to a temporary batch file to pass to yt-dlp
        temp_batch = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8')
        try:
            temp_batch.write(url + '\n')
            temp_batch.close()
            
            import shutil
            ytdlp_bin = shutil.which("yt-dlp") or "yt-dlp"
            cmd = [
                ytdlp_bin,
                "--batch-file", temp_batch.name,
                "-o", outtmpl,
                "--no-playlist",
                "--retries", "10",
                "--fragment-retries", "10",
                "--concurrent-fragments", "5",
                "--no-check-certificate",
                "--no-warnings",
                "--socket-timeout", "5",
                "--extractor-args", "youtube:player-client=android,web,default"
            ]
            
            for k, v in self.headers.items():
                cmd.extend(["--add-header", f"{k}:{v}"])
                
            if is_music:
                cmd.extend([
                    "-x",
                    "--audio-format", ext,
                    "--audio-quality", "0",
                    "--embed-metadata"
                ])
            else:
                height_map = {
                    "2K": "1440",
                    "1080p": "1080",
                    "720p": "720",
                    "480p": "480",
                    "360p": "360",
                    "240p": "240",
                    "144p": "144"
                }
                h = height_map.get(quality)
                if h:
                    cmd.extend(["-f", f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best"])
                else:
                    cmd.extend(["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"])
                    
                cmd.extend([
                    "--merge-output-format", "mp4",
                    "--embed-metadata"
                ])
                
            if not custom_thumbnail:
                cmd.append("--embed-thumbnail")

            success = self._run_ytdlp_subprocess(cmd, progress_hook, str(tmp_path))
            
            if success:
                # Align extension with selected format if it changed post-download
                final_path = tmp_path
                if is_music and not final_path.exists() and final_path.with_suffix(f".{ext}").exists():
                     final_path = final_path.with_suffix(f".{ext}")
                elif not is_music and not final_path.exists() and final_path.with_suffix(".mp4").exists():
                     final_path = final_path.with_suffix(".mp4")

                if custom_thumbnail and custom_thumbnail.exists():
                    final_thumb_path = final_path.with_name(final_path.name.replace(".tmp.", "."))
                    success = self._apply_custom_thumbnail(final_path, custom_thumbnail, final_thumb_path, is_music)
                    if success:
                        if final_path.exists(): final_path.unlink()
                        if is_music:
                            # Always use real embedded metadata for accurate lyrics search
                            try:
                                from core.lyrics_engine import auto_fetch_lyrics
                                auto_fetch_lyrics(final_thumb_path)
                            except Exception as e:
                                logger.debug(f"Lyrics post-download error: {e}")
                        return True
                    return False
                
                if is_music:
                    # Always use real embedded metadata — parallel thread pre-warmed cache,
                    # now yt-dlp --embed-metadata has baked the REAL title/artist into the file.
                    try:
                        from core.lyrics_engine import auto_fetch_lyrics
                        auto_fetch_lyrics(final_path)
                    except Exception as e:
                        logger.debug(f"Lyrics post-download error: {e}")

                return True
            else:
                return False
        except Exception as e:
            logger.error(f"YouTube Download failed for {url}: {e}")
            return False
        finally:
            if os.path.exists(temp_batch.name):
                try:
                    os.unlink(temp_batch.name)
                except Exception:
                    pass

    def _apply_custom_thumbnail(self, media_path: Path, cover_path: Path, output_path: Path, is_audio: bool) -> bool:
        """Uses ffmpeg to bake the custom cover into the media file."""
        try:
            # Command inspired by the user's dlsong.sh script
            import shutil
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
            cmd = [
                ffmpeg_bin, "-y",
                "-i", str(media_path),
                "-i", str(cover_path),
                "-map", "0:a" if is_audio else "0",
                "-map", "1:0",
                "-c", "copy",
                "-map_metadata", "0",
                "-disposition:v:0", "attached_pic",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
                "-loglevel", "error",
                str(output_path)
            ]
            
            # For video, we might need different mapping if we want to keep all streams
            if not is_audio:
                # For video: map all from 0, then add cover as attached pic
                import shutil
                ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
                cmd = [
                    ffmpeg_bin, "-y",
                    "-i", str(media_path),
                    "-i", str(cover_path),
                    "-map", "0",
                    "-map", "1",
                    "-c", "copy",
                    "-map_metadata", "0",
                    "-disposition:v:1", "attached_pic", # V:1 because V:0 is the video
                    "-loglevel", "error",
                    str(output_path)
                ]

            subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg failed to apply cover: {e}")
            return False
