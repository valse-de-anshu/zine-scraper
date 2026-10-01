"""
scrapers/3_SYSTEM/civitai/engine.py
-----------------------------------
Core Civitai model downloader and metadata extraction engine.
"""

import os
import sys
import re
import time
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import Optional, List, Tuple, Callable, Dict, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_browser_session(pool_size: int = 16) -> requests.Session:
    """
    Creates a requests session configured with browser emulation,
    connection pooling, and HTTP keep-alive.
    """
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_browser_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """
    High-priority Chrome 133 client hint headers with HTTP/2 Priority
    hints to request prioritized bandwidth at CDN edges.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Sec-Ch-Ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'Priority': 'u=0, i'
    }
    if api_key:
        headers['Authorization'] = f"Bearer {api_key}"
    return headers


def extract_api_key_from_lines(lines: List[str]) -> Optional[str]:
    """Detects API key from comments like '## api key - 1234...'"""
    for line in lines:
        stripped = line.strip()
        match = re.search(r'(?:api[\s_-]?key|token)\s*[:=-]\s*([a-fA-F0-9]{20,})', stripped, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def parse_civitai_target(url_str: str) -> Tuple[Optional[str], str, Optional[str], Optional[str]]:
    """
    Parses a Civitai URL and extracts (download_url, domain, mvid, model_id).
    """
    url_str = url_str.strip()
    parsed = urllib.parse.urlparse(url_str)
    domain = parsed.netloc or 'civitai.com'
    path = parsed.path
    qs = urllib.parse.parse_qs(parsed.query)

    mvid = qs['modelVersionId'][0] if 'modelVersionId' in qs else None
    model_id = None
    m = re.search(r'/models/(\d+)', path)
    if m:
        model_id = m.group(1)

    if '/api/download/models/' in path:
        m_api = re.search(r'/api/download/models/(\d+)', path)
        if m_api:
            mvid = m_api.group(1)
        return url_str, domain, mvid, model_id

    if mvid:
        return f"https://{domain}/api/download/models/{mvid}", domain, mvid, model_id

    if model_id:
        return None, domain, None, model_id

    return url_str, domain, None, None


def resolve_model_id_to_download_url(
    session: requests.Session,
    model_id: str,
    domain: str,
    headers: Dict[str, str],
    api_key: Optional[str] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """Queries Civitai API v1 to find the latest version download URL and metadata for a model ID with domain fallback."""
    token_param = f"?token={api_key}" if api_key else ""
    domains = [domain]
    if domain != "civitai.com":
        domains.append("civitai.com")
    if domain != "civitai.red":
        domains.append("civitai.red")

    last_err = None
    for dom in domains:
        try:
            api_url = f"https://{dom}/api/v1/models/{model_id}{token_param}"
            resp = session.get(api_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                model_versions = data.get('modelVersions', [])
                if not model_versions:
                    raise ValueError(f"No model versions found for model ID {model_id}")
                latest_version = model_versions[0]
                mvid = str(latest_version['id'])
                return f"https://{dom}/api/download/models/{mvid}", mvid, data
        except Exception as e:
            last_err = e

    raise last_err or ValueError(f"Failed to resolve model ID {model_id}")


def get_filename_from_cd(content_disposition: Optional[str]) -> Optional[str]:
    """Extracts filename from Content-Disposition header."""
    if not content_disposition:
        return None
    m_star = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", content_disposition, re.IGNORECASE)
    if m_star:
        return urllib.parse.unquote(m_star.group(1).strip('"\''))
    m = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition, re.IGNORECASE)
    if not m:
        m = re.search(r'filename\s*=\s*([^;]+)', content_disposition, re.IGNORECASE)
    if m:
        return urllib.parse.unquote(m.group(1).strip('"\''))
    return None


def resolve_download_metadata(
    session: requests.Session,
    download_url: str,
    domain: str,
    mvid: Optional[str],
    model_id: Optional[str],
    headers: Dict[str, str],
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Follows redirects to obtain the resolved direct CDN URL, final filename, total size,
    and queries Civitai API for model type, baseModel, tags, and model name.
    """
    resp = session.get(download_url, headers=headers, stream=True, allow_redirects=True, timeout=20)
    resp.raise_for_status()

    cd = resp.headers.get('content-disposition', '')
    filename = get_filename_from_cd(cd)

    if not filename:
        parsed_url = urllib.parse.urlparse(resp.url)
        qs = urllib.parse.parse_qs(parsed_url.query)
        if 'b2ContentDisposition' in qs:
            filename = get_filename_from_cd(qs['b2ContentDisposition'][0])

    content_length = resp.headers.get('content-length')
    total_size = int(content_length) if content_length and content_length.isdigit() else 0
    final_url = resp.url
    resp.close()

    model_type = None
    base_model = None
    model_name = None
    tags: List[str] = []
    token_param = f"?token={api_key}" if api_key else ""

    # Fetch version metadata
    if mvid:
        for query_domain in [domain, "civitai.com", "civitai.red"]:
            try:
                meta_resp = session.get(f"https://{query_domain}/api/v1/model-versions/{mvid}{token_param}", headers=headers, timeout=10)
                if meta_resp.status_code == 200:
                    meta = meta_resp.json()
                    base_model = meta.get('baseModel')
                    m_info = meta.get('model', {})
                    model_type = m_info.get('type')
                    model_name = m_info.get('name')
                    if not model_id and meta.get('modelId'):
                        model_id = str(meta.get('modelId'))
                    if not filename:
                        files = meta.get('files', [])
                        if files:
                            filename = files[0].get('name')
                    break
            except Exception:
                pass

    # Fetch model-level metadata for tags and type
    if model_id and (not model_type or not tags):
        for query_domain in [domain, "civitai.com", "civitai.red"]:
            try:
                m_resp = session.get(f"https://{query_domain}/api/v1/models/{model_id}{token_param}", headers=headers, timeout=10)
                if m_resp.status_code == 200:
                    m_data = m_resp.json()
                    if not model_type:
                        model_type = m_data.get('type')
                    if not model_name:
                        model_name = m_data.get('name')
                    raw_tags = m_data.get('tags', [])
                    if isinstance(raw_tags, list):
                        tags = [str(t) for t in raw_tags]
                    break
            except Exception:
                pass

    if not filename:
        filename = os.path.basename(urllib.parse.urlparse(download_url).path)
        if not filename or filename == 'models':
            filename = f"model_{mvid or int(time.time())}.safetensors"

    return {
        "final_url": final_url,
        "filename": filename,
        "total_size": total_size,
        "model_type": model_type,
        "base_model": base_model,
        "model_name": model_name,
        "tags": tags,
        "mvid": mvid,
        "model_id": model_id
    }


def download_chunk(
    session: requests.Session,
    url: str,
    headers: Dict[str, str],
    part_path: str,
    start: int,
    end: int,
    file_lock: threading.Lock,
    progress_callback: Optional[Callable[[int], None]] = None,
    max_retries: int = 5,
    stop_check: Optional[Callable[[], bool]] = None
) -> bool:
    """Downloads a single slice/chunk in parallel with retries and mid-chunk resume."""
    curr_pos = start
    # Strip Authorization header so presigned S3/R2/B2 URLs do not reject with 400 Bad Request
    base_headers = {k: v for k, v in headers.items() if k.lower() != 'authorization'}

    for attempt in range(1, max_retries + 1):
        if stop_check and stop_check():
            return False
        if curr_pos > end:
            return True

        chunk_headers = base_headers.copy()
        chunk_headers['Range'] = f"bytes={curr_pos}-{end}"

        try:
            with session.get(url, headers=chunk_headers, stream=True, timeout=30) as r:
                if r.status_code not in (200, 206):
                    r.raise_for_status()

                if r.status_code == 200 and curr_pos > start:
                    curr_pos = start

                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if stop_check and stop_check():
                        return False
                    if chunk:
                        chunk_len = len(chunk)
                        with file_lock:
                            with open(part_path, 'r+b') as f:
                                f.seek(curr_pos)
                                f.write(chunk)
                        curr_pos += chunk_len
                        if progress_callback:
                            progress_callback(chunk_len)
                if curr_pos > end:
                    return True
        except Exception:
            if stop_check and stop_check():
                return False
            if attempt < max_retries:
                time.sleep(1.5 * attempt)
            else:
                return False
    return False


def parallel_download_file(
    session: requests.Session,
    download_url: str,
    target_path: str,
    total_size: int,
    headers: Dict[str, str],
    threads: int = 6,
    max_retries: int = 5,
    progress_callback: Optional[Callable[[int], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Downloads file using concurrent Range streams to bypass single-stream CDN bandwidth limits.
    """
    part_path = target_path + ".part"
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    if total_size < 10 * 1024 * 1024:
        return single_stream_download(
            session=session,
            download_url=download_url,
            target_path=target_path,
            expected_size=total_size,
            headers=headers,
            max_retries=max_retries,
            progress_callback=progress_callback,
            stop_check=stop_check
        )

    # Pre-allocate part file on disk
    with open(part_path, 'wb') as f:
        f.seek(total_size - 1)
        f.write(b'\0')

    chunk_size = total_size // threads
    ranges = []
    for i in range(threads):
        start = i * chunk_size
        end = (start + chunk_size - 1) if (i < threads - 1) else (total_size - 1)
        ranges.append((start, end))

    file_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [
            executor.submit(
                download_chunk, session, download_url, headers, part_path,
                start, end, file_lock, progress_callback, max_retries, stop_check
            )
            for start, end in ranges
        ]
        all_succeeded = all(f.result() for f in as_completed(futures))

    if stop_check and stop_check():
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except Exception:
                pass
        return False

    if all_succeeded and os.path.exists(part_path):
        if os.path.getsize(part_path) == total_size:
            os.rename(part_path, target_path)
            return True

    # If parallel streams failed or timed out, clean up and fallback to single_stream_download
    if os.path.exists(part_path):
        try:
            os.remove(part_path)
        except Exception:
            pass

    if stop_check and stop_check():
        return False

    return single_stream_download(
        session=session,
        download_url=download_url,
        target_path=target_path,
        expected_size=total_size,
        headers=headers,
        max_retries=max_retries,
        progress_callback=progress_callback,
        stop_check=stop_check
    )


def single_stream_download(
    session: requests.Session,
    download_url: str,
    target_path: str,
    expected_size: int,
    headers: Dict[str, str],
    max_retries: int = 5,
    progress_callback: Optional[Callable[[int], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None
) -> bool:
    """Fallback single-stream downloader with resume support."""
    part_path = target_path + ".part"
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    base_headers = {k: v for k, v in headers.items() if k.lower() != 'authorization'}
    for attempt in range(1, max_retries + 1):
        if stop_check and stop_check():
            return False
        resume_byte = os.path.getsize(part_path) if os.path.exists(part_path) else 0
        req_headers = base_headers.copy()
        if resume_byte > 0:
            req_headers['Range'] = f"bytes={resume_byte}-"

        try:
            with session.get(download_url, headers=req_headers, stream=True, timeout=30) as r:
                if r.status_code == 416:
                    os.rename(part_path, target_path)
                    return True

                if r.status_code not in (200, 206):
                    r.raise_for_status()

                mode = 'ab' if (r.status_code == 206 and resume_byte > 0) else 'wb'

                with open(part_path, mode) as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if stop_check and stop_check():
                            return False
                        if chunk:
                            f.write(chunk)
                            if progress_callback:
                                progress_callback(len(chunk))

            os.rename(part_path, target_path)
            return True

        except Exception:
            if stop_check and stop_check():
                return False
            if attempt < max_retries:
                time.sleep(2 ** attempt)

    return False


def remove_line_from_file(filepath: Path, line_to_remove: str) -> None:
    """Atomically removes a specific line from the input file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    updated = [l for l in lines if l.strip() != line_to_remove.strip()]
    temp_file = filepath.with_suffix('.tmp')
    with open(temp_file, 'w', encoding='utf-8') as f:
        f.writelines(updated)
    os.replace(temp_file, filepath)
