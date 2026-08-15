import re
import json
import sys
import logging
from curl_cffi import requests
from pathlib import Path
from typing import Dict, Any, Callable, Optional, List
from core.video_engine import VideoEngine
import html as html_module

logger = logging.getLogger(__name__)

def _decode(raw: str) -> str:
    if not raw: return raw
    return html_module.unescape(raw)

class HentaiHavenCoEngine(VideoEngine):
    def __init__(self):
        super().__init__(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://hentaihaven.co/"
        })
        self.session = requests.Session(impersonate="chrome")
        self.session.headers.update(self.headers)

    def extract_video_info(self, url: str) -> Dict[str, Any]:
        return {
            "id": url.strip("/").split("/")[-1],
            "title": "Unknown",
            "webpage_url": url,
            "url": "",
            "upload_date": "20260101",
            "view_count": 0,
            "like_count": 0,
            "duration": 0
        }

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        if not avatar_url: return False
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
        except Exception as e:
            return False

    def save_metadata(self, root_dir: Path, info: Dict[str, Any], source: str, model_name: str, avatar_url: Optional[str] = None, videos: Optional[List[Dict[str, Any]]] = None, skip_cover: bool = False, custom_metadata: Optional[Dict[str, Any]] = None):
        zine_dir = root_dir / ".zine"
        zine_dir.mkdir(parents=True, exist_ok=True)
        meta_path = zine_dir / "metadata.json"

        video_list = videos or []
        url = info.get("webpage_url") or ""
        if custom_metadata and "URL" in custom_metadata:
            url = custom_metadata["URL"]
            
        studio = custom_metadata.get("Studio", "") if custom_metadata else ""
        tags = custom_metadata.get("Tags", "") if custom_metadata else ""
        summary = custom_metadata.get("Description", "") if custom_metadata else ""
        
        metadata_content = {
            "Series": _decode(model_name),
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
            cover_path = root_dir / "cover.png"
            if not cover_path.exists():
                self.download_avatar(avatar_url, cover_path)

    def _extract_nhplayer_m3u8(self, url: str) -> str:
        # Fetch the video page to get iframe
        res = self.session.get(url, timeout=15)
        iframe_match = re.search(r'<iframe[^>]+src=["\'](https://nhplayer.com/v/[^"\']+)["\']', res.text)
        if not iframe_match:
            if "nhplayer.com" in url:
                iframe_match = re.search(r'(https://nhplayer.com/[^"\']+)', url)
            
        nh_url = iframe_match.group(1) if iframe_match else url
            
        import subprocess
        script_path = Path(__file__).parent.parent / "playwright_extractor.py"
        try:
            result = subprocess.run(
                [sys.executable, str(script_path), nh_url],
                capture_output=True,
                text=True,
                timeout=60
            )
            stdout = result.stdout.strip()
            if "JSON_RESULT:" in stdout:
                json_line = stdout.split("JSON_RESULT:")[1].strip().split('\n')[0]
                data = json.loads(json_line)
                self._last_subtitles = data.get("subtitles", [])
                return data.get("url", "")
        except Exception as e:
            logger.error(f"Playwright extractor failed: {e}")
        return ""

    def download_hentaihaven_video(
        self,
        url: str,
        output_dir: Path,
        progress_hook: Callable,
        quality: str = "1080p",
        fixed_title: Optional[str] = None,
    ) -> bool:
        output_dir.mkdir(parents=True, exist_ok=True)

        if fixed_title:
            clean_title = "".join(c for c in fixed_title if c.isalnum() or c in " .-_()'")
            clean_title = re.sub(r'[<>:"/\\|?*]', '', clean_title).strip()
            if not clean_title: clean_title = "video"
        else:
            clean_title = url.strip("/").split("/")[-1]

        result_path = output_dir / f"{clean_title}.mp4"
        cover_path = output_dir / "cover.png"

        try:
            m3u8_url = self._extract_nhplayer_m3u8(url)
            if not m3u8_url:
                logger.error(f"Failed to find nhplayer m3u8 for {url}")
                return False

            if hasattr(self, "_last_subtitles") and self._last_subtitles:
                import requests
                for i, sub in enumerate(self._last_subtitles):
                    sub_url = sub.get("url") if isinstance(sub, dict) else sub
                    if not sub_url: continue
                    ext = ".vtt" if ".vtt" in sub_url.lower() else ".srt"
                    lang = sub.get("label", "en") if isinstance(sub, dict) else "en"
                    sub_dest = output_dir / f"{clean_title}.{lang}{ext}"
                    try:
                        r = requests.get(sub_url, headers=self.headers, timeout=10)
                        if r.status_code == 200:
                            sub_dest.write_bytes(r.content)
                    except Exception as e:
                        logger.error(f"Failed to fetch subtitle {sub_url}: {e}")

            self.headers.pop("Referer", None)
            
            success = self.download_video(
                url=url,
                output_dir=output_dir,
                progress_hook=progress_hook,
                raw_stream_url=m3u8_url,
                fixed_title=fixed_title,
                custom_thumbnail=None
            )
            
            if success and result_path.exists():
                pass
                
            return success

        except Exception as e:
            logger.error(f"HentaiHavenCo download failed for {url}: {e}")
            return False
