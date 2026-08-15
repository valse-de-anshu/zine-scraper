import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def clean_part_files(folder: Path, videos: list, tracker, scraper_url: str):
    import shutil
    
    # 1. Clean the central global temp folder (💩) unconditionally
    try:
        from core.paths import PathAuthority
        poop_dir = PathAuthority().get_app_root() / "💩"
    except Exception:
        poop_dir = Path(__file__).parent.parent / "💩"
        
    if poop_dir.exists():
        try:
            shutil.rmtree(poop_dir)
            logger.info("Butler swept the 💩 folder completely clean.")
        except Exception as e:
            logger.error(f"Butler failed to clean 💩 folder: {e}")
            
    # Ensure it exists for the upcoming run
    poop_dir.mkdir(parents=True, exist_ok=True)

    # 2. Clean only fragment/temp files in the target download folder
    if not folder.exists() or not folder.is_dir():
        return
        
    # SAFETY LOCK: Prevent wiping any data on the external SSD
    if "/mnt/maiden" in str(folder.resolve()):
        logger.warning(f"SAFETY LOCK: Refusing to run part_cleaner on external SSD {folder}")
        return

    candidate_files = []
    try:
        for f in folder.iterdir():
            if f.is_file():
                name_lower = f.name.lower()
                is_junk = False
                
                # Obvious temp/part files
                if any(name_lower.endswith(x) for x in ['.part', '.ytdl', '.aria2', '.tmp', '.meta.tmp']) or '-frag' in name_lower:
                    is_junk = True
                # yt-dlp format chunks
                elif re.search(r'\.f\d+(?:-[a-zA-Z0-9]+)?\.[a-zA-Z0-9]+$', name_lower) or re.search(r'\.f\d+(?:-[a-zA-Z0-9]+)?$', name_lower):
                    is_junk = True
                # yt-dlp batch files
                elif name_lower.endswith('_batch.txt'):
                    is_junk = True
                
                if is_junk:
                    candidate_files.append(f)
    except Exception as e:
        logger.error(f"Failed to scan directory for leftover files: {e}")
        return

    for cf in candidate_files:
        try:
            cf.unlink()
            logger.info(f"Cleaned temporary fragment file: {cf.name}")
            # If a fragment was found, we should ideally unmark it in the tracker,
            # but we don't have perfect mapping here without looping videos.
            # We will just clean the file to keep the disk tidy.
        except Exception as e:
            logger.error(f"Failed to delete temporary file {cf.name}: {e}")
