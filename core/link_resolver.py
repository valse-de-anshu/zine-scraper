"""
core/link_resolver.py
---------------------
Centralized Link Architecture & URL Routing Resolver for Zine Scraper.
Validates incoming URLs, maps them to supported site engines, classifies
single-item (Quick Grab) vs whole-series/channel (Vacuum) targets, and
calculates the precise container root for storage and packaging.
"""

import sys
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

_repo_dir = Path(__file__).parent.parent.resolve()
if str(_repo_dir) not in sys.path:
    sys.path.insert(0, str(_repo_dir))

from core.site_map import get_site_folder
from core.funnel import get_scraper_instance
from core.paths import get_container_root, PathAuthority
from core.journal import clean_site_and_category


def clean_url_string(raw: str) -> str:
    """Strips quotes, surrounding whitespace, and ensures http/https scheme."""
    s = raw.strip().strip("'\"")
    # Strip any trailing CLI flag fragments from the URL string
    s = re.sub(r"--batch-path(?:=|\s+)\S+", "", s)
    s = re.sub(r"(?i)\s+--?(?:meta|metadata|vacuum|batch|all|\d+|[aA])\b", "", s).strip()
    s = s.strip("'\"")
    if s and not s.startswith(("http://", "https://")):
        s = "https://" + s
    return s


def extract_inline_flags(raw_input: str) -> Tuple[str, List[str]]:
    """
    Extracts inline CLI flags from a raw URL or command string.
    Supports --0, --<N>, -a, --a, --all, --meta, --metadata.
    Guards against matching UUIDs or hyphenated slugs.
    """
    flags: List[str] = []
    text = raw_input.strip()

    # Metadata flags
    if re.search(r"(?:^|\s)--?(?:meta|metadata)\b", text, re.IGNORECASE):
        flags.append("--meta")
        text = re.sub(r"(?i)(?:^|\s)--?(?:meta|metadata)\b", " ", text)

    # Vacuum all flags: -a, --a, --all
    if re.search(r"(?:^|\s)(?:--?a|--all)\b", text, re.IGNORECASE):
        flags.append("--a")
        text = re.sub(r"(?i)(?:^|\s)(?:--?a|--all)\b", " ", text)

    # Numeric limit flags: --0 (quick grab), --1, --2, --5, etc.
    num_matches = re.findall(r"(?:^|\s)--(\d+)\b", text)
    for num_str in num_matches:
        flag = f"--{num_str}"
        if flag not in flags:
            flags.append(flag)
        text = re.sub(rf"(?:^|\s)--{num_str}\b", " ", text)

    clean_url = clean_url_string(text)
    return clean_url, flags


def resolve_link_info(
    url_input: str,
    flags_input: Optional[List[str]] = None,
    mode_input: Optional[str] = None,
    limit_input: Optional[int] = None
) -> Dict[str, Any]:
    """
    Validates a URL against Zine's site map, determines single vs vacuum architecture,
    and returns rich resolution metadata.
    """
    clean_url, inline_flags = extract_inline_flags(url_input)
    if not clean_url:
        return {
            "valid": False,
            "error": "URL cannot be empty.",
            "url": ""
        }

    # Combine provided flags and inline flags
    combined_flags = list(inline_flags)
    if flags_input:
        for f in flags_input:
            norm_f = "--a" if f in ["-a", "--all"] else f
            if norm_f not in combined_flags:
                combined_flags.append(norm_f)

    if limit_input and limit_input > 0:
        lim_flag = f"--{limit_input}"
        if lim_flag not in combined_flags:
            combined_flags.append(lim_flag)

    # 1. Site resolution
    site_folder = get_site_folder(clean_url)
    if not site_folder:
        # Extract hostname for friendly error
        domain_match = re.search(r"https?://(?:www\.)?([^/]+)", clean_url)
        domain = domain_match.group(1) if domain_match else clean_url
        return {
            "valid": False,
            "error": f"Unsupported URL: domain '{domain}' is not supported by any active Zine Scraper engine.",
            "url": clean_url
        }

    # 2. Scraper initialization
    try:
        scraper = get_scraper_instance(clean_url)
    except Exception as e:
        return {
            "valid": False,
            "error": f"Failed to initialize scraper for '{site_folder}': {e}",
            "url": clean_url
        }

    if not scraper:
        return {
            "valid": False,
            "error": f"Scraper class not found in '{site_folder}'.",
            "url": clean_url
        }

    site_name, category = clean_site_and_category(site_folder)

    # 3. Link Architecture Classification (Single vs Vacuum)
    is_chapter = False
    link_type = "single"

    if hasattr(scraper, "is_chapter_link"):
        try:
            is_chapter = bool(scraper.is_chapter_link())
        except Exception:
            is_chapter = False
    elif hasattr(scraper, "get_link_type"):
        try:
            raw_lt = str(scraper.get_link_type()).lower()
            is_chapter = raw_lt in ["single", "video", "post", "pin"]
            link_type = raw_lt
        except Exception:
            is_chapter = False
    else:
        # Generic heuristic fallback
        is_chapter = any(x in clean_url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/", "/episodes/", "/watch?v=", "/watch/"])

    if not hasattr(scraper, "get_link_type") or not link_type:
        link_type = "chapter" if is_chapter else "series"

    # 4. Mode & Flags Resolution
    is_meta = "--meta" in combined_flags
    has_explicit_limit = any(re.match(r"^--\d+$", f) for f in combined_flags if f != "--0")
    has_explicit_all = "--a" in combined_flags or mode_input == "vacuum"
    has_explicit_single = "--0" in combined_flags or mode_input == "quick_grab"

    effective_flags: List[str] = []
    if is_meta:
        effective_flags.append("--meta")

    if not is_chapter:
        # ── VACUUM LINK ARCHITECTURE (Channel, Series, Playlist, Season) ──
        # Any series, channel, or playlist URL is ALWAYS a VACUUM target!
        effective_mode = "vacuum"
        if has_explicit_limit:
            limit_flag = next(f for f in combined_flags if re.match(r"^--\d+$", f) and f != "--0")
            effective_flags.append(limit_flag)
        elif has_explicit_single:
            # User passed --0 on a series/channel: download 1 single item from the vacuum container
            effective_flags.append("--0")
        else:
            effective_flags.append("--a")
    else:
        # ── QUICK GRAB LINK ARCHITECTURE (Single Video, Single Chapter, Single Clip) ──
        # Standalone chapter or video URL is inherently a QUICK GRAB target!
        effective_mode = "quick_grab"
        effective_flags.append("--0")

    # 5. Exact Container Root Determination
    if effective_mode == "vacuum":
        setattr(scraper, "_force_vacuum", True)
        setattr(scraper, "_batch_all", True)
        setattr(scraper, "_batch_quick_grab", False)
    else:
        setattr(scraper, "_batch_quick_grab", True)
        setattr(scraper, "_force_vacuum", False)
        setattr(scraper, "_batch_all", False)

    try:
        target_root = get_container_root(clean_url, scraper, is_batch=True)
    except Exception:
        pa = PathAuthority()
        target_root = pa.get_downloads_root() / ("Vacuum" if effective_mode == "vacuum" else "Quick grab")

    title = getattr(scraper, "title", None) or getattr(scraper, "name", None) or ""

    return {
        "valid": True,
        "url": clean_url,
        "site_folder": site_folder,
        "site_name": site_name,
        "category": category,
        "link_type": link_type,
        "is_chapter": is_chapter,
        "mode": effective_mode,
        "flags": effective_flags,
        "target_root": str(target_root),
        "title": str(title) if title else "",
        "error": ""
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"valid": False, "error": "No URL provided"}))
        sys.exit(1)

    url_arg = sys.argv[1]
    extra_flags = [a for a in sys.argv[2:] if a.startswith("-")]
    mode_arg = next((a.split("=")[1] for a in sys.argv[2:] if a.startswith("--mode=")), None)

    info = resolve_link_info(url_arg, flags_input=extra_flags, mode_input=mode_arg)
    print(json.dumps(info, indent=2))
    sys.exit(0 if info.get("valid") else 1)


if __name__ == "__main__":
    main()
