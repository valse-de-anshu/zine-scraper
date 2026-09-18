import sys
import json
import time
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests
from Crypto.Cipher import AES

def download_hls(playlist_url, target_path_str, headers):
    tmp_path = Path(target_path_str)
    
    # Strip user-agent and accept so curl_cffi's perfect impersonation isn't broken
    clean_headers = {k: v for k, v in headers.items() if k.lower() in ("referer", "origin", "user-agent")}

    r = requests.get(playlist_url, headers=clean_headers, impersonate="chrome124", timeout=15)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}: {r.text}")

    target_stream_url = playlist_url
    if "#EXT-X-STREAM-INF" in r.text:
        streams = []
        lines = r.text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:"):
                bw_m = re.search(r'BANDWIDTH=(\d+)', line)
                bw = int(bw_m.group(1)) if bw_m else 0
                if i + 1 < len(lines):
                    streams.append((bw, lines[i+1].strip()))
        if streams:
            streams.sort(key=lambda x: x[0], reverse=True)
            target_stream_url = urljoin(playlist_url, streams[0][1])
        r = requests.get(target_stream_url, headers=clean_headers, impersonate="chrome124", timeout=15)
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}: {r.text}")

    segment_uris = []
    aes_key = None
    aes_iv = None
    media_sequence = 0
    init_segment_url = None

    for line in r.text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try: media_sequence = int(line.split(":")[1])
            except Exception: pass
        elif line.startswith("#EXT-X-MAP:"):
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                key_url = uri_match.group(1)
                if not key_url.startswith("http"):
                    key_url = urljoin(target_stream_url, key_url)
                init_segment_url = key_url
        elif line.startswith("#EXT-X-KEY"):
            if "METHOD=AES-128" in line:
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    key_url = uri_match.group(1)
                    if not key_url.startswith("http"):
                        key_url = urljoin(target_stream_url, key_url)
                    aes_key = requests.get(key_url, headers=clean_headers, impersonate="chrome124", timeout=45).content
                iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', line)
                if iv_match:
                    aes_iv = bytes.fromhex(iv_match.group(1))
        elif line and not line.startswith('#'):
            segment_uris.append(urljoin(target_stream_url, line))

    total_segments = len(segment_uris)
    import os
    if os.environ.get("ZINE_TEST_LIMIT_SEGMENTS"):
        limit = int(os.environ.get("ZINE_TEST_LIMIT_SEGMENTS"))
        segment_uris = segment_uris[:limit]
        total_segments = len(segment_uris)
    
    if total_segments == 0:
        return

    parts_dir = tmp_path.parent / f"{tmp_path.stem}_parts"
    
    if parts_dir.exists():
        test_frag = next(parts_dir.glob("frag_*.ts"), None)
        if test_frag and test_frag.exists() and test_frag.stat().st_size > 0:
            with open(test_frag, 'rb') as f:
                if f.read(1) != b'\x47':
                    import shutil
                    shutil.rmtree(parts_dir, ignore_errors=True)

    parts_dir.mkdir(parents=True, exist_ok=True)
    downloaded_bytes = [0] * total_segments

    for i in range(total_segments):
        frag_path = parts_dir / f"frag_{i:05d}.ts"
        if frag_path.exists():
            downloaded_bytes[i] = frag_path.stat().st_size

    completed_segments = sum(1 for b in downloaded_bytes if b > 0)
    start_time = time.time()
    estimated_total_bytes = 0
    failed_segments = [0]

    if init_segment_url:
        init_path = parts_dir / "init.mp4"
        if not init_path.exists():
            for _ in range(5):
                try:
                    ir = requests.get(init_segment_url, headers=clean_headers, impersonate="chrome124", timeout=30)
                    if ir.status_code == 200:
                        with open(init_path, 'wb') as f:
                            f.write(ir.content)
                        break
                except Exception:
                    time.sleep(2)

    def download_segment(url, index):
        nonlocal completed_segments, estimated_total_bytes
        frag_path = parts_dir / f"frag_{index:05d}.ts"
        if frag_path.exists():
            current_downloaded = sum(downloaded_bytes)
            lock_threshold = max(3, int(total_segments * 0.05))
            if completed_segments >= lock_threshold and estimated_total_bytes == 0:
                avg_segment = current_downloaded / completed_segments
                estimated_total_bytes = int(avg_segment * total_segments)
            estimated_total = estimated_total_bytes if estimated_total_bytes > 0 else current_downloaded * 2
            
            print(json.dumps({
                "status": "downloading",
                "filename": str(tmp_path),
                "downloaded_bytes": current_downloaded,
                "total_bytes": estimated_total,
                "speed": 0.0
            }), flush=True)
            return True

        for attempt in range(10):
            try:
                resp = requests.get(url, headers=clean_headers, impersonate="chrome124", timeout=60)
                if resp.status_code in (429, 503, 502, 504):
                    time.sleep(5.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                content = resp.content

                png_header = b'\x89PNG\r\n\x1a\n'
                iend_marker = b'IEND\xae\x42\x60\x82'
                if content.startswith(png_header):
                    marker_idx = content.find(iend_marker)
                    if marker_idx != -1:
                        content = content[marker_idx + len(iend_marker):]

                if aes_key:
                    segment_iv = aes_iv if aes_iv else (media_sequence + index).to_bytes(16, 'big')
                    cipher = AES.new(aes_key, AES.MODE_CBC, segment_iv)
                    content = cipher.decrypt(content)
                    if content:
                        padding_len = content[-1]
                        if padding_len <= 16:
                            content = content[:-padding_len]

                with open(frag_path, 'wb') as f:
                    f.write(content)

                downloaded_bytes[index] = len(content)
                completed_segments += 1

                current_downloaded = sum(downloaded_bytes)
                lock_threshold = max(3, int(total_segments * 0.05))
                if completed_segments >= lock_threshold and estimated_total_bytes == 0:
                    avg_segment = current_downloaded / completed_segments
                    estimated_total_bytes = int(avg_segment * total_segments)

                estimated_total = estimated_total_bytes if estimated_total_bytes > 0 else current_downloaded * 2
                elapsed = time.time() - start_time
                speed = current_downloaded / elapsed if elapsed > 0 else 0.0

                print(json.dumps({
                    "status": "downloading",
                    "filename": str(tmp_path),
                    "downloaded_bytes": current_downloaded,
                    "total_bytes": estimated_total,
                    "speed": speed
                }), flush=True)
                return True
            except Exception as e:
                if attempt == 9:
                    failed_segments[0] += 1
                    if failed_segments[0] > max(20, int(total_segments * 0.15)):
                        import shutil
                        shutil.rmtree(parts_dir, ignore_errors=True)
                        sys.exit(1)
                    return False
                time.sleep(2.0 * (attempt + 1))
        return False

    import shutil
    if shutil.which('aria2c'):
        aria_input = parts_dir / "aria2.txt"
        with open(aria_input, "w") as f:
            for i, url in enumerate(segment_uris):
                frag_path = parts_dir / f"frag_{i:05d}.ts"
                if not frag_path.exists():
                    f.write(f"{url}\n")
                    f.write(f"  out=frag_{i:05d}.enc\n")
                    for k, v in clean_headers.items():
                        f.write(f"  header={k}: {v}\n")
        
        if aria_input.stat().st_size > 0:
            import shutil
            aria_bin = shutil.which("aria2c") or "aria2c"
            cmd = [aria_bin, "-i", str(aria_input), "-d", str(parts_dir), "-j", "64", "-x", "2", "-s", "2", "--optimize-concurrent-downloads=true", "--file-allocation=none", "--allow-overwrite=true", "--auto-file-renaming=false", "--connect-timeout=5", "--timeout=10", "--max-tries=3"]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            def process_enc_file(i):
                enc_path = parts_dir / f"frag_{i:05d}.enc"
                frag_path = parts_dir / f"frag_{i:05d}.ts"
                if enc_path.exists() and not frag_path.exists():
                    with open(enc_path, 'rb') as f:
                        content = f.read()
                    
                    png_header = b'\x89PNG\r\n\x1a\n'
                    iend_marker = b'IEND\xae\x42\x60\x82'
                    if content.startswith(png_header):
                        marker_idx = content.find(iend_marker)
                        if marker_idx != -1:
                            content = content[marker_idx + len(iend_marker):]

                    if aes_key:
                        segment_iv = aes_iv if aes_iv else (media_sequence + i).to_bytes(16, 'big')
                        cipher = AES.new(aes_key, AES.MODE_CBC, segment_iv)
                        content = cipher.decrypt(content)
                        if content:
                            padding_len = content[-1]
                            if padding_len <= 16:
                                content = content[:-padding_len]

                    with open(frag_path, 'wb') as f:
                        f.write(content)
                    downloaded_bytes[i] = len(content)
                    enc_path.unlink()

            with ThreadPoolExecutor(max_workers=16) as dec_executor:
                for _ in dec_executor.map(process_enc_file, range(total_segments)):
                    pass

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(download_segment, url, i) for i, url in enumerate(segment_uris)]
        for future in futures:
            future.result()

    final_completed = sum(1 for b in downloaded_bytes if b > 0)
    if total_segments > 0 and (final_completed / total_segments) < 0.95:
        # Silently fail on incomplete chunks
        import shutil
        shutil.rmtree(parts_dir, ignore_errors=True)
        sys.exit(1)

    print(json.dumps({"status": "baking", "baking": True, "done": False, "total_bytes": 1, "downloaded_bytes": 1}), flush=True)
    
    import shutil
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg_bin, "-y", "-i", "pipe:0", "-c", "copy", str(tmp_path)]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    try:
        if init_segment_url:
            init_path = parts_dir / "init.mp4"
            if init_path.exists():
                with open(init_path, 'rb') as infile:
                    import shutil
                    shutil.copyfileobj(infile, process.stdin)
        for i in range(total_segments):
            frag_path = parts_dir / f"frag_{i:05d}.ts"
            if frag_path.exists():
                with open(frag_path, 'rb') as infile:
                    import shutil
                    shutil.copyfileobj(infile, process.stdin)
    finally:
        process.stdin.close()
        process.wait()

    import shutil
    if parts_dir.exists():
        shutil.rmtree(parts_dir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(1)
    
    playlist_url = sys.argv[1]
    target_path = sys.argv[2]
    import base64
    headers = json.loads(base64.b64decode(sys.argv[3]).decode('utf-8'))
    
    try:
        download_hls(playlist_url, target_path, headers)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
