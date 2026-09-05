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
            r = self.session.get(avatar_url, timeout=20)
            r.raise_for_status()
            
            ct = r.headers.get("Content-Type", "").lower().split(";")[0].strip()
            mime_map = {
                "image/jpeg": ".jpg", "image/jpg": ".jpg",
                "image/png": ".png", "image/webp": ".webp",
                "image/avif": ".avif", "image/gif": ".gif"
            }
            real_ext = mime_map.get(ct, dest.suffix or ".jpg")
            if dest.suffix.lower() != real_ext:
                dest = dest.with_suffix(real_ext)
                
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
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
        
        metadata_content = {
            "Series": model_name,
            "Source": source,
            "URL": url,
            "Total Videos": len(video_list),
            "Studio": studio,
            "Tags": tags,
            "Summary": summary,
            "videos": video_list
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata_content, f, indent=2, ensure_ascii=False)

        if not skip_cover and avatar_url:
            cover_path = root_dir / "cover.jpg"
            if not cover_path.exists():
                self.download_avatar(avatar_url, cover_path)

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

                for opt in [1, 2, 3]:
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
                                        f_m = re.search(r"file:\s*['\"]([^'\"]+)['\"]", r_ifr.text)
                                        if f_m:
                                            file_url = f_m.group(1).replace("\\/", "/")
                                            logger.info(f"[Hentaimama] Found stream URL via option {opt}: {file_url}")
                                            return file_url
                                        dl_m = re.search(r"window\.open\(['\"]([^'\"]+)['\"]\)", r_ifr.text)
                                        if dl_m:
                                            file_url = dl_m.group(1).replace("\\/", "/")
                                            return file_url
                    except Exception as e:
                        logger.debug(f"[Hentaimama] Error probing player option {opt}: {e}")

            # Fallback: direct mp4 / m3u8 search in page
            direct_m = re.search(r"['\"](https?://[^\s'\"<>]+\.(?:mp4|m3u8)(?:\?[^\s'\"<>]*)?)['\"]", r.text)
            if direct_m:
                return direct_m.group(1)

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
