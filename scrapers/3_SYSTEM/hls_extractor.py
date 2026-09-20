"""
scrapers/3_SYSTEM/hls_extractor.py
───────────────────────────────────
High-speed parallel HLS stream extractor and downloader.
Supports AES-128 decryption, PNG header stripping, and direct ffmpeg muxing.

Strategy:
- Uses curl_cffi per-thread sessions with browser impersonation to bypass CDN blocks.
- Streams each segment with chunked reads (no total-transfer timeout).
- 64 concurrent workers for maximum throughput on throttled CDNs.
- Retries on transient errors with backoff.
"""

import sys
import os
import json
import time
import re
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

from Crypto.Cipher import AES

# Thread-local storage for per-thread curl_cffi sessions
_tls = threading.local()

def _get_session():
    """Get or create a per-thread curl_cffi session."""
    if not hasattr(_tls, 'session') or _tls.session is None:
        from curl_cffi.requests import Session
        _tls.session = Session(impersonate="chrome124")
    return _tls.session


def _stream_get(url: str, headers: dict, connect_timeout: int = 15, chunk_timeout: int = 30) -> bytes:
    """
    Download URL with streaming, using per-thread sessions.
    Uses chunked reading to avoid total-transfer timeouts on slow CDNs.
    connect_timeout: seconds to wait for connection
    chunk_timeout: seconds to wait for each chunk read
    """
    session = _get_session()
    chunks = []
    
    # curl_cffi stream=True uses connect timeout only; reads happen in chunks
    resp = session.get(
        url,
        headers=headers,
        stream=True,
        timeout=(connect_timeout, chunk_timeout),
    )
    resp.raise_for_status()
    
    for chunk in resp.iter_content(chunk_size=65536):
        if chunk:
            chunks.append(chunk)
    
    return b"".join(chunks)


def download_hls(playlist_url: str, target_path_str: str, headers: dict):
    tmp_path = Path(target_path_str)

    clean_headers = {
        'User-Agent': headers.get(
            'User-Agent',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    for k, v in headers.items():
        if k.lower() in ("referer", "origin", "cookie", "authorization"):
            clean_headers[k] = v

    # ── Fetch playlist ──────────────────────────────────────────────────────
    playlist_bytes = _stream_get(playlist_url, clean_headers)
    playlist_text  = playlist_bytes.decode("utf-8", errors="ignore")

    # If master playlist, resolve to best variant
    target_stream_url = playlist_url
    if "#EXT-X-STREAM-INF" in playlist_text:
        streams = []
        lines = playlist_text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:"):
                bw_m = re.search(r'BANDWIDTH=(\d+)', line)
                bw   = int(bw_m.group(1)) if bw_m else 0
                if i + 1 < len(lines):
                    streams.append((bw, lines[i + 1].strip()))
        if streams:
            streams.sort(key=lambda x: x[0], reverse=True)
            target_stream_url = urljoin(playlist_url, streams[0][1])
            playlist_bytes = _stream_get(target_stream_url, clean_headers)
            playlist_text  = playlist_bytes.decode("utf-8", errors="ignore")

    # ── Parse segments ──────────────────────────────────────────────────────
    segment_uris: list  = []
    aes_key:      bytes = None
    aes_iv:       bytes = None
    media_sequence: int = 0
    init_segment_url:   str = None

    for line in playlist_text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(line.split(":")[1])
            except Exception:
                pass
        elif line.startswith("#EXT-X-MAP:"):
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                raw = uri_match.group(1)
                if raw.startswith("//"):
                    init_segment_url = "https:" + raw
                elif not raw.startswith("http"):
                    init_segment_url = urljoin(target_stream_url, raw)
                else:
                    init_segment_url = raw
        elif line.startswith("#EXT-X-KEY"):
            if "METHOD=AES-128" in line:
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    key_url = uri_match.group(1)
                    if not key_url.startswith("http"):
                        key_url = urljoin(target_stream_url, key_url)
                    aes_key = _stream_get(key_url, clean_headers)
                iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', line)
                if iv_match:
                    aes_iv = bytes.fromhex(iv_match.group(1))
        elif line and not line.startswith("#"):
            if line.startswith("//"):
                full_u = "https:" + line
            elif not line.startswith("http"):
                full_u = urljoin(target_stream_url, line)
            else:
                full_u = line
            segment_uris.append(full_u)

    total_segments = len(segment_uris)
    if total_segments == 0:
        return

    # ── Scratch directory ────────────────────────────────────────────────────
    parts_dir = tmp_path.parent / f"{tmp_path.stem}_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    # Resume support: skip already-completed segments
    downloaded_bytes = [0] * total_segments
    for i in range(total_segments):
        fp = parts_dir / f"frag_{i:05d}.ts"
        if fp.exists() and fp.stat().st_size > 0:
            downloaded_bytes[i] = fp.stat().st_size

    completed_count = sum(1 for b in downloaded_bytes if b > 0)
    start_time      = time.time()
    lock            = threading.Lock()

    # Download init segment if present
    if init_segment_url:
        init_path = parts_dir / "init.mp4"
        if not init_path.exists():
            for _ in range(3):
                try:
                    data = _stream_get(init_segment_url, clean_headers)
                    init_path.write_bytes(data)
                    break
                except Exception:
                    time.sleep(1)

    # ── Worker ───────────────────────────────────────────────────────────────
    PNG_HEADER   = b'\x89PNG\r\n\x1a\n'
    IEND_MARKER  = b'IEND\xaeB`\x82'

    def download_segment(item):
        nonlocal completed_count
        index, url = item
        frag_path   = parts_dir / f"frag_{index:05d}.ts"

        if frag_path.exists() and frag_path.stat().st_size > 0:
            return True

        for attempt in range(6):
            try:
                content = _stream_get(url, clean_headers, connect_timeout=20, chunk_timeout=60)

                # Strip PNG wrapper (KAA CDN disguises TS segments as .jpg/PNG)
                if content.startswith(PNG_HEADER):
                    marker_idx = content.find(IEND_MARKER)
                    if marker_idx != -1:
                        content = content[marker_idx + len(IEND_MARKER):]

                # AES-128 decryption
                if aes_key:
                    seg_iv = aes_iv if aes_iv else (media_sequence + index).to_bytes(16, 'big')
                    cipher  = AES.new(aes_key, AES.MODE_CBC, seg_iv)
                    content = cipher.decrypt(content)
                    if content:
                        pad = content[-1]
                        if pad <= 16:
                            content = content[:-pad]

                frag_path.write_bytes(content)

                with lock:
                    downloaded_bytes[index] = len(content)
                    completed_count += 1
                    cur_dl  = sum(downloaded_bytes)
                    avg_seg = cur_dl / completed_count if completed_count > 0 else 0
                    est_tot = int(avg_seg * total_segments) if avg_seg > 0 else cur_dl * 2
                    elapsed = time.time() - start_time
                    spd     = cur_dl / elapsed if elapsed > 0 else 0.0

                print(json.dumps({
                    "status":           "downloading",
                    "filename":         str(tmp_path),
                    "downloaded_bytes": cur_dl,
                    "total_bytes":      est_tot,
                    "speed":            spd,
                }), flush=True)
                return True

            except Exception as exc:
                wait = min(0.5 * (attempt + 1), 4.0)
                time.sleep(wait)

        return False

    # ── Thread pool: 64 workers ─────────────────────────────────────────────
    items_to_download = [
        (i, u) for i, u in enumerate(segment_uris) if downloaded_bytes[i] == 0
    ]

    if items_to_download:
        with ThreadPoolExecutor(max_workers=64) as executor:
            list(executor.map(download_segment, items_to_download))

    # ── Completion check ────────────────────────────────────────────────────
    final_completed = sum(1 for b in downloaded_bytes if b > 0)
    if total_segments > 0 and (final_completed / total_segments) < 0.90:
        print(json.dumps({
            "error": f"Failed to download sufficient segments ({final_completed}/{total_segments})"
        }), flush=True)
        shutil.rmtree(parts_dir, ignore_errors=True)
        sys.exit(1)

    # ── Mux segments via ffmpeg ─────────────────────────────────────────────
    print(json.dumps({
        "status": "baking", "baking": True, "done": False,
        "total_bytes": 1, "downloaded_bytes": 1
    }), flush=True)

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg_bin, "-y", "-i", "pipe:0", "-c", "copy", str(tmp_path)]
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        if init_segment_url:
            init_path = parts_dir / "init.mp4"
            if init_path.exists():
                with open(init_path, "rb") as f:
                    shutil.copyfileobj(f, process.stdin)
        for i in range(total_segments):
            fp = parts_dir / f"frag_{i:05d}.ts"
            if fp.exists():
                with open(fp, "rb") as f:
                    shutil.copyfileobj(f, process.stdin)
    finally:
        process.stdin.close()
        process.wait()

    if parts_dir.exists():
        shutil.rmtree(parts_dir, ignore_errors=True)


# ── CLI entry point ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(1)

    playlist_url = sys.argv[1]
    target_path  = sys.argv[2]

    import base64
    headers = json.loads(base64.b64decode(sys.argv[3]).decode("utf-8"))

    try:
        download_hls(playlist_url, target_path, headers)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
