from typing import List, Dict, Any
from pathlib import Path
from core.history import HistoryLayer

def verify_videos(
    folder: Path,
    videos: List[Dict[str, Any]],
    ext: str,
    url: str,
    tracker: HistoryLayer,
    is_music: bool
) -> List[str]:
    """Perform local file verification and sync history for Idagio tracks."""
    history_ids = list(tracker.get_downloaded_items(url))
    verified_ids = []
    
    videos_dir = folder / ("music" if is_music else "videos")
    all_vid_ids = {str(v.get("id")) for v in videos if v.get("id")}
    
    for video in videos:
        vid_id = str(video.get("id"))
        if not vid_id:
            continue
        vid_title = video.get("title", "")
        clean_title = "".join([c for c in vid_title if c.isalnum() or c in " .-_()"]).strip()
        
        file_exists = False
        if videos_dir.exists():
            for f in videos_dir.glob(f"*{ext}"):
                if f"[{vid_id}]" in f.name:
                    file_exists = True
                    break
                elif clean_title and clean_title in f.name:
                    file_exists = True
                    break
                elif vid_title and vid_title in f.name:
                    file_exists = True
                    break
        
        if file_exists:
            verified_ids.append(vid_id)
            if vid_id not in history_ids:
                tracker.mark_downloaded(url, vid_id)
        else:
            if vid_id in history_ids:
                tracker.unmark_downloaded(url, vid_id)
                
    # Cleanup any old history IDs
    for vid_id in history_ids:
        if vid_id not in all_vid_ids:
            file_exists = False
            if videos_dir.exists():
                for f in videos_dir.glob(f"*{ext}"):
                    if f"[{vid_id}]" in f.name:
                        file_exists = True
                        break
            if not file_exists:
                tracker.unmark_downloaded(url, str(vid_id))
            else:
                verified_ids.append(vid_id)
                
    return verified_ids
