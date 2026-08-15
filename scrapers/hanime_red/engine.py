from core.video_engine import VideoEngine
from pathlib import Path
from typing import Dict, Any, Optional

class HanimeRedEngine(VideoEngine):
    def __init__(self):
        super().__init__(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        })
    
    def download_hanime_red_video(self, url, output_dir, progress_hook, quality="1080p", fixed_title=None):
        # 1. First, attempt to intercept subtitles using playwright extractor
        import subprocess, sys, json, re
        from pathlib import Path
        try:
            extractor_script = Path(__file__).parent.parent / "playwright_extractor.py"
            python_path = sys.executable
            p = subprocess.run([python_path, str(extractor_script), url], capture_output=True, text=True, timeout=90)
            stdout = p.stdout.strip()
            if "JSON_RESULT:" in stdout:
                json_line = stdout.split("JSON_RESULT:")[1].strip().split('\n')[0]
                data = json.loads(json_line)
                subtitles = data.get("subtitles", [])
                
                if subtitles:
                    import requests
                    clean_title = "".join(c for c in (fixed_title or "video") if c.isalnum() or c in " .-_()'")
                    clean_title = re.sub(r'[<>:"/\\|?*]', '', clean_title).strip()
                    
                    for i, sub in enumerate(subtitles):
                        sub_url = sub.get("url") if isinstance(sub, dict) else sub
                        if not sub_url: continue
                        ext = ".vtt" if ".vtt" in sub_url.lower() else ".srt"
                        lang = sub.get("label", "en") if isinstance(sub, dict) else "en"
                        sub_dest = output_dir / f"{clean_title}.{lang}{ext}"
                        try:
                            r = requests.get(sub_url, headers=self.headers, timeout=10)
                            if r.status_code == 200:
                                sub_dest.write_bytes(r.content)
                        except Exception:
                            pass
        except Exception:
            pass

        # 2. Proceed with standard video download using yt-dlp
        return self.download_video(
            url=url,
            output_dir=output_dir,
            progress_hook=progress_hook,
            fixed_title=fixed_title
        )

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        if not avatar_url: return False
        try:
            import requests
            r = requests.get(avatar_url, headers=self.headers, timeout=20)
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

    def save_metadata(self, root_dir: Path, info: Dict[str, Any], source: str, model_name: str, avatar_url: Optional[str] = None, videos: Optional[list] = None, skip_cover: bool = False, custom_metadata: Optional[Dict[str, Any]] = None):
        import json
        zine_dir = root_dir / ".zine"
        zine_dir.mkdir(parents=True, exist_ok=True)
        meta_path = zine_dir / "metadata.json"

        url = info.get("url", "")
        if custom_metadata and "URL" in custom_metadata:
            url = custom_metadata["URL"]
            
        studio = custom_metadata.get("Studio", "") if custom_metadata else ""
        tags = custom_metadata.get("Tags", "") if custom_metadata else ""
        summary = custom_metadata.get("Description", "") if custom_metadata else ""

        meta = {
            "Series": model_name,
            "Source": source,
            "URL": url,
            "Total Videos": len(videos) if videos else 0,
            "Studio": studio,
            "Tags": tags,
            "Summary": summary,
            "videos": videos or []
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        if not skip_cover and avatar_url:
            cover_path = root_dir / "cover.jpg"
            if not cover_path.exists():
                self.download_avatar(avatar_url, cover_path)
