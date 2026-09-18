from pathlib import Path
from typing import Dict, Any, Optional, List
from curl_cffi import requests
import re
import json
import logging
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://hentaimama.io/",
}

NON_VIDEO_EXTS = (".vtt", ".srt", ".ass", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".json", ".xml")


def _is_valid_video_url(u: str) -> bool:
    if not u or not isinstance(u, str):
        return False
    u = u.strip()
    if not u.startswith(("http://", "https://")):
        return False
    path = u.split("?")[0].lower()
    if path.endswith(NON_VIDEO_EXTS):
        return False
    if "/images/thumbnail/" in path or "/thumbnails/" in path or "thumbnail.vtt" in path:
        return False
    return True


class HentaimamaEngine(VideoEngine):
    def __init__(self):
        super().__init__()
        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update(HEADERS)
        self.headers = HEADERS

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        if not avatar_url:
            return False
        try:
            from core.cover_utils import save_verified_cover
            r = self.session.get(avatar_url, timeout=20)
            if r.status_code == 200 and len(r.content) > 500:
                saved = save_verified_cover(r.content, dest.parent, filename=dest.stem)
                return saved is not None
            return False
        except Exception:
            return False

    def save_metadata(self, root_dir: Path, info: Dict[str, Any], source: str,
                      model_name: str, avatar_url: Optional[str] = None,
                      videos: Optional[list] = None, skip_cover: bool = False, custom_metadata: Optional[Dict[str, Any]] = None):
        import json
        zine_dir = root_dir / ".zine"
        zine_dir.mkdir(parents=True, exist_ok=True)
        meta_path = zine_dir / "metadata.json"

        video_list = videos or []
        url = info.get("webpage_url") or info.get("url") or ""
        if custom_metadata and "URL" in custom_metadata:
            url = custom_metadata["URL"]
            
        studio = custom_metadata.get("Studio", "") if custom_metadata else ""
        tags = custom_metadata.get("Tags", "") if custom_metadata else ""
        summary = custom_metadata.get("Description", "") if custom_metadata else ""
        
        from core.metadata_engine import MetadataEngine, ZineMetadataPayload
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if isinstance(tags, str) else (tags or [])
        payload = ZineMetadataPayload(
            title=model_name,
            type="Series",
            author=studio or model_name,
            artist=studio,
            description=summary,
            tags=tags_list,
            url=url
        )
        MetadataEngine.save_metadata(root_dir, payload)

        if not skip_cover and avatar_url:
            cover_path = root_dir / "cover.jpg"
            if not cover_path.exists():
                self.download_avatar(avatar_url, cover_path)
    def _extract_video_from_html(self, html: str) -> Optional[str]:
        # 1. Look for sources: [...] in jwplayer / script setup
        src_m = re.search(r"sources\s*:\s*(\[[^\]]+\])", html, re.DOTALL)
        if src_m:
            files = re.findall(r"['\"]?file['\"]?\s*:\s*['\"]([^'\"]+)['\"]", src_m.group(1))
            for f in files:
                clean = f.replace(r"\/", "/")
                if _is_valid_video_url(clean):
                    return clean

        # 2. General file regex for video streams (quoted or unquoted key)
        for f in re.findall(r"['\"]?file['\"]?\s*:\s*['\"](https?://[^'\"]+)['\"]", html):
            clean = f.replace(r"\/", "/")
            if _is_valid_video_url(clean):
                return clean

        # 3. Direct mp4 / m3u8 search in html
        for m in re.finditer(r"['\"](https?://[^\s'\"<>]+\.(?:mp4|m3u8)(?:\?[^\s'\"<>]*)?)['\"]", html):
            clean = m.group(1).replace(r"\/", "/")
            if _is_valid_video_url(clean):
                return clean

        # 4. window.open download links
        dl_m = re.search(r"window\.open\(['\"](https?://[^'\"]+)['\"]\)", html)
        if dl_m:
            clean = dl_m.group(1).replace(r"\/", "/")
            if _is_valid_video_url(clean):
                return clean

        return None

    def extract_subtitles_candidates(self, page_url: str) -> List[Dict[str, str]]:
        """
        Extracts genuine companion subtitles (excluding thumbnail scrubber tracks).
        """
        candidates = []
        try:
            r = self.session.get(page_url, headers=self.headers, impersonate="chrome124", timeout=15)
            if r.status_code != 200:
                return []

            m = re.search(r"action:\s*['\"]get_player_contents['\"],\s*a:\s*['\"](\d+)['\"]", r.text)
            if not m:
                m = re.search(r"['\"]postId['\"]:\s*(\d+)", r.text)
            if not m:
                m = re.search(r"['\"]episode['\"]:\s*['\"](\d+)['\"]", r.text)

            if not m:
                return []

            post_id = m.group(1)
            ajax_headers = self.headers.copy()
            ajax_headers["X-Requested-With"] = "XMLHttpRequest"

            for opt in [1, 2, 3, 4]:
                data = {"action": "get_player_contents", "a": post_id, "i": str(opt)}
                try:
                    r_ajax = self.session.post(
                        "https://hentaimama.io/wp-admin/admin-ajax.php",
                        data=data,
                        headers=ajax_headers,
                        impersonate="chrome124",
                        timeout=10,
                    )
                    if r_ajax.status_code == 200:
                        import html as html_lib
                        items = json.loads(r_ajax.text)
                        for item in items:
                            if not item:
                                continue
                            ifr_m = re.search(r"src=['\"]([^'\"]+)['\"]", item)
                            if ifr_m:
                                ifr_url = html_lib.unescape(ifr_m.group(1))
                                if ifr_url.startswith("//"):
                                    ifr_url = f"https:{ifr_url}"
                                r_ifr = self.session.get(
                                    ifr_url,
                                    headers=self.headers,
                                    impersonate="chrome124",
                                    timeout=10,
                                )
                                if r_ifr.status_code == 200:
                                    tracks_m = re.search(r"tracks\s*:\s*(\[[^\]]+\])", r_ifr.text, re.DOTALL)
                                    if tracks_m:
                                        raw_tracks = re.findall(r"\{([^}]+)\}", tracks_m.group(1))
                                        for tr in raw_tracks:
                                            kind_m = re.search(r"['\"]?kind['\"]?\s*:\s*['\"]([^'\"]+)['\"]", tr)
                                            kind = kind_m.group(1).lower() if kind_m else ""
                                            if kind in ("thumbnails", "preview", "thumb"):
                                                continue
                                            file_m = re.search(r"['\"]?file['\"]?\s*:\s*['\"]([^'\"]+)['\"]", tr)
                                            if not file_m:
                                                continue
                                            sub_url = file_m.group(1).replace(r"\/", "/")
                                            if "/images/thumbnail/" in sub_url.lower() or "thumbnail.vtt" in sub_url.lower():
                                                continue
                                            lbl_m = re.search(r"['\"]?label['\"]?\s*:\s*['\"]([^'\"]+)['\"]", tr)
                                            label = lbl_m.group(1).strip() if lbl_m else "English"
                                            lang = "en" if "eng" in label.lower() else "und"
                                            candidates.append({"url": sub_url, "label": label, "lang": lang})
                except Exception:
                    pass
                if candidates:
                    break
        except Exception as e:
            logger.debug(f"[Hentaimama] Subtitle candidate extraction error: {e}")

        return candidates

    def download_subtitle(self, sub_url: str, output_dir: Path, clean_title: str, lang: str = "en") -> bool:
        if not sub_url:
            return False
        try:
            ext = ".vtt" if ".vtt" in sub_url.lower() else ".srt"
            dest_lang = output_dir / f"{clean_title}.{lang}{ext}"
            dest_plain = output_dir / f"{clean_title}{ext}"

            r = self.session.get(sub_url, headers=self.headers, impersonate="chrome124", timeout=15)
            if r.status_code == 200 and len(r.content) > 50:
                output_dir.mkdir(parents=True, exist_ok=True)
                dest_lang.write_bytes(r.content)
                dest_plain.write_bytes(r.content)
                logger.info(f"[Hentaimama] Downloaded subtitle: {dest_lang.name}")
                return True
        except Exception as e:
            logger.warning(f"[Hentaimama] Failed to download subtitle {sub_url}: {e}")
        return False

    def extract_stream_url(self, page_url: str) -> Optional[str]:
        try:
            r = self.session.get(page_url, headers=self.headers, impersonate="chrome124", timeout=15)
            if r.status_code != 200:
                logger.warning(f"[Hentaimama] Failed to fetch {page_url}, status: {r.status_code}")
                return None

            # Look for episode post ID
            m = re.search(r"action:\s*['\"]get_player_contents['\"],\s*a:\s*['\"](\d+)['\"]", r.text)
            if not m:
                m = re.search(r"['\"]postId['\"]:\s*(\d+)", r.text)
            if not m:
                m = re.search(r"['\"]episode['\"]:\s*['\"](\d+)['\"]", r.text)

            if m:
                post_id = m.group(1)
                ajax_headers = self.headers.copy()
                ajax_headers["X-Requested-With"] = "XMLHttpRequest"

                for opt in [1, 2, 3, 4]:
                    data = {"action": "get_player_contents", "a": post_id, "i": str(opt)}
                    try:
                        r_ajax = self.session.post(
                            "https://hentaimama.io/wp-admin/admin-ajax.php",
                            data=data,
                            headers=ajax_headers,
                            impersonate="chrome124",
                            timeout=10,
                        )
                        if r_ajax.status_code == 200:
                            import html as html_lib
                            items = json.loads(r_ajax.text)
                            for item in items:
                                if not item:
                                    continue
                                ifr_m = re.search(r"src=['\"]([^'\"]+)['\"]", item)
                                if ifr_m:
                                    ifr_url = html_lib.unescape(ifr_m.group(1))
                                    if ifr_url.startswith("//"):
                                        ifr_url = f"https:{ifr_url}"
                                    r_ifr = self.session.get(
                                        ifr_url,
                                        headers=self.headers,
                                        impersonate="chrome124",
                                        timeout=10,
                                    )
                                    if r_ifr.status_code == 200:
                                        stream_url = self._extract_video_from_html(r_ifr.text)
                                        if stream_url:
                                            logger.info(f"[Hentaimama] Found stream URL via option {opt}: {stream_url}")
                                            return stream_url
                    except Exception as e:
                        logger.debug(f"[Hentaimama] Error probing player option {opt}: {e}")

            # Fallback: direct mp4 / m3u8 search in page
            fallback = self._extract_video_from_html(r.text)
            if fallback:
                return fallback

            return None
        except Exception as e:
            logger.error(f"[Hentaimama] Exception in extract_stream_url for {page_url}: {e}")
            return None

    def download_hentaimama_video(
        self,
        url: str,
        output_dir: Path,
        progress_hook=None,
        is_audio: bool = False,
        quality: str = "",
        fixed_title: str = "",
        fixed_artist: str = "",
        pre_extracted_stream: str = "",
    ) -> bool:
        """
        Downloads a Hentaimama video using extracted direct stream.
        """
        try:
            stream_url = pre_extracted_stream or self.extract_stream_url(url)
            if not stream_url:
                logger.error(f"[Hentaimama] Could not extract stream URL for: {url}")
                return False

            self.headers["Referer"] = "https://hentaimama.io/"
            return self.download_video(
                url=url,
                output_dir=output_dir,
                progress_hook=progress_hook or (lambda d: None),
                raw_stream_url=stream_url,
                is_audio=is_audio,
                fixed_title=fixed_title,
                fixed_artist=fixed_artist,
            )
        except Exception as e:
            logger.error(f"Hentaimama download_video failed: {e}")
            return False
