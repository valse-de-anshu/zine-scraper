import requests
import asyncio
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from bs4 import BeautifulSoup
from core.video_engine import VideoEngine

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9'
}

from scrapers.playwright_extractor import extract_stream

class AnitakuEngine(VideoEngine):
    def __init__(self):
        super().__init__()
        
    def resolve_episode_stream(self, episode_url: str) -> dict:
        """Intercepts embed URLs from the episode page and resolves m3u8."""
        h = HEADERS.copy()
        r = requests.get(episode_url, headers=h)
        soup = BeautifulSoup(r.text, "lxml")
        
        embed_urls = []
        for li in soup.select(".anime_muti_link ul li a"):
            embed_url = li.get("data-video")
            if embed_url:
                if not embed_url.startswith("http"):
                    embed_url = "https:" + embed_url
                embed_urls.append(embed_url)
                
        # We prioritize vivibebe/vidstreaming because we have a FAST custom extractor for it now!
        def server_priority(url):
            if "vivibebe" in url or "vidstreaming" in url: return 0
            if "otakuhg" in url or "streamhg" in url: return 1
            if "mp4upload" in url: return 2
            if "dood" in url: return 3
            if "playmogo" in url: return 4
            return 10
            
        embed_urls.sort(key=server_priority)
                
        if not embed_urls:
            return None
            
        for embed_url in embed_urls:
            try:
                # Fast direct extraction for vivibebe/vidstreaming
                if "vivibebe" in embed_url or "vidstreaming" in embed_url:
                    r_embed = requests.get(embed_url, headers=h, timeout=10)
                    m = re.search(r"const\s+src\s*=\s*['\"](.*?)['\"]", r_embed.text)
                    if m:
                        return {
                            "m3u8_url": m.group(1),
                            "subtitles": [],
                            "qualities": [],
                            "embed_referer": embed_url
                        }
                
                # Fallback to Playwright
                result = asyncio.run(extract_stream(embed_url))
                stream_url = result.get("url")
                if stream_url:
                    return {
                        "m3u8_url": stream_url,
                        "subtitles": result.get("subtitles", []),
                        "qualities": result.get("qualities_urls", []),
                        "embed_referer": embed_url
                    }
            except Exception as e:
                print(f"[AnitakuEngine] Extraction error on {embed_url}: {e}")
                continue
        return None

    def download_video(self, url: str, output_dir: Path, progress_hook=None, raw_stream_url: str = None, is_audio: bool = False, custom_thumbnail: Path = None, fixed_title: str = None, fixed_artist: str = None, format_override: str = None, baking_callback=None, **kwargs) -> bool:
        target = raw_stream_url if raw_stream_url else url
        if ".m3u8" in target and not is_audio:
            # We use a blazing fast custom HLS downloader!
            success = self._fast_hls_download(target, output_dir, progress_hook, fixed_title, custom_thumbnail, baking_callback, **kwargs)
            if success:
                return True
            
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
            
        try:
            resp = requests.get(m3u8_url, headers=headers, timeout=15)
            playlist = m3u8.loads(resp.text, uri=m3u8_url)
            
            real_url = m3u8_url
            if playlist.is_variant:
                best = playlist.playlists[-1]
                real_url = best.absolute_uri if best.absolute_uri else best.uri
                if not real_url.startswith("http"):
                    real_url = m3u8_url.rsplit("/", 1)[0] + "/" + real_url
                resp = requests.get(real_url, headers=headers, timeout=15)
                playlist = m3u8.loads(resp.text, uri=real_url)
                
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
            print(f"HLS Fast download failed: {e}")
        return False
