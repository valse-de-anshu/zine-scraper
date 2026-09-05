import yt_dlp
import json
import logging
import subprocess
import os
import re
import html
import time
import requests
from pathlib import Path
from typing import Dict, Any, Callable, Optional, List
from bs4 import BeautifulSoup
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)


def parse_vtt(vtt_content: str) -> List[Dict[str, Any]]:
    """
    Parses raw WebVTT from YouTube into normalized list: [{'time': float, 'text': str}, ...]
    Precision alignment features:
    - Extracts active newly-spoken line from rolling captions (<c...><00:00...> tags)
    - Eliminates multi-line lag and duplicate static context blocks
    - Handles standard (00:00:00.000) and short (00:00.000) timestamp formats
    - Strips inline XML tags while preserving musical notes (♪)
    - Unescapes HTML entities (&amp;, &#39;, &quot;, &nbsp;)
    """
    lines = []
    vtt_clean = re.sub(r"^WEBVTT[^\n]*\n", "", vtt_content.strip(), flags=re.IGNORECASE)
    blocks = re.split(r"\n\s*\n", vtt_clean)

    for block in blocks:
        block = block.strip()
        if not block or block.startswith("Kind:") or block.startswith("Language:"):
            continue

        lines_in_block = block.splitlines()
        ts_match = re.search(r"(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)\s*-->", lines_in_block[0])
        if not ts_match:
            ts_match = re.search(r"(\d{2}):(\d{2}(?:\.\d+)?)\s*-->", lines_in_block[0])
            if ts_match:
                mins = int(ts_match.group(1))
                secs = float(ts_match.group(2))
                timestamp = mins * 60 + secs
            else:
                continue
        else:
            hrs = int(ts_match.group(1))
            mins = int(ts_match.group(2))
            secs = float(ts_match.group(3))
            timestamp = hrs * 3600 + mins * 60 + secs

        text_lines = [
            l.strip() for l in lines_in_block[1:]
            if l.strip() and "-->" not in l and not l.strip().isdigit()
        ]
        if not text_lines:
            continue

        # In YouTube rolling ASR WebVTT, multiple lines are displayed for visual context:
        # The line containing word tags (<...>) is the active speech being spoken right now.
        tagged_lines = [l for l in text_lines if "<" in l and ">" in l]
        if tagged_lines:
            target_line = tagged_lines[-1]
        else:
            target_line = text_lines[-1]

        # 1. Strip inline HTML/XML tags and word timestamps
        text = re.sub(r"<[^>]+>", "", target_line).strip()

        # 2. Decode HTML entities (&amp;, &#39;, &quot;, &nbsp;)
        text = html.unescape(text)

        # 3. Deduplicate consecutive repeated lines
        if text and (not lines or lines[-1]["text"] != text):
            lines.append({"time": timestamp, "text": text})

    return sorted(lines, key=lambda x: x["time"])


def format_srt(lines: List[Dict[str, Any]]) -> str:
    """Formats normalized cues list into standard SubRip (.srt) subtitle text."""
    def _sec_to_srt_time(sec: float) -> str:
        hours = int(sec // 3600)
        mins = int((sec % 3600) // 60)
        secs = int(sec % 60)
        millis = int(round((sec - int(sec)) * 1000))
        return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    srt_blocks = []
    for i, line in enumerate(lines, 1):
        start_ts = _sec_to_srt_time(line["time"])
        if i < len(lines):
            end_sec = max(line["time"] + 1.0, lines[i]["time"] - 0.05)
        else:
            end_sec = line["time"] + 3.0
        end_ts = _sec_to_srt_time(end_sec)
        text = line.get("text", "").strip()
        srt_blocks.append(f"{i}\n{start_ts} --> {end_ts}\n{text}")

    return "\n\n".join(srt_blocks) + "\n"


def clean_artist_string(artist: str) -> str:
    if not artist:
        return ""
    a = artist.strip()
    a = re.sub(r"(?i)\s*-\s*Topic$", "", a)
    a = re.sub(r"(?i)VEVO$", "", a)
    a = re.sub(r"(?i)\s+(Official|Records|Music|Entertainment|Channel|TV)$", "", a)
    if re.match(r"^[A-Z][a-z]+[A-Z][a-z]+$", a):
        a = re.sub(r"([a-z])([A-Z])", r"\1 \2", a)
    return a.strip()


def parse_artist_and_title(raw_title: str, channel_name: str = "") -> Tuple[str, str]:
    t = (raw_title or "").strip()
    c = clean_artist_string(channel_name)
    
    t_clean = re.sub(r"(?i)\s*[\(\[\{](?:official\s*(?:music\s*)?video|official\s*audio|official|music\s*video|audio|lyrics|lyric\s*video|mv|hd|4k|1080p|remastered(?:\s*\d{4})?|visualizer|audio\s*track|prod\.[^\)\]\}]*|feat\.[^\)\]\}]*|ft\.[^\)\]\}]*)[\)\]\}]", "", t)
    t_clean = re.sub(r"(?i)\s*-\s*YouTube$", "", t_clean).strip()
    t_clean = re.sub(r"[「『](.*?)[」』]", r"\1", t_clean).strip()

    sep_match = re.search(r"\s+[-–—:|•]\s+", t_clean)
    if sep_match:
        part1 = t_clean[:sep_match.start()].strip()
        part2 = t_clean[sep_match.end():].strip()
        return clean_artist_string(part1), part2
    
    return c, t_clean


def clean_album_name(album: str) -> str:
    """
    Strips store-specific classification tags such as ' - EP', ' - Single', ' [EP]', ' (EP)', ' - LP'
    to leave the pure, original artistic album title (e.g. 'I. - EP' -> 'I.', 'THE BOOK 3 [EP]' -> 'THE BOOK 3').
    """
    if not album:
        return ""
    a = album.strip()
    a = re.sub(r"(?i)\s*[-–—]\s*(?:EP|Single|LP)$", "", a)
    a = re.sub(r"(?i)\s*[\(\[](?:EP|Single|LP)[\)\]]$", "", a)
    return a.strip()


def _is_artist_match(candidate_artist: Optional[str], parsed_artist: str, channel_artist: str) -> bool:
    if not candidate_artist:
        return False
    ca = candidate_artist.lower().strip()
    raw_candidates = [a.lower().strip() for a in [parsed_artist, channel_artist] if a and a.strip()]
    if not raw_candidates:
        return True
    
    ca_parts = [p.strip() for p in re.split(r"(?i)\s*(?:feat\.?|ft\.?|&|x|/|,|\band\b)\s*", ca) if p.strip()]
    
    cand_parts = []
    for c in raw_candidates:
        cand_parts.append(c)
        cand_parts.extend([p.strip() for p in re.split(r"(?i)\s*(?:feat\.?|ft\.?|&|x|/|,|\band\b)\s*", c) if p.strip()])

    for c in cand_parts:
        for part in ca_parts:
            if part == c:
                return True
            part_clean = re.sub(r"(?i)\s*(?:official|topic|music|records|band|vevo)$", "", part).strip()
            c_clean = re.sub(r"(?i)\s*(?:official|topic|music|records|band|vevo)$", "", c).strip()
            if part_clean == c_clean:
                return True
            if part == f"the {c}" or c == f"the {part}":
                return True
    return False


def search_album_waterfall(title: str, artist: str = "") -> Optional[str]:
    """
    Searches multi-layer online music databases (iTunes API -> LRCLIB API -> MusicBrainz API)
    using smart parsed (artist, title) queries to discover the true official Album name.
    Strictly enforces artist validation to avoid matching unrelated releases with identical song titles.
    """
    import urllib.request
    import urllib.parse
    import json

    parsed_art, parsed_title = parse_artist_and_title(title, artist)
    effective_artist = parsed_art or artist or ""

    queries = []
    if parsed_art and parsed_title:
        queries.append((f"{parsed_art} {parsed_title}", parsed_art))
    if artist and parsed_title and artist.lower() != parsed_art.lower():
        queries.append((f"{artist} {parsed_title}", artist))
    if title:
        queries.append((title, effective_artist))

    for q_clean, expected_artist in queries:
        q_clean = q_clean.strip()
        if not q_clean:
            continue

        # 1. iTunes Store Search API (Global catalog)
        try:
            url = f"https://itunes.apple.com/search?term={urllib.parse.quote(q_clean)}&entity=song&limit=5"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for item in data.get("results", []):
                    item_art = item.get("artistName", "")
                    if effective_artist and not _is_artist_match(item_art, parsed_art, artist):
                        continue
                    alb = item.get("collectionName")
                    if alb and alb.strip() and not alb.strip().lower().endswith(" - single"):
                        return clean_album_name(alb)
                for item in data.get("results", []):
                    item_art = item.get("artistName", "")
                    if effective_artist and not _is_artist_match(item_art, parsed_art, artist):
                        continue
                    alb = item.get("collectionName")
                    if alb and alb.strip():
                        return clean_album_name(alb)
        except Exception as e:
            logger.debug(f"iTunes album search error: {e}")

        # 2. LRCLIB API
        try:
            url = f"https://lrclib.net/api/search?q={urllib.parse.quote(q_clean)}"
            req = urllib.request.Request(url, headers={"User-Agent": "ZineScraper/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for item in data:
                    item_art = item.get("artistName", "")
                    if effective_artist and not _is_artist_match(item_art, parsed_art, artist):
                        continue
                    alb = item.get("albumName")
                    if alb and alb.strip() and not alb.strip().lower().endswith(" - single"):
                        return clean_album_name(alb)
                for item in data:
                    item_art = item.get("artistName", "")
                    if effective_artist and not _is_artist_match(item_art, parsed_art, artist):
                        continue
                    alb = item.get("albumName")
                    if alb and alb.strip():
                        return clean_album_name(alb)
        except Exception as e:
            logger.debug(f"LRCLIB album search error: {e}")

        # 3. MusicBrainz API
        try:
            target_title = parsed_title or q_clean
            query_parts = [f"recording:\"{target_title}\""]
            if effective_artist:
                query_parts.append(f"artist:\"{effective_artist}\"")
            query_str = " AND ".join(query_parts)
            url = f"https://musicbrainz.org/ws/2/recording/?query={urllib.parse.quote(query_str)}&fmt=json&limit=5"
            req = urllib.request.Request(url, headers={"User-Agent": "ZineScraper/1.0 ( valsedeanshu@gmail.com )"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                for rec in data.get("recordings", []):
                    artist_credits = rec.get("artist-credit", [])
                    rec_art = " ".join([ac.get("name", "") for ac in artist_credits if isinstance(ac, dict)])
                    if effective_artist and not _is_artist_match(rec_art, parsed_art, artist):
                        continue
                    for rel in rec.get("releases", []):
                        rel_grp = rel.get("release-group") or {}
                        pri_type = (rel_grp.get("primary-type") or "").lower()
                        sec_types = [t.lower() for t in (rel_grp.get("secondary-types") or [])]
                        if "audiobook" in sec_types or "spokenword" in sec_types or "audio drama" in sec_types or "interview" in sec_types:
                            continue
                        if pri_type == "other" and not sec_types:
                            continue
                        alb = rel.get("title")
                        if alb and alb.strip() and not alb.strip().lower().endswith(" - single"):
                            return clean_album_name(alb)
        except Exception as e:
            logger.debug(f"MusicBrainz album search error: {e}")

    return None


def _tag_audio_file(
    media_path: Path,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    track_number: Optional[int] = None
) -> None:
    """Ensures audio file is explicitly tagged with Title, Artist, Album, and Track Number using Mutagen/FFmpeg."""
    if not media_path.exists():
        return
    ext = media_path.suffix.lower()
    try:
        if ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(str(media_path))
            if title: audio["title"] = [title]
            if artist: audio["artist"] = [artist]
            if album: audio["album"] = [album]
            if track_number: audio["tracknumber"] = [str(track_number)]
            audio.save()
            return
        elif ext == ".mp3":
            from mutagen.easyid3 import EasyID3
            try:
                audio = EasyID3(str(media_path))
            except Exception:
                from mutagen.id3 import ID3, ID3NoHeaderError
                try:
                    ID3(str(media_path))
                except ID3NoHeaderError:
                    id3 = ID3()
                    id3.save(str(media_path))
                audio = EasyID3(str(media_path))
            if title: audio["title"] = [title]
            if artist: audio["artist"] = [artist]
            if album: audio["album"] = [album]
            if track_number: audio["tracknumber"] = [str(track_number)]
            audio.save()
            return
        elif ext in [".m4a", ".mp4", ".aac"]:
            from mutagen.mp4 import MP4
            audio = MP4(str(media_path))
            if title: audio["\xa9nam"] = [title]
            if artist: audio["\xa9ART"] = [artist]
            if album: audio["\xa9alb"] = [album]
            if track_number: audio["trkn"] = [(int(track_number), 0)]
            audio.save()
            return
        else:
            from mutagen import File as MutagenFile
            audio = MutagenFile(str(media_path), easy=True)
            if audio is not None:
                if title: audio["title"] = [title]
                if artist: audio["artist"] = [artist]
                if album: audio["album"] = [album]
                if track_number is not None: audio["tracknumber"] = [str(track_number)]
                audio.save()
                return
    except Exception as e:
        logger.debug(f"Mutagen container tagging failed ({ext}): {e}")

    try:
        from core.bake_engine import bake_metadata_and_cover
        bake_metadata_and_cover(
            media_path,
            title=title or "",
            artist=artist or "",
            album=album or "",
            track=str(track_number) if track_number else ""
        )
    except Exception as e:
        logger.debug(f"FFmpeg tag bake fallback error: {e}")


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
            auto_fetch_lyrics(audio_path)
    except Exception as e:
        logger.debug(f"_write_yt_lyrics error: {e}")


def get_subtitle_save_path(media_path: Path, is_audio: bool = True, is_batch: bool = False) -> Path:
    """
    Computes the standard companion subtitle/lyrics save path:
    - Quick Grab (single file): sibling file -> <media_path>.lrc or <media_path>.srt
    - Vacuum / Batch (album/playlist/folder):
        * For audio: <parent>/lyrics/<stem>.lrc
        * For video: <parent>/subtitles/<stem>.srt
    """
    path_str = str(media_path)
    is_quick_grab = "Quick grab" in path_str and not is_batch
    if is_quick_grab:
        return media_path.with_suffix(".lrc" if is_audio else ".srt")
    else:
        sub_folder_name = "lyrics" if is_audio else "subtitles"
        ext = ".lrc" if is_audio else ".srt"
        return media_path.parent / sub_folder_name / f"{media_path.stem}{ext}"


class YoutubeEngine(VideoEngine):
    """
    Extended VideoEngine for YouTube with support for Music mode, Album Tagging,
    Custom Thumbnails, and AI / Official Subtitles extraction.
    """

    def fetch_youtube_subtitles(self, url: str) -> List[Dict[str, Any]]:
        """
        Fetches official or AI auto-generated subtitles for a given YouTube URL.
        Returns: [{'time': float, 'text': str}, ...]
        """
        from core.paths import PathAuthority
        temp_root = PathAuthority().get_temp_root()
        token = f"sub_{int(time.time() * 1000)}"
        sub_dir = temp_root / token
        sub_dir.mkdir(parents=True, exist_ok=True)
        out_tmpl = str(sub_dir / "sub.%(ext)s")

        import shutil
        ytdlp_bin = shutil.which("yt-dlp") or "yt-dlp"
        cmd = [
            ytdlp_bin,
            "--no-warnings", "--quiet", "--no-playlist",
            "--write-auto-sub", "--write-sub",
            "--sub-format", "vtt/lrc/best",
            "--sub-langs", "en,en.*,en-orig,en-US,en-GB,hi,hi.*,hin,hi-orig,all",
            "--skip-download",
            "-o", out_tmpl,
            url
        ]

        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)

            def _priority(f: str) -> int:
                fl = f.lower()
                if fl.endswith(".en.vtt") or fl.endswith(".en.lrc"): return 0
                if ".en-orig" in fl or ".en" in fl or "english" in fl: return 1
                if fl.endswith(".hi.vtt") or fl.endswith(".hi.lrc"): return 2
                if ".hi-orig" in fl or ".hi" in fl or "hindi" in fl or "hin" in fl: return 3
                return 4

            files = sorted([f for f in os.listdir(sub_dir) if f.startswith("sub.")], key=_priority)
            for fname in files:
                fpath = sub_dir / fname
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    if fname.endswith(".vtt"):
                        parsed = parse_vtt(content)
                        if parsed:
                            return parsed
                    elif fname.endswith(".lrc"):
                        from core.lyrics_engine import parse_lrc
                        parsed = parse_lrc(content)
                        if parsed:
                            return parsed
                except Exception as e:
                    logger.debug(f"Error reading sub file {fname}: {e}")
        except Exception as e:
            logger.debug(f"yt-dlp subtitle fetch error: {e}")
        finally:
            try:
                import shutil
                shutil.rmtree(sub_dir, ignore_errors=True)
            except Exception:
                pass

        return []

    def fetch_and_save_subtitles(self, url: str, media_path: Path, is_audio: bool = True, is_batch: bool = False) -> Optional[Path]:
        """
        Fetches official/AI subtitles from YouTube and saves into the appropriate location:
        - Quick Grab: sibling file -> <media_path>.lrc / <media_path>.srt
        - Vacuum / Batch: inside lyrics/ or subtitles/ subfolder
        Returns path to the saved subtitle file if successful, else None.
        """
        parsed = self.fetch_youtube_subtitles(url)
        if not parsed:
            return None

        try:
            save_path = get_subtitle_save_path(media_path, is_audio=is_audio, is_batch=is_batch)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            if is_audio:
                from core.lyrics_engine import format_lrc
                lrc_text = format_lrc(parsed)
                save_path.write_text(lrc_text, encoding="utf-8")
            else:
                srt_text = format_srt(parsed)
                save_path.write_text(srt_text, encoding="utf-8")
            return save_path
        except Exception as e:
            logger.error(f"Failed to save subtitles: {e}")
            return None

    def _get_channel_pfp_url(self, channel_url: str) -> Optional[str]:
        if not channel_url:
            return None
        try:
            resp = requests.get(channel_url, headers=self.headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                return og_image.get('content')
                
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
        
        for old_loc in [root_dir / "metadata.json", root_dir / "metadata" / "metadata.json"]:
            if old_loc.exists() and not meta_path.exists():
                try:
                    old_loc.rename(meta_path)
                except Exception: pass
        
        if not meta_path.exists() or info.get('_type') == 'playlist':
            metadata = {
                "channel_name": info.get('uploader') or info.get('channel') or info.get('title') or "Unknown",
                "channel_id": info.get('uploader_id') or info.get('channel_id') or info.get('id') or "Unknown",
                "album": info.get('album') or info.get('title') or "Single",
                "source": source,
                "url": info.get('webpage_url') or info.get('original_url') or "",
                "total_videos": len(info.get('entries', [])) if info.get('_type') == 'playlist' else 1,
                "description": info.get('description', ''),
            }
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

        if skip_cover:
            return

        target_cover_dir = channel_root if channel_root else root_dir
        cover_path = target_cover_dir / "cover.jpg"
        
        if not cover_path.exists():
            thumb_url = None
            
            channel_url = info.get('channel_url') or info.get('uploader_url')
            if not channel_url and info.get('_type') == 'playlist' and 'channel' in (info.get('webpage_url') or ''):
                channel_url = info.get('webpage_url')
                
            if channel_url:
                thumb_url = self._get_channel_pfp_url(channel_url)
                
            if not thumb_url:
                thumbnails = info.get('thumbnails', [])
                if thumbnails:
                    avatar_thumb = None
                    for thumb in reversed(thumbnails):
                        w = thumb.get('width', 0)
                        h = thumb.get('height', 1)
                        if w > 0 and (w / h) < 1.3:
                            avatar_thumb = thumb
                            break
                    
                    if not avatar_thumb:
                        avatar_thumb = thumbnails[-1]
 
                    thumb_url = avatar_thumb.get('url')
 
            if thumb_url:
                try:
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
        fixed_artist: Optional[str] = None,
        fixed_album: Optional[str] = None,
        **kwargs
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
            fixed_artist=fixed_artist,
            fixed_album=fixed_album,
            **kwargs
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
        fixed_artist: Optional[str] = None,
        fixed_album: Optional[str] = None,
        download_subs: bool = True,
        **kwargs
    ) -> bool:
        """
        Main entry point for downloading YouTube content with specific modes, quality, and rich metadata.
        """
        is_music = "music" in mode
        videos_dir = output_dir
        videos_dir.mkdir(parents=True, exist_ok=True)

        ext = audio_format.lower() if (is_music and audio_format) else "flac" if is_music else "mp4"
        
        if fixed_title:
            clean_title = "".join([c for c in fixed_title if c.isalnum() or c in " .-_()"]).strip()
            # If song or quick grab, ensure no accidental leading index number
            if is_music or ("Quick grab" in str(videos_dir)):
                clean_title = re.sub(r'^\d+[\.\s\-]+\s*', '', clean_title).strip() or clean_title
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

        # ── Parallel subtitles & lyrics fetch: start BEFORE yt-dlp so it runs concurrently ──
        prefetched_cues = []
        prefetched_lrc_source = [None]

        def _bg_subs_fetch():
            if not download_subs:
                return
            try:
                if is_music:
                    from core.lyrics_engine import waterfall_fetch_lyrics, clean_track_string
                    t = clean_track_string(fixed_title or "")
                    a = clean_track_string(fixed_artist or "")
                    if t:
                        lines, src = waterfall_fetch_lyrics(t, a)
                        if lines:
                            prefetched_cues.extend(lines)
                            prefetched_lrc_source[0] = src
                            return

                # If video or if music had no database lyrics, extract YouTube subtitles
                subs = self.fetch_youtube_subtitles(url)
                if subs:
                    prefetched_cues.extend(subs)
                    prefetched_lrc_source[0] = "youtube_captions"
            except Exception as e:
                logger.debug(f"YT bg subs fetch error: {e}")

        if download_subs:
            subs_thread = threading.Thread(target=_bg_subs_fetch, daemon=True)
            subs_thread.start()
        else:
            subs_thread = None

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
                final_path = tmp_path
                if is_music and not final_path.exists() and final_path.with_suffix(f".{ext}").exists():
                     final_path = final_path.with_suffix(f".{ext}")
                elif not is_music and not final_path.exists() and final_path.with_suffix(".mp4").exists():
                     final_path = final_path.with_suffix(".mp4")

                if is_music:
                    if not fixed_album or fixed_album.endswith(" - Single") or fixed_album == fixed_title:
                        try:
                            rec_alb = search_album_waterfall(fixed_title or clean_title, fixed_artist or "")
                            if rec_alb:
                                fixed_album = rec_alb
                            elif not fixed_album:
                                fixed_album = f"{fixed_artist or clean_title} - Single"
                        except Exception:
                            if not fixed_album:
                                fixed_album = f"{fixed_artist or clean_title} - Single"

                if custom_thumbnail and custom_thumbnail.exists():
                    final_thumb_path = final_path.with_name(final_path.name.replace(".tmp.", "."))
                    success = self._apply_custom_thumbnail(
                        final_path, custom_thumbnail, final_thumb_path, is_music,
                        title=fixed_title, artist=fixed_artist, album=fixed_album
                    )
                    if success:
                        if final_path.exists(): final_path.unlink()
                        if is_music:
                            _tag_audio_file(final_thumb_path, title=fixed_title, artist=fixed_artist, album=fixed_album)

                        # Write concurrently fetched subtitles / lyrics
                        if download_subs and subs_thread:
                            try:
                                subs_thread.join(timeout=10)
                                if prefetched_cues:
                                    save_p = get_subtitle_save_path(final_thumb_path, is_audio=is_music)
                                    save_p.parent.mkdir(parents=True, exist_ok=True)
                                    if is_music:
                                        from core.lyrics_engine import format_lrc
                                        save_p.write_text(format_lrc(prefetched_cues), encoding="utf-8")
                                    else:
                                        save_p.write_text(format_srt(prefetched_cues), encoding="utf-8")
                            except Exception as e:
                                logger.debug(f"Prefetched subs write error: {e}")

                        return True
                    return False
                
                if is_music:
                    _tag_audio_file(final_path, title=fixed_title, artist=fixed_artist, album=fixed_album)

                # Write concurrently fetched subtitles / lyrics
                if download_subs and subs_thread:
                    try:
                        subs_thread.join(timeout=10)
                        if prefetched_cues:
                            save_p = get_subtitle_save_path(final_path, is_audio=is_music)
                            save_p.parent.mkdir(parents=True, exist_ok=True)
                            if is_music:
                                from core.lyrics_engine import format_lrc
                                save_p.write_text(format_lrc(prefetched_cues), encoding="utf-8")
                            else:
                                save_p.write_text(format_srt(prefetched_cues), encoding="utf-8")
                    except Exception as e:
                        logger.debug(f"Prefetched subs write error: {e}")

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

    def _apply_custom_thumbnail(
        self, 
        media_path: Path, 
        cover_path: Path, 
        output_path: Path, 
        is_audio: bool,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None
    ) -> bool:
        """Uses ffmpeg to bake the custom cover and metadata into the media file."""
        try:
            import shutil
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
            cmd = [
                ffmpeg_bin, "-y",
                "-i", str(media_path),
                "-i", str(cover_path),
                "-map", "0:a" if is_audio else "0",
                "-map", "1:0" if is_audio else "1",
                "-c", "copy",
                "-map_metadata", "0",
                "-disposition:v:0" if is_audio else "-disposition:v:1", "attached_pic",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
            ]
            if title:
                cmd.extend(["-metadata", f"title={title}"])
            if artist:
                cmd.extend(["-metadata", f"artist={artist}"])
            if album:
                cmd.extend(["-metadata", f"album={album}"])
                
            if is_audio and output_path.suffix.lower() == ".mp3":
                cmd.extend(["-id3v2_version", "3"])
                
            cmd.extend(["-loglevel", "error", str(output_path)])

            subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg failed to apply cover: {e}")
            return False
