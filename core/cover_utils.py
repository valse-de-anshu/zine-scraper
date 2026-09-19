import os
import shutil
import time
import importlib
import logging
from pathlib import Path
from typing import Optional, Union, Dict, Any
from bs4 import BeautifulSoup
from PIL import Image
import requests

from core.paths import PathAuthority

SITE_MAP = {
    "manhuaplus.org": "manhuaplus",
    "manhwaus.net": "manhwaus",
    "hentai18.net": "hentai18",
    "hentai20.io": "hentai20",
    "asurascans.com": "asurascans",
    "asuracomic.net": "asurascans",
    "asuratoon.com": "asurascans",
    "omegascans.org": "omegascans",
    "kunmanga.co.uk": "kunmanga",
    "fanfox.net": "fanfox",
    "mangafox.la": "fanfox",
    "nhentai.net": "nhentai",
    "weebcentral.com": "weebcentral",
    "mangak.io": "mangak",
    "idagio.com": "idagio",
    "pinterest.com": "pinterest",
}

def extract_cover_url(soup: BeautifulSoup, url: str) -> Optional[str]:
    """
    Dynamically loads site-specific cover extraction logic.
    """
    url_lower = url.lower()
    site_folder = next((folder for domain, folder in SITE_MAP.items() if domain in url_lower), None)
    
    if site_folder:
        try:
            # Import the site-specific module
            module = importlib.import_module(f"scrapers.{site_folder}.cover")
            if hasattr(module, "extract"):
                return module.extract(soup, url)
        except ImportError:
            pass
        except Exception as e:
            logging.debug(f"Error in site-specific cover logic for {site_folder}: {e}")

    # Fallback to generic
    try:
        from .generic_cover import extract as generic_extract
        return generic_extract(soup, url)
    except Exception:
        return None


def detect_image_format_from_bytes(header_bytes: bytes) -> Optional[str]:
    """
    Sniffs real image format by inspecting the first 32+ binary magic bytes.
    Returns format string ("JPEG", "PNG", "WEBP", "GIF", "AVIF", "BMP", "TIFF", "ICO", "HEIC") or None.
    """
    if not header_bytes:
        return None
    if header_bytes.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if header_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if header_bytes.startswith(b"RIFF") and b"WEBP" in header_bytes[:16]:
        return "WEBP"
    if header_bytes.startswith(b"GIF8"):
        return "GIF"
    if b"ftyp" in header_bytes[:16] and (b"avif" in header_bytes[:16] or b"avis" in header_bytes[:16] or b"mif1" in header_bytes[:16]):
        return "AVIF"
    if b"ftyp" in header_bytes[:16] and any(h in header_bytes[:16] for h in (b"heic", b"heix", b"hevc", b"heim", b"heis")):
        return "HEIC"
    if header_bytes.startswith(b"BM"):
        return "BMP"
    if header_bytes.startswith(b"II*\x00") or header_bytes.startswith(b"MM\x00*"):
        return "TIFF"
    if header_bytes.startswith(b"\x00\x00\x01\x00"):
        return "ICO"
    return None


def ensure_compatible_image_for_ffmpeg(cover_path: Optional[Union[Path, str]]) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Ensures any picture format (JPEG, PNG, WEBP, AVIF, BMP, TIFF, GIF, ICO, HEIC, etc.)
    is converted to a standard format (JPEG or PNG) compatible with FFmpeg attached_pic
    and media container streams (.mp4, .mkv, .mp3, .flac, .m4a).

    Returns:
        (effective_path, temp_path_to_cleanup)
        - effective_path: The Path to use in the FFmpeg command (or None if cover_path was invalid/missing).
        - temp_path_to_cleanup: Path to unlink after FFmpeg finishes (None if no temp file created).
    """
    if not cover_path:
        return None, None
    src = Path(cover_path)
    if not src.exists() or not src.is_file():
        return None, None

    ext = src.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png"):
        return src, None

    converted = src.parent / f".tmp_cover_{src.stem}.jpg"
    try:
        with Image.open(src) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                bg.save(converted, "JPEG", quality=95, optimize=True)
            else:
                img.convert("RGB").save(converted, "JPEG", quality=95, optimize=True)
        return converted, converted
    except Exception as e:
        logging.debug(f"Pillow cover conversion error for {src}: {e}")
        # Fallback to FFmpeg conversion
        try:
            import subprocess
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
            subprocess.run(
                [ffmpeg_bin, "-y", "-i", str(src), "-loglevel", "error", str(converted)],
                check=True,
                capture_output=True
            )
            if converted.exists() and converted.stat().st_size > 0:
                return converted, converted
        except Exception:
            pass
        return src, None


def ensure_compatible_image_bytes_for_tagging(cover_path: Optional[Union[Path, str]]) -> Tuple[Optional[bytes], str]:
    """
    Reads and converts any image file (WebP, AVIF, BMP, TIFF, GIF, ICO, etc.) into clean
    JPEG or PNG bytes with correct MIME type ("image/jpeg" or "image/png") for embedding
    into FLAC / Vorbis / ID3 / MP4 tags.

    Returns:
        (image_bytes, mime_type)
    """
    if not cover_path:
        return None, ""
    src = Path(cover_path)
    if not src.exists() or not src.is_file():
        return None, ""

    try:
        raw_bytes = src.read_bytes()
        if len(raw_bytes) < 100:
            return None, ""

        # If already standard PNG or JPEG, return directly
        if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return raw_bytes, "image/png"
        if raw_bytes.startswith(b"\xff\xd8\xff"):
            return raw_bytes, "image/jpeg"

        # Convert other formats (WEBP, AVIF, BMP, TIFF, etc.) to JPEG in-memory
        import io
        with Image.open(io.BytesIO(raw_bytes)) as img:
            out_buf = io.BytesIO()
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                bg.save(out_buf, format="JPEG", quality=95, optimize=True)
            else:
                img.convert("RGB").save(out_buf, format="JPEG", quality=95, optimize=True)
            return out_buf.getvalue(), "image/jpeg"
    except Exception as e:
        logging.debug(f"Cover tagging byte conversion failed for {src}: {e}")
        try:
            raw_bytes = src.read_bytes()
            return raw_bytes, "image/jpeg"
        except Exception:
            return None, ""


def save_verified_cover(
    source_data: Union[bytes, Path, str],
    folder: Union[Path, str],
    filename: str = "cover"
) -> Optional[Path]:
    """
    2-Step Binary Magic-Byte Verification & Preview Optimization.
    Ensures:
      1. Magic-byte verification of raw payload (rejects corrupt/empty/HTML responses).
      2. Universal desktop & Android preview compatibility (converts PNG/oversized to optimized JPEG).
      3. Preserves authentic WebP/JPEG format with matching extension.
    """
    dest_dir = Path(folder)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Read binary bytes
    if isinstance(source_data, (Path, str)):
        src_path = Path(source_data)
        if not src_path.exists() or src_path.stat().st_size < 100:
            return None
        try:
            raw_bytes = src_path.read_bytes()
        except Exception:
            return None
    elif isinstance(source_data, bytes):
        raw_bytes = source_data
        if len(raw_bytes) < 100:
            return None
    else:
        return None

    # Step 1: Magic Byte Sniffing
    header = raw_bytes[:32]
    real_format = detect_image_format_from_bytes(header)
    if not real_format:
        # Check if payload is HTML / text error
        if any(h in header.lower() for h in (b"<!doctype", b"<html", b"<head", b"<?xml")):
            logging.debug("Rejected HTML/XML payload disguised as cover image")
            return None

    # Step 2: PIL Preview Verification & Normalization
    import io
    try:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            detected_format = real_format or im.format

            # If PNG, oversized, or non-JPEG/WebP format -> convert to clean, universally previewable JPEG
            if detected_format == "PNG" or len(raw_bytes) > 1_500_000 or detected_format not in ("JPEG", "WEBP"):
                target_cover = dest_dir / f"{filename}.jpg"
                if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                    bg.save(target_cover, "JPEG", quality=95, optimize=True)
                else:
                    im.convert("RGB").save(target_cover, "JPEG", quality=95, optimize=True)
                return target_cover
            elif detected_format == "WEBP":
                target_cover = dest_dir / f"{filename}.webp"
                target_cover.write_bytes(raw_bytes)
                return target_cover
            else:
                target_cover = dest_dir / f"{filename}.jpg"
                target_cover.write_bytes(raw_bytes)
                return target_cover
    except Exception as e:
        logging.debug(f"PIL cover verification failed: {e}")
        if real_format:
            ext_map = {"PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "AVIF": ".avif"}
            ext = ext_map.get(real_format, ".jpg")
            target_cover = dest_dir / f"{filename}{ext}"
            try:
                target_cover.write_bytes(raw_bytes)
                return target_cover
            except Exception:
                pass
    return None


def download_verified_cover(
    cover_url: str,
    folder: Union[Path, str],
    session: Optional[requests.Session] = None,
    headers: Optional[Dict[str, str]] = None,
    filename: str = "cover",
    timeout: int = 25
) -> Optional[Path]:
    """
    Downloads cover image using 2-step verification:
      1. HTTP stream fetch with user-agent & retry logic.
      2. Binary magic-byte inspection + PIL preview optimization.
    """
    if not cover_url:
        return None

    dest_dir = Path(folder)
    # If a cover already exists, return it immediately
    existing = list(dest_dir.glob(f"{filename}.*"))
    if existing:
        return existing[0]

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    if headers:
        req_headers.update(headers)

    requester = session or requests

    for attempt in range(1, 4):
        try:
            r = requester.get(cover_url, headers=req_headers, timeout=(10, timeout), stream=True)
            if r.status_code == 403 and "Referer" in req_headers:
                # Retry without Referer
                no_ref_headers = req_headers.copy()
                no_ref_headers.pop("Referer", None)
                r = requester.get(cover_url, headers=no_ref_headers, timeout=(10, timeout), stream=True)

            if r.status_code == 200:
                content = r.content
                saved = save_verified_cover(content, dest_dir, filename=filename)
                if saved:
                    return saved
        except Exception as e:
            logging.debug(f"Cover download attempt {attempt} failed: {e}")
        if attempt < 3:
            time.sleep(1.5)

    return None
