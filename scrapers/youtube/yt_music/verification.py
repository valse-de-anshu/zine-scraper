from pathlib import Path
from typing import List, Dict, Any, Set, Optional

def verify_videos(folder: Path, videos: List[Dict[str, Any]], ext_str: str = "flac", tracker: Optional[Any] = None, scraper_url: Optional[str] = None) -> Set[str]:
    """
    Verifies which YouTube Music tracks already exist in the folder with valid FLAC headers.
    """
    verified: Set[str] = set()
    folder = Path(folder)
    if not folder.exists():
        return verified

    flac_files = list(folder.glob("*.flac"))

    for v in videos:
        vid_id = str(v.get("id", ""))
        title = v.get("title", "")
        track_num = v.get("track_number")

        found = False
        for f in flac_files:
            # Match by track number prefix or title substring or id
            if vid_id and vid_id in f.stem:
                found = True
            elif title and title.lower() in f.stem.lower():
                found = True
            elif track_num is not None and f.stem.startswith(f"{track_num:02d}."):
                found = True

            if found:
                try:
                    if f.stat().st_size > 1024:
                        # Verify FLAC magic bytes fLaC
                        with open(f, "rb") as flac_in:
                            header = flac_in.read(4)
                            if header == b"fLaC":
                                verified.add(vid_id or title)
                                break
                except Exception:
                    pass

    return verified
