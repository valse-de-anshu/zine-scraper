import re
import time
import base64
import logging
import threading
import requests
from bs4 import BeautifulSoup
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
from pathlib import Path
from typing import Dict, Any, Optional
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

LANG_PATTERNS = [
    ('en', 'English', [r'english', r'\beng\b', r'\ben\b', r'_eng?\.', r'\.eng?\.', r'\[eng?\]']),
    ('es', 'Spanish', [r'spanish', r'espanol', r'español', r'\bspa\b', r'\bes\b', r'_spa?\.', r'\.spa?\.', r'\[spa?\]']),
    ('fr', 'French', [r'french', r'francais', r'français', r'\bfre\b', r'\bfr\b', r'\bfra\b']),
    ('de', 'German', [r'german', r'deutsch', r'\bger\b', r'\bdeu\b', r'\bde\b']),
    ('pt', 'Portuguese', [r'portuguese', r'portugues', r'português', r'\bpor\b', r'\bpt\b']),
    ('it', 'Italian', [r'italian', r'italiano', r'\bita\b', r'\bit\b']),
    ('ja', 'Japanese', [r'japanese', r'nihongo', r'\bjpn\b', r'\bja\b', r'\bjp\b']),
    ('zh', 'Chinese', [r'chinese', r'mandarin', r'\bchi\b', r'\bzho\b', r'\bzh\b']),
    ('ru', 'Russian', [r'russian', r'\brus\b', r'\bru\b']),
    ('ko', 'Korean', [r'korean', r'\bkor\b', r'\bko\b']),
    ('ar', 'Arabic', [r'arabic', r'\bara\b', r'\bar\b']),
    ('id', 'Indonesian', [r'indonesian', r'bahasa', r'\bind\b', r'\bid\b']),
]

def detect_subtitle_language(text: str) -> tuple[str, str]:
    t = text.lower()
    for code, name, patterns in LANG_PATTERNS:
        for p in patterns:
            if re.search(p, t):
                return code, name
    return 'und', 'Available'


class HanimeRedEngine(VideoEngine):
    def __init__(self):
        super().__init__()
        self.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(self.headers)

    def extract_subtitles_candidates(self, url: str) -> list[dict]:
        """
        Extracts all candidate subtitle streams and languages from the episode and nhplayer iframe.
        Returns candidates prioritized with English ('en') first, followed by any other available languages.
        """
        candidates = []
        seen_urls = set()

        def add_candidate(sub_url: str, label_hint: str = ""):
            if not sub_url or sub_url in seen_urls:
                return
            if not ('.srt' in sub_url.lower() or '.vtt' in sub_url.lower()):
                return
            seen_urls.add(sub_url)
            lang_code, lang_name = detect_subtitle_language(f"{label_hint} {sub_url}")
            ext = "vtt" if ".vtt" in sub_url.lower() else "srt"
            candidates.append({
                "url": sub_url,
                "lang": lang_code,
                "name": lang_name,
                "ext": ext
            })

        timeout_req = (10, 25)

        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout_req)
                if r.status_code != 200:
                    time.sleep(1)
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                iframe = soup.find("iframe", src=lambda src: src and "nhplayer.com" in src)
                if iframe and iframe.get("src"):
                    ifr_url = iframe["src"]
                    ifr_res = None
                    for ifr_attempt in range(3):
                        try:
                            ifr_res = self.session.get(ifr_url, timeout=timeout_req)
                            if ifr_res.status_code == 200:
                                break
                        except Exception:
                            time.sleep(1)

                    if ifr_res and ifr_res.status_code == 200:
                        ifr_soup = BeautifulSoup(ifr_res.text, "html.parser")

                        for li in ifr_soup.find_all("li", attrs={"data-id": True}):
                            data_id = li.get("data-id", "")
                            server_label = li.text.strip()
                            s_match = re.search(r'[?&]s=([a-zA-Z0-9+/=]+)', data_id)
                            if s_match:
                                try:
                                    raw = base64.b64decode(s_match.group(1)).decode("utf-8", errors="ignore")
                                    if raw.startswith("http"):
                                        add_candidate(raw, server_label)
                                        # If candidate is not English, probe if an English variant exists on CDN
                                        if "cdn.htstreaming.com" in raw and "/english/" not in raw:
                                            en_variant = re.sub(
                                                r'/(spanish|french|german|japanese|portuguese|italian|russian|korean)/',
                                                '/english/',
                                                raw,
                                                flags=re.IGNORECASE
                                            )
                                            en_variant = re.sub(
                                                r'(?:[_\-\s](?:spa|fre|ger|jpn|por|ita|rus|kor))(\.srt|\.vtt)',
                                                r' ENG\1',
                                                en_variant,
                                                flags=re.IGNORECASE
                                            )
                                            if en_variant != raw and en_variant not in seen_urls:
                                                try:
                                                    head = self.session.head(en_variant, timeout=5)
                                                    if head.status_code == 200:
                                                        add_candidate(en_variant, "English")
                                                except Exception:
                                                    pass
                                except Exception:
                                    pass

                            if data_id:
                                try:
                                    nh_url = f"https://nhplayer.com/{data_id}"
                                    nh_res = self.session.get(nh_url, timeout=10)
                                    for tm in re.finditer(r'\{[^{}]*file\s*:\s*"([^"]+\.(?:srt|vtt)[^"]*)"[^{}]*\}', nh_res.text):
                                        block = tm.group(0)
                                        sub_f = tm.group(1).replace(r"\/", "/")
                                        lbl_m = re.search(r'label\s*:\s*"([^"]+)"', block)
                                        lbl = lbl_m.group(1) if lbl_m else ""
                                        add_candidate(sub_f, f"{server_label} {lbl}")
                                except Exception:
                                    pass
                if candidates:
                    break
            except Exception as e:
                if attempt == 2:
                    logger.debug(f"Subtitle extraction notice for {url}: {e}")
                time.sleep(1)

        # English ('en') candidates first, followed by any other available languages
        candidates.sort(key=lambda c: 0 if c["lang"] == "en" else 1)
        return candidates

    def extract_subtitles_url(self, url: str) -> Optional[str]:
        """
        Returns best candidate subtitle URL (English first, fallback to available).
        """
        candidates = self.extract_subtitles_candidates(url)
        return candidates[0]["url"] if candidates else None

    def download_subtitle(self, sub_url: str, output_dir: Path, clean_title: str, lang: str = "en") -> bool:
        """
        Downloads a specific subtitle URL directly alongside the video file.
        """
        if not sub_url:
            return False
        try:
            ext = ".vtt" if ".vtt" in sub_url.lower() else ".srt"
            dest_lang = output_dir / f"{clean_title}.{lang}{ext}"
            dest_plain = output_dir / f"{clean_title}{ext}"

            r = self.session.get(sub_url, timeout=(10, 25))
            if r.status_code == 200 and len(r.content) > 50:
                dest_lang.write_bytes(r.content)
                dest_plain.write_bytes(r.content)
                logger.info(f"Downloaded subtitle: {dest_lang.name}")
                return True
        except Exception as e:
            logger.debug(f"Failed to download subtitle from {sub_url}: {e}")
        return False

    def download_subtitles(self, url: str, output_dir: Path, clean_title: str) -> bool:
        """
        Looks for English subtitles first. If English cannot be found or fails to download,
        falls back to whatever language is available.
        Saves both <clean_title>.<lang>.<ext> and <clean_title>.<ext> directly into output_dir.
        """
        candidates = self.extract_subtitles_candidates(url)
        if not candidates:
            return False

        has_english = any(c["lang"] == "en" for c in candidates)

        for c in candidates:
            sub_url = c["url"]
            lang = c["lang"]
            name = c["name"]
            ext = f".{c['ext']}"

            for attempt in range(3):
                try:
                    r = self.session.get(sub_url, timeout=(10, 25))
                    if r.status_code == 200 and len(r.content) > 50:
                        from core.video_engine import save_subtitle_as_srt
                        dest_lang = save_subtitle_as_srt(r.content, output_dir, clean_title, lang=lang)
                        dest_default = save_subtitle_as_srt(r.content, output_dir, clean_title, lang=None)

                        if lang == "en":
                            logger.info(f"Downloaded English subtitle (.srt): {dest_lang.name}")
                        else:
                            if not has_english:
                                logger.info(f"English subtitle not found; falling back to {name} ({lang}) subtitle (.srt): {dest_lang.name}")
                            else:
                                logger.info(f"English subtitle unavailable; fell back to {name} ({lang}) subtitle (.srt): {dest_lang.name}")
                        return True
                except Exception as e:
                    if attempt == 2:
                        logger.debug(f"Failed candidate subtitle download from {sub_url}: {e}")
                    time.sleep(1)

        return False

    def download_hanime_red_video(
        self,
        url: str,
        output_dir: Path,
        progress_hook,
        quality: str = "1080p",
        fixed_title: Optional[str] = None,
        subtitle_dir: Optional[Path] = None,
    ) -> bool:
        """
        Direct high-speed video download with concurrent parallel subtitle retrieval into video/subtitle folder.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        if fixed_title:
            clean_title = "".join(c for c in fixed_title if c.isalnum() or c in " .-_()'")
            clean_title = re.sub(r'[<>:"/\\|?*]', '', clean_title).strip() or "video"
        else:
            clean_title = "video"

        # Resolve subtitle folder inside video: output_dir / "subtitle"
        if subtitle_dir is None:
            if output_dir.name == "video":
                subtitle_dir = output_dir / "subtitle"
            else:
                subtitle_dir = output_dir / "video" / "subtitle"
        subtitle_dir.mkdir(parents=True, exist_ok=True)

        # 1. Spawn concurrent subtitle download in parallel alongside video stream download (into video/subtitle/)
        sub_thread = threading.Thread(
            target=self.download_subtitles,
            args=(url, subtitle_dir, clean_title),
            daemon=True
        )
        sub_thread.start()

        # 2. Concurrently proceed with optimized aria2c video stream download
        success = self.download_video(
            url=url,
            output_dir=output_dir,
            progress_hook=progress_hook,
            fixed_title=fixed_title
        )

        # 3. Ensure background subtitle thread completes
        try:
            sub_thread.join(timeout=15)
        except Exception:
            pass

        # 4. Post-download verification: if video succeeded and subtitles were not saved, retry once
        if success:
            has_sub = any(subtitle_dir.glob(f"{clean_title}*.srt"))
            if not has_sub:
                try:
                    self.download_subtitles(url, subtitle_dir, clean_title)
                except Exception as e:
                    logger.debug(f"Subtitle recovery notice: {e}")
            try:
                from core.video_engine import migrate_and_clean_subtitles
                migrate_and_clean_subtitles(output_dir, subtitle_dir)
            except Exception:
                pass

        return success

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        """Downloads and verifies cover art using 2-step magic-byte and PIL verification."""
        if not avatar_url:
            return False
        try:
            from core.cover_utils import download_verified_cover
            saved = download_verified_cover(
                cover_url=avatar_url,
                folder=dest.parent,
                filename=dest.stem,
                headers=self.headers
            )
            return saved is not None
        except Exception as e:
            logger.debug(f"Failed to download verified cover: {e}")
            return False

    def save_metadata(
        self,
        root_dir: Path,
        info: Dict[str, Any],
        source: str,
        model_name: str,
        avatar_url: Optional[str] = None,
        videos: Optional[list] = None,
        skip_cover: bool = False,
        custom_metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Persists clean, normalized metadata and 2-step verified cover art into folder.
        """
        url = info.get("url", "")
        if custom_metadata and "URL" in custom_metadata:
            url = custom_metadata["URL"]

        alt_title = (custom_metadata.get("Alternative Title") or info.get("alt_title") or "") if custom_metadata else ""
        studio = (custom_metadata.get("Studio") or info.get("uploader_id") or "") if custom_metadata else ""
        tags = (custom_metadata.get("Tags") or "") if custom_metadata else ""
        summary = (custom_metadata.get("Description") or "") if custom_metadata else ""
        raw_date = (custom_metadata.get("Release Date") or info.get("upload_date") or "") if custom_metadata else ""
        year = str(raw_date).split("-")[0] if raw_date else ""
        views = str(custom_metadata.get("Views") or info.get("views") or "") if custom_metadata else ""
        likes = str(custom_metadata.get("Likes") or info.get("likes") or "") if custom_metadata else ""

        from core.metadata_engine import MetadataEngine, ZineMetadataPayload
        if isinstance(tags, list):
            tags_list = tags
        elif isinstance(tags, str):
            tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        else:
            tags_list = []

        payload = ZineMetadataPayload(
            title=model_name,
            type="Series",
            alt_title=alt_title,
            author=studio or model_name,
            artist=studio,
            studio=studio,
            description=summary,
            tags=tags_list,
            year=year,
            views=views,
            likes=likes,
            url=url
        )
        MetadataEngine.save_metadata(root_dir, payload)

        # 2-step verification cover download
        if not skip_cover and avatar_url:
            from core.cover_utils import download_verified_cover
            download_verified_cover(
                cover_url=avatar_url,
                folder=root_dir,
                filename="cover",
                headers=self.headers
            )
