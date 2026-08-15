"""
scrapers/anikai/engine.py
──────────────────────────
Anikai download engine. Subclasses VideoEngine and adds:
  1. resolve_episode_stream()  – reads the data-video embed URLs baked into
     the watch page HTML and, for vivibebe/vidstreaming, extracts the m3u8
     directly from the embed page JS (no Playwright needed).
  2. download_video()          – routes m3u8 streams through the blazing-fast
     custom HLS downloader (same logic as AnitakuEngine) with PNG-header stripping.
  3. _fast_hls_download()      – concurrent chunk downloader + ffmpeg muxing.
"""

import re
import os
import time
import requests
import asyncio
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

from core.video_engine import VideoEngine

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}


def _server_priority(url: str) -> int:
    """Prefer vivibebe first (we have a direct regex extractor). Fallback chain after that."""
    if "vivibebe" in url or "vidstreaming" in url:
        return 0
    if "otakuhg" in url or "streamhg" in url:
        return 1
    if "otakuvid" in url or "earnvids" in url:
        return 2
    if "playmogo" in url or "dood" in url:
        return 3
    return 10


class AnikaiEngine(VideoEngine):
    """
    Anikai specific extraction and fast-download engine.
    """
    def __init__(self):
        super().__init__()

    # ──────────────────────────────────────────────────────────────────────────
    # Stream resolution
    # ──────────────────────────────────────────────────────────────────────────

    def resolve_episode_stream(self, episode_url: str) -> dict | None:
        """
        Fetches the watch page for *episode_url*, collects all data-video embed
        URLs, sorts them by server priority, and resolves an m3u8 stream URL.

        For vivibebe/vidstreaming we directly regex the embed page JS for
        `const src = "..."` — instant, no Playwright overhead.
        For everything else we fall back to the shared Playwright extractor.
        """
        h = HEADERS.copy()

        try:
            r = requests.get(episode_url, headers=h, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            return None

        # Collect all embed URLs from data-video attributes
        embed_entries = []
        for a in soup.select(".server-video.server"):
            data_video = a.get("data-video", "").strip()
            if not data_video:
                continue
            tab = a.get("data-tab", "")
            embed_entries.append((data_video, tab))

        if not embed_entries:
            return None

        # Sort: prefer vivibebe, then streamhg, etc.
        embed_entries.sort(key=lambda e: _server_priority(e[0]))

        for embed_url, tab in embed_entries:
            try:
                # ── vivibebe / vidstreaming: direct regex extraction ──────────
                if "vivibebe" in embed_url or "vidstreaming" in embed_url:
                    r_embed = requests.get(embed_url, headers=h, timeout=12)
                    # Extract subtitle VTT if embedded in the URL query string
                    sub_match = re.search(r'[?&]sub=([^&]+)', embed_url)
                    subtitle_url = sub_match.group(1) if sub_match else None

                    # Try `const src = "..."` pattern first
                    m = re.search(r"const\s+src\s*=\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", r_embed.text)
                    if not m:
                        # Some pages use `file: "..."` inside a sources array
                        m = re.search(r"['\"]file['\"]\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", r_embed.text)
                    if m:
                        subtitles = []
                        if subtitle_url:
                            subtitles.append({"url": subtitle_url, "label": "English"})
                        return {
                            "m3u8_url": m.group(1),
                            "subtitles": subtitles,
                            "qualities": [],
                            "embed_referer": embed_url,
                        }
                    else:
                        if "cloudflare" in r_embed.text.lower() or "just a moment" in r_embed.text.lower():
                            raise RuntimeError("Cloudflare block detected on video server")
                        # If regex failed but no block, let it fall through to Playwright

                # ── All other servers: Playwright fallback ───────────────────
                from scrapers.playwright_extractor import extract_stream
                result = asyncio.run(extract_stream(embed_url))
                stream_url = result.get("url")
                if stream_url:
                    return {
                        "m3u8_url": stream_url,
                        "subtitles": result.get("subtitles", []),
                        "qualities": result.get("qualities_urls", []),
                        "embed_referer": embed_url,
                    }

            except Exception as e:
                print(f"[AnikaiEngine] Server {embed_url} failed: {e}")
                continue

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Download routing
    # ──────────────────────────────────────────────────────────────────────────

    def download_video(
        self, url: str, output_dir: Path, progress_hook=None,
        raw_stream_url: str = None, is_audio: bool = False,
        custom_thumbnail: Path = None, fixed_title: str = None,
        fixed_artist: str = None, format_override: str = None,
        baking_callback=None, **kwargs
    ) -> bool:
        target = raw_stream_url if raw_stream_url else url
        if ".m3u8" in target and not is_audio:
            success = self._fast_hls_download(
                target, output_dir, progress_hook,
                fixed_title, custom_thumbnail, baking_callback, **kwargs
            )
            if success:
                return True
        # Fallback to base VideoEngine (yt-dlp subprocess)
        return super().download_video(
            url, output_dir, progress_hook, raw_stream_url, is_audio,
            custom_thumbnail, fixed_title, fixed_artist, format_override,
            baking_callback, **kwargs
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Blazing-fast concurrent HLS downloader (vivibebe CDN with PNG-header stripping)
    # ──────────────────────────────────────────────────────────────────────────

    def _fast_hls_download(
        self, m3u8_url: str, output_dir: Path, progress_hook,
        fixed_title, custom_thumbnail, baking_callback, **kwargs
    ) -> bool:
        output_dir.mkdir(parents=True, exist_ok=True)
        clean_title = (
            "".join(c for c in fixed_title if c.isalnum() or c in " .-_()").strip()
            if fixed_title else "downloaded_video"
        )

        from core.paths import PathAuthority
        temp_root = PathAuthority().get_temp_root()
        temp_root.mkdir(parents=True, exist_ok=True)

        tmp_path   = temp_root / f"{clean_title}.mp4"
        final_dest = output_dir / f"{clean_title}.mp4"
        parts_dir  = temp_root / f"{clean_title}_parts"
        parts_dir.mkdir(parents=True, exist_ok=True)

        headers = self.headers.copy()
        if "embed_referer" in kwargs:
            headers["Referer"] = kwargs["embed_referer"]

        from urllib.parse import urljoin
        import re

        try:
            resp = requests.get(m3u8_url, headers=headers, timeout=15)
            lines = resp.text.splitlines()

            # If this is a master playlist, pick the highest-bandwidth variant
            real_url = m3u8_url
            if any(line.startswith("#EXT-X-STREAM-INF") for line in lines):
                best_bandwidth = -1
                best_uri = None
                for i, line in enumerate(lines):
                    if line.startswith("#EXT-X-STREAM-INF"):
                        bw_match = re.search(r"BANDWIDTH=(\d+)", line)
                        bw = int(bw_match.group(1)) if bw_match else 0
                        # The next non-empty line should be the URI
                        uri = None
                        for next_line in lines[i+1:]:
                            next_line = next_line.strip()
                            if next_line and not next_line.startswith("#"):
                                uri = next_line
                                break
                        
                        if uri and bw > best_bandwidth:
                            best_bandwidth = bw
                            best_uri = uri
                
                if best_uri:
                    real_url = urljoin(m3u8_url, best_uri)
                    resp = requests.get(real_url, headers=headers, timeout=15)
                    lines = resp.text.splitlines()

            # Build chunk list
            chunks = []
            chunk_idx = 0
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#"):
                    chunk_url = urljoin(real_url, line)
                    chunks.append((chunk_idx, chunk_url))
                    chunk_idx += 1

            total_chunks = len(chunks)
            if total_chunks == 0:
                raise RuntimeError("No chunks found in M3U8 playlist (possible 403 or geo-block)")

            downloaded = 0

            def download_chunk(idx: int, c_url: str):
                chunk_path = parts_dir / f"chunk_{idx:05d}.ts"
                if chunk_path.exists() and chunk_path.stat().st_size > 0:
                    return True, chunk_path
                for _ in range(4):
                    try:
                        c_resp = requests.get(c_url, headers=headers, timeout=20)
                        data = c_resp.content
                        # Strip obfuscated PNG header (vivibebe CDN protection)
                        if data.startswith(b'\x89PNG\r\n\x1a\n'):
                            iend_pos = data.find(b'IEND\xaeB`\x82')
                            if iend_pos != -1:
                                data = data[iend_pos + 8:]
                        chunk_path.write_bytes(data)
                        return True, chunk_path
                    except Exception:
                        time.sleep(1)
                return False, chunk_path

            chunk_paths = [None] * total_chunks
            with ThreadPoolExecutor(max_workers=24) as executor:
                futures = {executor.submit(download_chunk, i, u): i for i, u in chunks}
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
                                "speed": 0.0,
                            })

            if downloaded < total_chunks * 0.95:
                raise RuntimeError(f"Download incomplete: {downloaded}/{total_chunks} chunks downloaded")

            if baking_callback:
                baking_callback()

            # Concatenate chunks into a single .ts then mux to .mp4
            temp_ts = tmp_path.with_suffix(".ts")
            with open(temp_ts, "wb") as outfile:
                for path in chunk_paths:
                    if path and path.exists():
                        with open(path, "rb") as infile:
                            shutil.copyfileobj(infile, outfile)

            ffmpeg_bin = shutil.which("ffmpeg")
            if not ffmpeg_bin:
                raise RuntimeError("ffmpeg not found in PATH")
            subprocess.run(
                [ffmpeg_bin, "-y", "-i", str(temp_ts), "-c", "copy", str(tmp_path)],
                check=True, capture_output=True, stdin=subprocess.DEVNULL
            )
            temp_ts.unlink(missing_ok=True)
            shutil.rmtree(parts_dir, ignore_errors=True)

            if tmp_path.exists():
                shutil.move(str(tmp_path), str(final_dest))
                # Tidy temp root
                for junk in temp_root.glob(f"*{clean_title}*"):
                    if junk != final_dest and not junk.suffix in (".mp4", ".flac"):
                        junk.unlink(missing_ok=True)
                return True

        except Exception as e:
            # Re-raise so the UI can display the exact failure reason (e.g. missing module)
            raise RuntimeError(f"HLS Engine Error: {e}")
            
        return False
