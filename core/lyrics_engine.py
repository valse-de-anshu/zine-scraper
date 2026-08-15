"""
core/lyrics_engine.py
---------------------
Lyrics Engine for Zine Scraper Suite.
Incorporates the 6-layer lyrics waterfall architecture:

1. Disk Cache (~/.cache/zine-lyrics & ~/.cache/qs-lyrics) -> 0.0s instant fetch
2. Embedded audio tags (Mutagen SYLT/LYRICS/UNSYNCEDLYRICS/Vorbis) -> instant offline
3. Local .lrc file next to track -> instant offline
4. LRCLib API (https://lrclib.net) -> Synced & plain lyrics
5. NetEase Cloud Music API -> Massive catalog for anime/K-pop/Asian music
6. Megalobiz -> Web search fallback for Western tracks
"""

import sys
import os
import re
import json
import time
import hashlib
import logging
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from core.ui import (
    console, startup_clear, print_banner, Selector,
    active_status, set_active_live, get_theme_input_ansi, theme_input, raw_prompt_input,
)
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live

logger = logging.getLogger(__name__)

_LIVE_INSTANCE = None

try:
    import mutagen
    from mutagen import File as MutagenFile
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False


# ─── Cache Layer (~/.cache/zine-lyrics) ───────────────────────────────────────

CACHE_DIRS = [
    os.path.expanduser("~/.cache/zine-lyrics"),
    os.path.expanduser("~/.cache/qs-lyrics"),
]


def _cache_key(title: str, artist: str) -> str:
    raw = f"{title.lower().strip()}|{artist.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cache(title: str, artist: str) -> Optional[List[Dict[str, Any]]]:
    key = _cache_key(title, artist)
    for cdir in CACHE_DIRS:
        cpath = os.path.join(cdir, f"{key}.json")
        if os.path.exists(cpath):
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
            except Exception:
                pass
    return None


def _save_cache(title: str, artist: str, lines: List[Dict[str, Any]]):
    primary_dir = CACHE_DIRS[0]
    os.makedirs(primary_dir, exist_ok=True)
    cpath = os.path.join(primary_dir, f"{_cache_key(title, artist)}.json")
    try:
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(lines, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"Failed to write lyrics cache: {e}")


# ─── Data Cleaners & Helpers ──────────────────────────────────────────────────

INSTRUMENTAL_KEYWORDS = {
    "instrumental", "orchestral", "symphony", "concerto", "sonata",
    "waltz", "suite", "piano solo", "no lyrics", "backing track",
    "karaoke version", "ost instrumental", "bgm", "instrumental version"
}


def is_likely_instrumental(text: str) -> bool:
    """Detect if a track is likely classical/instrumental based on keywords."""
    if not text:
        return False
    lower = text.lower()
    return any(kw in lower for kw in INSTRUMENTAL_KEYWORDS) or bool(re.search(r'\bop\.\s*\d+|\bno\.\s*\d+', lower))


# Context labels that appear in parens/brackets that are NOT part of the song name
_CONTEXT_LABEL_PATTERN = re.compile(
    r"""\s*[\(\[]
    (?:
        # Live performances
        Live\s+(?:from|at|From|At|Performance|Session|Version|on|On)[^\)\]]*
        |Live\s+\d{4}[^\)\]]*
        |[^\)\]]*\bLive\b[^\)\]]*(?:Tour|Show|Concert|Stage|Arena|Festival|Award|VMAs?|AMAs?|EMAs?|Grammy|Billboard|Coachella|Glastonbury|SNL|Tonight|Kimmel|Fallon|Colbert|Corden|Leno|Letterman)[^\)\]]*
        |[^\)\]]*(?:Tour|Concert|Show|Stage|Arena|Festival)\s+(?:Performance|Session|Live|Version)[^\)\]]*
        |[^\)\]]*\d{4}\s+(?:MTV|VMAs?|AMAs?|EMAs?|Grammy|Billboard|BET)[^\)\]]*
        # Event-based labels
        |(?:Pop.?Up\s+Video|Behind\s+the\s+Scenes?|BTS|Making\s+Of|Studio\s+Version)
        |(?:Acoustic|Acoustic\s+Version|Acoustic\s+Session|Stripped|Stripped\s+Version)
        |(?:Karaoke|Instrumental\s+Version|Demo|Demo\s+Version|Rough\s+Mix)
        |(?:Sped\s+Up|Speed\s+Up|Slowed|Slowed\s+\+\s+Reverb|Slowed\s+Down|Reverb|Nightcore)
        |(?:Extended|Extended\s+Mix|Radio\s+Edit|Club\s+Mix|Remix(?:\s+Video)?|Alt(?:ernate)?\s+Version)
        |(?:Explicit|Clean|\d+\s+Hour\s+Loop|Loop|Lofi|Lo.?Fi)
    )
    [\)\]]""",
    re.IGNORECASE | re.VERBOSE
)


def clean_track_string(text: str) -> str:
    """Clean track title / query string by stripping common video/filename noise.
    
    Handles:
    - Leading track numbers: "1. ", "01. ", "1) ", "(1) "
    - YouTube suffix: " - YouTube"
    - Common bracketed labels: (Official Audio), [MV], etc.
    - Context/performance labels: (Live From Tour), (Behind the Scenes), (Pop-Up Video), etc.
    - Bare (unbracketed) labels at end of string
    """
    if not text:
        return ""
    # Strip leading track numbers: "1. ", "01. ", "(1) ", "1) "
    text = re.sub(r'^\(?\d+[\)\.]\)?\s*', '', text)
    # Strip YouTube suffix
    text = re.sub(r'\s*-\s*YouTube$', '', text, flags=re.IGNORECASE)
    # Strip explicit release labels at end
    text = re.sub(r'\s*[\(\[](Explicit|Clean Version|Parental Advisory)[\)\]]', '', text, flags=re.IGNORECASE)
    # Strip known bracketed release labels
    text = re.sub(
        r'\s*[\(\[](Official Music Video|Official Video|Official Audio|'
        r'Lyric Video|Audio Only|Audio|Video|HD|HQ|MV|4K|Full HD|'
        r'Visualizer|Full Video|Remaster(?:ed)?|Remastered Version)[\)\]]',
        '', text, flags=re.IGNORECASE
    )
    # Strip context/performance labels in parens
    text = _CONTEXT_LABEL_PATTERN.sub('', text)
    # Strip bare (unbracketed) labels at end of string
    text = re.sub(
        r'\s*[-–]?\s*(Official Music Video|Official Video|Official Audio|'
        r'Lyric Video|Audio Only|Official Lyric Video|Official Live|'
        r'Full Video|Remastered|Behind the Scenes)$',
        '', text, flags=re.IGNORECASE
    )
    # Collapse extra whitespace
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _strip_to_core_title(title: str) -> str:
    """Ultimate fallback: strip ALL parenthesized/bracketed content from title.
    
    Used when the full cleaned title doesn't match anything in any database.
    e.g. 'Feather (Behind the Scenes)' -> 'Feather'
         'Nonsense / Feather (Live From VMAs)' -> 'Nonsense / Feather'
    Also handles medley titles: tries each part split by '/' or '&'.
    """
    if not title:
        return title
    # Strip all parenthesized/bracketed content
    core = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', '', title).strip()
    # Strip trailing punctuation/dashes left over
    core = re.sub(r'[-–,/&|]\s*$', '', core).strip()
    core = re.sub(r'^\s*[-–,/&|]', '', core).strip()
    return core if core else title


def _medley_title_variants(title: str) -> List[str]:
    """For medley titles like 'Nonsense / Feather' return ['Nonsense / Feather', 'Nonsense', 'Feather']."""
    variants = [title]
    for sep in ('/', '&', '+', ' x ', ' X '):
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            variants.extend(parts)
    return list(dict.fromkeys(variants))  # dedupe preserving order



def parse_lrc(lrc_text: str) -> List[Dict[str, Any]]:
    """Parse LRC format into sorted [{time: float, text: str}, ...]."""
    lines = []
    for raw in lrc_text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        tags = re.findall(r'\[(\d+:\d+(?:\.\d+)?)\]', raw)
        text = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', raw).strip()
        for tag in tags:
            try:
                parts = tag.split(":")
                mins = int(parts[0])
                secs = float(parts[1])
                timestamp = mins * 60 + secs
                lines.append({"time": timestamp, "text": text})
            except Exception:
                continue
    return sorted(lines, key=lambda x: x["time"])


def format_lrc(lines: List[Dict[str, Any]]) -> str:
    """Reconstruct valid .lrc file text from [{time, text}, ...]."""
    lrc_out = []
    for entry in lines:
        ts = entry["time"]
        mins = int(ts // 60)
        secs = ts % 60
        time_tag = f"[{mins:02d}:{secs:05.2f}]"
        lrc_out.append(f"{time_tag}{entry['text']}")
    return "\n".join(lrc_out)


def _http_get(url: str, timeout: int = 8, headers: Optional[Dict[str, str]] = None) -> bytes:
    hdrs = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _title_match(a: str, b: str) -> bool:
    def norm(s):
        s = s.lower()
        s = re.sub(r'\s*[\(\[](feat|ft|with|prod|x)[^\)\]]*[\)\]]', '', s, flags=re.IGNORECASE)
        s = re.sub(r'[^\w\s]', '', s)
        return s.strip()
    na, nb = norm(a), norm(b)
    return na in nb or nb in na or na[:15] == nb[:15]


def _artist_match(a: str, b: str) -> bool:
    if not a or a.lower() in ("youtube", "unknown", ""):
        return True
    a_words = set(w for w in a.lower().split() if len(w) > 3)
    b_lower = b.lower()
    return a.lower() in b_lower or b_lower in a.lower() or any(w in b_lower for w in a_words)


# ─── Source 1: Embedded Audio Tags (Mutagen) ─────────────────────────────────

def _from_embedded_tags(file_path: Path) -> List[Dict[str, Any]]:
    """Read SYLT (synced ID3) or plain LYRICS/UNSYNCEDLYRICS tags directly from audio file."""
    if not MUTAGEN_OK or not file_path.exists():
        return []
    try:
        audio = MutagenFile(str(file_path), easy=False)
        if audio is None:
            return []
        for tag_key in audio.keys():
            if tag_key.startswith("SYLT"):
                sylt = audio[tag_key]
                lines = []
                for text, ts_ms in getattr(sylt, "text", []):
                    if str(text).strip():
                        lines.append({"time": ts_ms / 1000.0, "text": str(text).strip()})
                if lines:
                    return sorted(lines, key=lambda x: x["time"])
        for tag_key in audio.keys():
            if tag_key.startswith("LYRICS") or tag_key == "lyrics":
                tag = audio[tag_key]
                raw = tag.text if hasattr(tag, "text") else str(tag)
                if isinstance(raw, list):
                    raw = raw[0] if raw else ""
                if raw and "[" in str(raw):
                    parsed = parse_lrc(str(raw))
                    if parsed:
                        return parsed
        for key in ("LYRICS", "lyrics", "UNSYNCEDLYRICS"):
            if key in audio:
                val = audio[key]
                if isinstance(val, list):
                    val = val[0] if val else ""
                if val and "[" in str(val):
                    parsed = parse_lrc(str(val))
                    if parsed:
                        return parsed
    except Exception as e:
        logger.debug(f"Mutagen tag extraction error for {file_path}: {e}")
    return []


# ─── Online API Sources ──────────────────────────────────────────────────────

def fetch_from_lrclib(title: str, artist: str = "", duration: float = 0.0) -> List[Dict[str, Any]]:
    """Query lrclib.net API for synced LRC lines. Falls back to plain lyrics if no synced found."""
    base = "https://lrclib.net/api"
    urls = []
    if title and artist and artist.lower() not in ("youtube", "unknown", ""):
        if duration > 0:
            urls.append(
                f"{base}/get?track_name={urllib.parse.quote(title)}"
                f"&artist_name={urllib.parse.quote(artist)}"
                f"&duration={int(duration)}"
            )
        urls.append(
            f"{base}/search?track_name={urllib.parse.quote(title)}"
            f"&artist_name={urllib.parse.quote(artist)}"
        )
    urls.append(f"{base}/search?q={urllib.parse.quote((title + ' ' + artist).strip())}")
    urls.append(f"{base}/search?q={urllib.parse.quote(title)}")
    # Also try swapped artist/title (common when metadata has them backwards)
    if artist and title:
        urls.append(f"{base}/search?q={urllib.parse.quote((artist + ' ' + title).strip())}")

    plain_fallback: List[Dict[str, Any]] = []

    for url in urls:
        try:
            raw = _http_get(url)
            data = json.loads(raw)
            candidates = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
            for strict in (True, False):
                for d in candidates:
                    synced = d.get("syncedLyrics")
                    plain = d.get("plainLyrics")
                    tm = _title_match(title, d.get("trackName", ""))
                    am = _artist_match(artist, d.get("artistName", ""))
                    match_ok = (strict and tm and am) or (not strict and tm)
                    if match_ok:
                        if synced:
                            return parse_lrc(synced)
                        if plain and not plain_fallback:
                            # Convert plain lyrics to timed lines starting at 0
                            lines_text = [l.strip() for l in plain.splitlines() if l.strip()]
                            plain_fallback = [{"time": i * 3.0, "text": l} for i, l in enumerate(lines_text)]
        except Exception as e:
            logger.debug(f"LRCLib fetch attempt failed for {url}: {e}")
            continue

    return plain_fallback



def fetch_from_netease(title: str, artist: str = "") -> List[Dict[str, Any]]:
    """Query NetEase Cloud Music API for synced lyrics (anime / K-pop / Asian catalog)."""
    query = f"{title} {artist}".strip()
    search_url = (
        "https://music.163.com/api/search/get/web"
        f"?csrf_token=&s={urllib.parse.quote(query)}&type=1&offset=0&limit=8"
    )
    try:
        data = json.loads(_http_get(search_url, headers={"Referer": "https://music.163.com/"}))
        songs = data.get("result", {}).get("songs", [])
        for song in songs:
            name = song.get("name", "")
            artists_str = " ".join(a.get("name", "") for a in song.get("artists", []))
            if not _title_match(title, name):
                continue
            song_id = song.get("id")
            if song_id:
                lyric_url = f"https://music.163.com/api/song/lyric?os=pc&id={song_id}&lv=1&kv=1&tv=-1"
                lyric_data = json.loads(_http_get(lyric_url, headers={"Referer": "https://music.163.com/"}))
                for key in ("klyric", "lrc"):
                    lrc_text = lyric_data.get(key, {}).get("lyric", "")
                    if lrc_text:
                        parsed = parse_lrc(lrc_text)
                        if parsed:
                            return parsed
    except Exception as e:
        logger.debug(f"NetEase lyrics fetch failed: {e}")
    return []


def fetch_from_musixmatch(title: str, artist: str = "") -> List[Dict[str, Any]]:
    """Scrape Musixmatch for plain lyrics (world's largest lyrics DB)."""
    try:
        query = urllib.parse.quote_plus(f"{artist} {title}".strip() if artist else title)
        search_url = f"https://www.musixmatch.com/search/{query}"
        html = _http_get(search_url, timeout=10).decode("utf-8", errors="ignore")
        # Find first track link in search results
        track_match = re.search(r'href="(/lyrics/[^"?#]+)"', html)
        if not track_match:
            return []
        track_path = track_match.group(1)
        # Verify title match before fetching full page
        url_parts = track_path.strip("/").split("/")
        if len(url_parts) >= 2:
            url_track_name = url_parts[-1].replace("-", " ")
            if not _title_match(title, url_track_name):
                return []
        lyric_url = f"https://www.musixmatch.com{track_path}"
        lyric_html = _http_get(lyric_url, timeout=10).decode("utf-8", errors="ignore")
        # Extract lyrics from span tags
        spans = re.findall(r'<span[^>]*class="[^"]*lyrics__content[^"]*"[^>]*>(.*?)</span>', lyric_html, re.DOTALL)
        if not spans:
            # fallback: look for data-testid lyrics spans
            spans = re.findall(r'<span[^>]*>((?:[^<]|<br>)+)</span>', lyric_html)
        if spans:
            lines_text = []
            for span in spans:
                cleaned = re.sub(r'<[^>]+>', '', span).strip()
                cleaned = cleaned.replace('&amp;', '&').replace('&apos;', "'").replace('&#039;', "'")
                for line in cleaned.splitlines():
                    line = line.strip()
                    if line:
                        lines_text.append(line)
            if lines_text:
                return [{"time": i * 3.0, "text": l} for i, l in enumerate(lines_text)]
    except Exception as e:
        logger.debug(f"Musixmatch fetch failed: {e}")
    return []


def fetch_from_azlyrics(title: str, artist: str = "") -> List[Dict[str, Any]]:
    """Scrape AZLyrics as a deep fallback for Western tracks not in other DBs."""
    try:
        # Build AZLyrics URL format: /artist/tracktitle.html
        def slug(s: str) -> str:
            s = s.lower()
            s = re.sub(r'[^a-z0-9]', '', s)
            return s

        if not artist or artist.lower() in ("unknown", "youtube", ""):
            return []

        artist_slug = slug(re.sub(r'^the\s+', '', artist.lower()))
        title_slug = slug(title)
        url = f"https://www.azlyrics.com/lyrics/{artist_slug}/{title_slug}.html"
        html = _http_get(url, timeout=10).decode("utf-8", errors="ignore")
        # AZLyrics puts lyrics between comment markers
        match = re.search(
            r'<!-- Usage of azlyrics\.com content by any third-party.*?-->.*?<div[^>]*>(.*?)</div>',
            html, re.DOTALL
        )
        if not match:
            # fallback pattern
            match = re.search(r'<div>\s*<!-- (.*?) -->(.*?)</div>', html, re.DOTALL)
        if match:
            raw = match.group(1 if match.lastindex == 1 else 2)
            raw = re.sub(r'<[^>]+>', '', raw)
            raw = raw.replace('&amp;', '&').replace('&apos;', "'").replace('&#039;', "'")
            lines_text = [l.strip() for l in raw.splitlines() if l.strip()]
            if lines_text:
                return [{"time": i * 3.0, "text": l} for i, l in enumerate(lines_text)]
    except Exception as e:
        logger.debug(f"AZLyrics fetch failed: {e}")
    return []


def fetch_from_megalobiz(title: str, artist: str = "") -> List[Dict[str, Any]]:
    """Search Megalobiz database as a fallback."""
    query = f"{artist} {title}".strip() if artist else title
    search_url = f"https://www.megalobiz.com/search/all?qry={urllib.parse.quote(query)}&searchButton=Search"
    try:
        html = _http_get(search_url, timeout=8).decode("utf-8", errors="ignore")
        match = re.search(r'href="(/lrc/maker/[^"]+)"', html)
        if not match:
            return []
        lrc_url = "https://www.megalobiz.com" + match.group(1)
        lrc_html = _http_get(lrc_url, timeout=8).decode("utf-8", errors="ignore")
        lrc_match = re.search(r'<div[^>]*id="entity_lyric_text"[^>]*>(.*?)</div>', lrc_html, re.DOTALL)
        if lrc_match:
            raw = lrc_match.group(1)
            raw = re.sub(r'<[^>]+>', '', raw)
            raw = raw.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
            parsed = parse_lrc(raw)
            if parsed:
                return parsed
    except Exception as e:
        logger.debug(f"Megalobiz lyrics fetch failed: {e}")
    return []



# ─── Full 8-Layer Waterfall ──────────────────────────────────────────────────

def waterfall_fetch_lyrics(title: str, artist: str = "", duration: float = 0.0, file_path: Optional[Path] = None) -> Tuple[List[Dict[str, Any]], str]:
    """
    8-Layer Waterfall Fetch Architecture with Core Title Retry:
      ① Disk Cache (~/.cache/zine-lyrics) -> 0.0s instant fetch
      ② Embedded Tags (Mutagen SYLT/LYRICS/Vorbis) -> instant offline
      ③ Local .lrc File next to track -> instant offline
      ④-⑧ Online APIs (LRCLib, NetEase, Musixmatch, Megalobiz, AZLyrics)
         └─ If full title misses, retries with _strip_to_core_title() and medley variants
    Returns (parsed_lines, source_name).
    """
    clean_t = clean_track_string(title)
    clean_a = clean_track_string(artist)

    if " - " in clean_t and not clean_a:
        parts = clean_t.split(" - ", 1)
        clean_a = parts[0].strip()
        clean_t = parts[1].strip()

    # Layer 1: Disk Cache
    cached = _load_cache(clean_t, clean_a)
    if cached:
        return cached, "Disk Cache (~/.cache/zine-lyrics)"

    # Layer 2: Embedded Tags
    if file_path and file_path.exists():
        embedded = _from_embedded_tags(file_path)
        if embedded:
            _save_cache(clean_t, clean_a, embedded)
            return embedded, "Embedded Audio Tag (SYLT/ID3)"

    # Layer 3: Local .lrc File
    if file_path and file_path.exists():
        local_lrc_p = file_path.with_suffix(".lrc")
        if local_lrc_p.exists():
            try:
                content = local_lrc_p.read_text(encoding="utf-8", errors="ignore")
                parsed = parse_lrc(content)
                if parsed:
                    _save_cache(clean_t, clean_a, parsed)
                    return parsed, "Local .lrc File"
            except Exception:
                pass

    def _run_online_waterfall(t: str, a: str) -> Tuple[List, str]:
        """Run layers 4-8 for a given title+artist pair."""
        lines = fetch_from_lrclib(t, a, duration)
        if lines:
            return lines, "LRCLib (lrclib.net)"
        lines = fetch_from_netease(t, a)
        if lines:
            return lines, "NetEase Cloud Music"
        lines = fetch_from_musixmatch(t, a)
        if lines:
            return lines, "Musixmatch"
        lines = fetch_from_megalobiz(t, a)
        if lines:
            return lines, "Megalobiz"
        lines = fetch_from_azlyrics(t, a)
        if lines:
            return lines, "AZLyrics"
        return [], ""

    # Layers 4-8: Try with full cleaned title
    lines, src = _run_online_waterfall(clean_t, clean_a)
    if lines:
        _save_cache(clean_t, clean_a, lines)
        return lines, src

    # Core Title Retry: strip ALL parenthesized context
    # e.g. "Feather (Behind the Scenes)" -> "Feather"
    #      "Feather (Live from the emails i cant send Tour)" -> "Feather"
    core_t = _strip_to_core_title(clean_t)
    if core_t and core_t.lower() != clean_t.lower():
        logger.debug(f"Lyrics: retrying with core title '{core_t}' (was '{clean_t}')")
        lines, src = _run_online_waterfall(core_t, clean_a)
        if lines:
            _save_cache(clean_t, clean_a, lines)  # cache under original key too
            _save_cache(core_t, clean_a, lines)
            return lines, src + " (core title retry)"

    # Medley Variant Retry: for titles like "Nonsense / Feather" try each part separately
    variants = _medley_title_variants(core_t or clean_t)
    if len(variants) > 1:
        for variant in variants[1:]:  # skip first (already tried as core_t or clean_t)
            variant = variant.strip()
            if not variant or variant.lower() == clean_t.lower():
                continue
            logger.debug(f"Lyrics: medley variant retry '{variant}'")
            lines, src = _run_online_waterfall(variant, clean_a)
            if lines:
                _save_cache(clean_t, clean_a, lines)
                return lines, src + " (medley split)"

    return [], "None"




# ─── Track Metadata Extractor ────────────────────────────────────────────────

def extract_audio_info(file_path: Path) -> Tuple[str, str, float]:
    """Extract (title, artist, duration_sec) from an audio file using mutagen or fallback filename."""
    title = ""
    artist = ""
    duration = 0.0

    if MUTAGEN_OK and file_path.exists():
        try:
            audio = MutagenFile(str(file_path), easy=True)
            if audio is not None:
                if audio.info and hasattr(audio.info, "length"):
                    duration = float(audio.info.length)
                titles = audio.get("title", [])
                if titles:
                    title = str(titles[0])
                artists = audio.get("artist", [])
                if artists:
                    artist = str(artists[0])
        except Exception:
            pass

    if not title:
        stem = file_path.stem
        stem = re.sub(r'^\d+[\.\s\-]+\s*', '', stem).strip()
        if " - " in stem:
            parts = stem.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
        else:
            title = stem

    return title, artist, duration



def _lrc_save_path(audio_path: Path, is_batch: bool = False) -> Path:
    """
    Compute the correct .lrc save path for an audio file:
      - Quick Grab (single track): sibling file → <audio_path>.lrc
      - Vacuum / Batch (playlist/album): inside lyrics/ subfolder
    """
    path_str = str(audio_path)
    is_quick_grab = "Quick grab" in path_str
    if is_quick_grab and not is_batch:
        return audio_path.with_suffix(".lrc")
    else:
        return audio_path.parent / "lyrics" / (audio_path.stem + ".lrc")


def auto_fetch_lyrics(file_path: Path, is_batch: bool = False) -> Optional[Path]:
    """
    Called after downloading an audio file.
    Routing rules:
      - Quick Grab (single file): saves <stem>.lrc directly next to audio (NO subfolders).
      - Vacuum / Batch (album/playlist/folder): saves inside <parent>/lyrics/<stem>.lrc.
    Returns path to saved .lrc file on success, else None.
    """
    if not file_path or not file_path.exists():
        return None

    lrc_path = _lrc_save_path(file_path, is_batch)
    if lrc_path.exists():
        return lrc_path

    title, artist, duration = extract_audio_info(file_path)
    if not title:
        return None

    lines, source = waterfall_fetch_lyrics(title, artist, duration, file_path=file_path)
    if lines:
        lrc_text = format_lrc(lines)
        try:
            lrc_path.parent.mkdir(parents=True, exist_ok=True)
            lrc_path.write_text(lrc_text, encoding="utf-8")
            logger.info(f"Auto-synced lyrics from {source} saved to {lrc_path}")
            return lrc_path
        except Exception as e:
            logger.error(f"Failed to write .lrc file: {e}")
            return None
    else:
        status_msg = "Instrumental / No Lyrics" if is_likely_instrumental(title) else "No lyrics found"
        logger.info(f"{status_msg} for '{title}'")
        return None


# ─── Interactive TUI: lyrs ───────────────────────────────────────────────────

def run_lyrics_tui():
    """Interactive Lyrics Downloader TUI (command: lyrs / lyrics)."""
    startup_clear()
    print_banner()

    console.print("[menu]❖ Lyrics Downloader & Synced .LRC Search Engine[/menu]\n")

    if not sys.stdin.isatty():
        console.print("[warning]Non-interactive environment detected. Returning...[/warning]")
        return

    user_query = raw_prompt_input(
        prompt_title="LYRICS DOWNLOADER & SYNCED SEARCH",
        hint="Enter track title/artist (e.g. 'Daft Punk - One More Time') or paste a song/video URL"
    )

    if not user_query:
        return

    title, artist, duration = "", "", 0.0

    if user_query.startswith("http://") or user_query.startswith("https://"):
        with active_status("[info]Extracting metadata from URL...[/info]", spinner="dots"):
            try:
                from core.video_engine import VideoEngine
                eng = VideoEngine()
                info = eng.extract_video_info(user_query, fast=True)
                title = info.get("title") or ""
                artist = info.get("uploader") or info.get("artist") or info.get("channel") or ""
                duration = float(info.get("duration") or 0.0)
            except Exception as e:
                console.print(f"[error]Failed to extract URL info: {e}[/error]")
                title = user_query
    else:
        title = user_query

    lines = []
    source = ""

    with active_status("[info]Running 6-layer lyrics waterfall search...[/info]", spinner="dots"):
        lines, source = waterfall_fetch_lyrics(title, artist, duration)

    if not lines:
        is_inst = is_likely_instrumental(title)
        
        no_lyr_text = Text()
        no_lyr_text.append("✘ ", style="error")
        no_lyr_text.append("No lyrics found for: ", style="menu")
        no_lyr_text.append(f"'{clean_track_string(title)}'\n\n", style="title")
        
        if is_inst:
            no_lyr_text.append("● Note: ", style="warning")
            no_lyr_text.append("This track appears to be Classical, Instrumental, or BGM (no vocal lyrics).\n", style="info")
        else:
            no_lyr_text.append("● Checked Providers: ", style="info")
            no_lyr_text.append("Disk Cache ➔ Embedded Tags ➔ Local .LRC ➔ LRCLib ➔ NetEase ➔ Megalobiz\n", style="unselected")

        no_lyr_panel = Panel(
            no_lyr_text,
            title="[bold warning]Lyrics Search Result[/bold warning]",
            border_style="menu",
            width=88
        )
        console.print(no_lyr_panel)
        console.print("")
        console.input("[info]Press Enter to return...[/info]")
        return

    # Render Preview Panel
    preview_text = Text()
    preview_text.append(f"Source: ", style="menu")
    preview_text.append(f"{source}\n\n", style="site")

    for item in lines[:12]:
        ts = item["time"]
        mins = int(ts // 60)
        secs = ts % 60
        preview_text.append(f"[{mins:02d}:{secs:05.2f}] ", style="unselected")
        preview_text.append(f"{item['text']}\n", style="success")

    if len(lines) > 12:
        preview_text.append(f"\n... ({len(lines) - 12} more lines)", style="unselected")

    preview_panel = Panel(
        preview_text,
        title=f"[title]Synced Lyrics — {clean_track_string(title)}[/title]",
        border_style="menu",
        width=88
    )
    console.print(preview_panel)
    console.print("")

    opts = [
        ("Save .LRC to Quick Grab Folder", "SAVE_DEFAULT"),
        ("Save .LRC to Custom File Path", "SAVE_CUSTOM"),
        ("Back to Main Prompt", "BACK")
    ]
    choice = Selector(opts, "Options").select()

    if choice == "BACK":
        return

    save_path = None
    if choice == "SAVE_DEFAULT":
        from core.config import ConfigLayer
        from core.paths import PathAuthority
        from core.storage import StorageLayer
        cfg = ConfigLayer(PathAuthority(), StorageLayer())
        # Default save in lyrs command is ALWAYS direct single file in Quick grab/music (NO subfolders!)
        base_dir = Path(cfg.get("music_quick_grab_path") or (PathAuthority().get_downloads_root() / "Quick grab" / "music"))
        base_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c for c in clean_track_string(title) if c.isalnum() or c in " .-_()").strip()
        save_path = base_dir / f"{safe_name or 'lyrics'}.lrc"
    elif choice == "SAVE_CUSTOM":
        console.print("[menu]Enter absolute path to save .lrc file:[/menu]")
        console.print("[menu]❯ [/menu]", end="")
        sys.stdout.write(get_theme_input_ansi())
        sys.stdout.flush()
        try:
            c_input = input().strip()
            if c_input:
                save_path = Path(c_input).resolve()
        except (EOFError, KeyboardInterrupt):
            pass
        finally:
            sys.stdout.write("\033[0m")
            sys.stdout.flush()

    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(format_lrc(lines), encoding="utf-8")
        console.print(f"\n[success]✔ Synced .lrc saved to: {save_path}[/success]\n")
        console.input("[info]Press Enter to return...[/info]")


# ─── Interactive TUI: sc-lyrics ──────────────────────────────────────────────

def run_batch_lyrics_tui():
    """Batch Folder Scanner & Auto-Sync TUI (command: sc-lyrics / sclyrs)."""
    startup_clear()
    print_banner()

    console.print("[menu]❖ Folder Batch Scanner & Synced .LRC Auto-Sync[/menu]\n")

    if not sys.stdin.isatty():
        console.print("[warning]Non-interactive environment. Skipping batch lyrics...[/warning]")
        return

    from core.config import ConfigLayer
    from core.paths import PathAuthority
    from core.storage import StorageLayer
    cfg = ConfigLayer(PathAuthority(), StorageLayer())
    default_dir = Path(cfg.get("download_base") or PathAuthority().get_downloads_root()) / "Quick grab" / "music"

    # Display generic relative tilde placeholder to avoid hardcoding raw system usernames
    home_str = str(Path.home())
    display_default = str(default_dir).replace(home_str, "~") if home_str in str(default_dir) else str(default_dir)

    user_dir = raw_prompt_input(
        prompt_title="FOLDER BATCH SCANNER & AUTO-SYNC",
        hint=f"Enter folder path to scan for audio files (Press Enter for default: '{display_default}')"
    )

    if user_dir is None:
        return

    if user_dir.startswith("~"):
        target_dir = Path(os.path.expanduser(user_dir)).resolve()
    elif user_dir.strip():
        target_dir = Path(user_dir.strip()).resolve()
    else:
        target_dir = default_dir.resolve()

    if not target_dir.exists() or not target_dir.is_dir():
        console.print(f"\n[error]Directory not found: {target_dir}[/error]")
        time.sleep(1.8)
        return

    audio_extensions = {".flac", ".mp3", ".m4a", ".wav", ".ogg", ".opus"}
    audio_files: List[Path] = []

    for root, _, files in os.walk(target_dir):
        # Ignore hidden or metadata folders
        if ".zine" in root or ".git" in root:
            continue
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in audio_extensions:
                lrc_p = p.with_suffix(".lrc")
                lrc_sub_p = p.parent / "lyrics" / (p.stem + ".lrc")
                if not lrc_p.exists() and not lrc_sub_p.exists():
                    audio_files.append(p)

    if not audio_files:
        console.print(f"\n[success]✔ All audio files in '{target_dir.name}' already have synced .lrc files![/success]\n")
        console.input("[info]Press Enter to return...[/info]")
        return

    console.print(f"\n[info]Found {len(audio_files)} audio file(s) missing .lrc lyrics.[/info]")
    console.print("[info]Starting batch auto-sync...[/info]\n")

    synced_count = 0
    no_lyrics_count = 0

    # Print live line-by-line log for every single file scanned
    for idx, audio_file in enumerate(audio_files, 1):
        rel_name = audio_file.name
        res = auto_fetch_lyrics(audio_file, is_batch=True)
        if res:
            synced_count += 1
            console.print(f"  [success]✔ [{idx}/{len(audio_files)}] Synced .LRC:[/success] [site]{rel_name}[/site]")
        else:
            no_lyrics_count += 1
            is_inst = is_likely_instrumental(audio_file.stem)
            reason = "Instrumental Track" if is_inst else "No Lyrics Found"
            console.print(f"  [unselected]● [{idx}/{len(audio_files)}] {reason}:[/unselected] [unselected]{rel_name}[/unselected]")
        time.sleep(0.05)

    console.print(f"\n[success]✦ Batch Sync Complete![/success]")
    console.print(f"  [success]Synced .LRC:[/success] {synced_count} track(s)")
    console.print(f"  [unselected]No Lyrics / Instrumental:[/unselected] {no_lyrics_count} track(s)\n")

    # Always use raw input() with explicit TTY guard so it can never be silently skipped
    if sys.stdin.isatty():
        try:
            sys.stdout.write("\033[38;2;125;207;255m  Press Enter to return...\033[0m ")
            sys.stdout.flush()
            input()
        except (EOFError, KeyboardInterrupt):
            pass
