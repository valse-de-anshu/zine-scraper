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
            from core.cover_utils import save_verified_cover
            import requests
            r = requests.get(avatar_url, headers=self.headers, timeout=20)
            if r.status_code == 200 and len(r.content) > 500:
                saved = save_verified_cover(r.content, dest.parent, filename=dest.stem)
                return saved is not None
            return False
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
