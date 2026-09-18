import requests
import asyncio
import re
import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from bs4 import BeautifulSoup
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9'
}

from scrapers.playwright_extractor import extract_stream

class AnitakuEngine(VideoEngine):
    def __init__(self):
        super().__init__()

    def resolve_episode_streams(self, episode_url: str) -> list:
        """Intercepts embed URLs from the episode page and resolves all candidate m3u8 streams in priority order."""
        h = HEADERS.copy()
        soup = None
        for attempt in range(3):
            try:
                r = requests.get(episode_url, headers=h, timeout=(10, 30))
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")
                break
            except Exception:
                if attempt == 2:
                    return []
                time.sleep(1.0 * (attempt + 1))
        
        if not soup:
            return []

        embed_items = []
        for li in soup.select(".anime_muti_link ul li a"):
            server_name = li.text.replace("Choose this server", "").strip()
            embed_url = li.get("data-video")
            if embed_url:
                if not embed_url.startswith("http"):
                    embed_url = "https:" + embed_url
                embed_items.append((server_name, embed_url))
                
        def server_priority(item):
            sname, url = item
            # Prioritize bibiemb (HD-2) over vivibebe (HD-1) because bibiemb streams Cloudflare Workers directly
            if "bibiemb" in url: return 0
            if "vivibebe" in url or "vidstreaming" in url: return 1
            if "otakuhg" in url or "streamhg" in url: return 2
            if "mp4upload" in url: return 3
            if "dood" in url: return 4
            if "playmogo" in url: return 5
            return 10
            
        embed_items.sort(key=server_priority)
        candidates = []
        # First pass: Fast direct extraction (bibiemb, vivibebe, vidstreaming, vibe)
        for server_name, embed_url in embed_items:
            if any(k in embed_url for k in ["bibiemb", "vivibebe", "vidstreaming", "vibe"]):
                try:
                    r_embed = None
                    for attempt in range(2):
                        try:
                            r_embed = requests.get(embed_url, headers=h, timeout=(5, 15))
                            r_embed.raise_for_status()
                            break
                        except Exception:
                            time.sleep(0.5)
                    if not r_embed:
                        continue
                    m = re.search(r"const\s+src\s*=\s*['\"](.*?)['\"]", r_embed.text)
                    if m:
                        candidates.append({
                            "m3u8_url": m.group(1),
                            "subtitles": [],
                            "qualities": [],
                            "embed_referer": embed_url,
                            "server_name": server_name or "HD"
                        })
                except Exception as e:
                    logger.debug(f"[AnitakuEngine] Fast extraction error on {embed_url}: {e}")

        # Only fallback to Playwright if zero fast streams could be extracted
        if not candidates:
            for server_name, embed_url in embed_items:
                try:
                    result = asyncio.run(extract_stream(embed_url))
                    stream_url = result.get("url")
                    if stream_url:
                        candidates.append({
                            "m3u8_url": stream_url,
                            "subtitles": result.get("subtitles", []),
                            "qualities": result.get("qualities_urls", []),
                            "embed_referer": embed_url,
                            "server_name": server_name or "Alternative"
                        })
                        break
                except Exception as e:
                    logger.debug(f"[AnitakuEngine] Playwright extraction error on {embed_url}: {e}")
                continue
                
        return candidates

    def resolve_episode_stream(self, episode_url: str) -> dict:
        """Backwards-compatible wrapper returning the top stream candidate."""
        streams = self.resolve_episode_streams(episode_url)
        return streams[0] if streams else None

    def download_video(self, url: str, output_dir: Path, progress_hook=None, raw_stream_url: str = None, is_audio: bool = False, custom_thumbnail: Path = None, fixed_title: str = None, fixed_artist: str = None, format_override: str = None, baking_callback=None, **kwargs) -> bool:
        target = raw_stream_url if raw_stream_url else url
        if target and ".m3u8" in target and not is_audio:
            # We use a blazing fast custom HLS downloader!
            success = self._fast_hls_download(target, output_dir, progress_hook, fixed_title, custom_thumbnail, baking_callback, **kwargs)
            if success:
                return True
            if raw_stream_url:
                return False
            
        # Fallback to base engine
        return super().download_video(url, output_dir, progress_hook, raw_stream_url, is_audio, custom_thumbnail, fixed_title, fixed_artist, format_override, baking_callback, **kwargs)
        
    def _fast_hls_download(self, m3u8_url: str, output_dir: Path, progress_hook, fixed_title, custom_thumbnail, baking_callback, **kwargs) -> bool:
        import m3u8
        import shutil
        import subprocess
        
        videos_dir = output_dir
        videos_dir.mkdir(parents=True, exist_ok=True)
        ext = "mp4"
        clean_title = "".join([c for c in fixed_title if c.isalnum() or c in " .-_()"]).strip() if fixed_title else "downloaded_video"
        
        from core.paths import PathAuthority
        temp_root = PathAuthority().get_temp_root()
        temp_root.mkdir(parents=True, exist_ok=True)
        
        tmp_path = temp_root / f"{clean_title}.{ext}"
        final_dest = videos_dir / f"{clean_title}.{ext}"
        
        parts_dir = temp_root / f"{clean_title}_parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        
        headers = HEADERS.copy()
        # Ensure referer is passed if available in kwargs
        if "embed_referer" in kwargs:
            headers["Referer"] = kwargs["embed_referer"]
            
        def _fetch_m3u8(target_url):
            for attempt in range(3):
                try:
                    r = requests.get(target_url, headers=headers, timeout=(10, 30))
                    r.raise_for_status()
                    return r.text
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(1.0 * (attempt + 1))

        try:
            m3u8_text = _fetch_m3u8(m3u8_url)
            playlist = m3u8.loads(m3u8_text, uri=m3u8_url)
            
            real_url = m3u8_url
            if playlist.is_variant:
                best = playlist.playlists[-1]
                real_url = best.absolute_uri if best.absolute_uri else best.uri
                if not real_url.startswith("http"):
                    real_url = m3u8_url.rsplit("/", 1)[0] + "/" + real_url
                variant_text = _fetch_m3u8(real_url)
                playlist = m3u8.loads(variant_text, uri=real_url)
                
            chunks = []
            for i, segment in enumerate(playlist.segments):
                chunk_url = segment.absolute_uri if segment.absolute_uri else segment.uri
                if not chunk_url.startswith("http"):
                    chunk_url = real_url.rsplit("/", 1)[0] + "/" + chunk_url
                chunks.append((i, chunk_url))
                
            total_chunks = len(chunks)
            if total_chunks == 0:
                return False
                
            downloaded = 0
            
            def download_chunk(i, c_url):
                chunk_path = parts_dir / f"chunk_{i:05d}.ts"
                if chunk_path.exists() and chunk_path.stat().st_size > 0:
                    return True, chunk_path
                    
                for retry in range(4):
                    try:
                        c_resp = requests.get(c_url, headers=headers, timeout=15)
                        if c_resp.status_code != 200 or len(c_resp.content) < 100:
                            time.sleep(1)
                            continue
                        data = c_resp.content
                        if data.startswith(b'\x89PNG\r\n\x1a\n'):
                            iend_pos = data.find(b'IEND\xaeB`\x82')
                            if iend_pos != -1:
                                data = data[iend_pos + 8:]
                        with open(chunk_path, "wb") as f:
                            f.write(data)
                        return True, chunk_path
                    except Exception:
                        time.sleep(1)
                return False, chunk_path

            # Concurrently download chunks
            chunk_paths = [None] * total_chunks
            with ThreadPoolExecutor(max_workers=24) as executor:
                futures = {executor.submit(download_chunk, i, url): i for i, url in chunks}
                for future in as_completed(futures):
                    idx = futures[future]
                    success, path = future.result()
                    if success:
                        chunk_paths[idx] = path
                        downloaded += 1
                        if progress_hook:
                            progress_hook({
                                "status": "downloading",
                                "filename": str(tmp_path),
                                "downloaded_bytes": downloaded,
                                "total_bytes": total_chunks,
                                "speed": 0.0
                            })
                            
            if downloaded < total_chunks * 0.95:
                shutil.rmtree(parts_dir, ignore_errors=True)
                return False
                
            if baking_callback:
                baking_callback()
                
            temp_ts_path = tmp_path.with_suffix(".ts")
            with open(temp_ts_path, "wb") as outfile:
                for path in chunk_paths:
                    if path and path.exists():
                        with open(path, "rb") as infile:
                            shutil.copyfileobj(infile, outfile)
                            
            ffmpeg_bin = shutil.which("ffmpeg")
            if not ffmpeg_bin:
                raise RuntimeError("ffmpeg not found in PATH")
            cmd = [ffmpeg_bin, "-y", "-i", str(temp_ts_path), "-c", "copy", str(tmp_path)]
            subprocess.run(cmd, check=True, capture_output=True, stdin=subprocess.DEVNULL)
            
            temp_ts_path.unlink(missing_ok=True)
            shutil.rmtree(parts_dir, ignore_errors=True)
            
            if tmp_path.exists():
                shutil.move(str(tmp_path), str(final_dest))
                # Cleanup leftover temp files
                for pat in [f"*{clean_title}*"]:
                    for junk in temp_root.glob(pat):
                        if junk != final_dest and not junk.name.endswith('.mp4') and not junk.name.endswith('.flac'):
                            junk.unlink(missing_ok=True)
                return True
                
        except Exception as e:
            logger.debug(f"[AnitakuEngine] HLS Fast download error: {e}")
        finally:
            shutil.rmtree(parts_dir, ignore_errors=True)
            temp_ts_path = tmp_path.with_suffix(".ts")
            temp_ts_path.unlink(missing_ok=True)
        return False
