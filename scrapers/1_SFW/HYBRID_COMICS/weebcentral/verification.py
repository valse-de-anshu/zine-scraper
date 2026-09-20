import os
from pathlib import Path
from typing import List, Tuple, Any

def verify_chapters(folder: Path, chapters: List[Tuple[str, str]], tracker: Any, url: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    verified_nums = []
    to_process = []
    
    for num, link in chapters:
        try:
            val = float(num)
            if val == int(val):
                c_num = f"{int(val):03d}"
            else:
                c_num = f"{int(val):03d}" + str(val - int(val))[1:]
        except Exception:
            c_num = str(num).zfill(3)
            
        chapter_path = folder / f"Chapter{num}"
        
        try:
            val = float(num)
            old_c_num = str(int(val)) if val == int(val) else str(val)
        except Exception:
            old_c_num = str(num)
        old_chapter_path = folder / f"ch{old_c_num}"
        if old_chapter_path.exists() and not chapter_path.exists():
            try:
                old_chapter_path.rename(chapter_path)
            except Exception:
                pass
                
        is_in_history = tracker.is_downloaded(url, num)
        
        temp_dir = chapter_path / f"_temp_{num}"
        if temp_dir.exists():
            import shutil
            try: shutil.rmtree(temp_dir)
            except Exception: pass
            if chapter_path.exists():
                try: shutil.rmtree(chapter_path)
                except Exception: pass

        has_files = chapter_path.exists() and (
            any(chapter_path.glob("*.png")) or 
            any(list(chapter_path.glob("*.jpg")) + list(chapter_path.glob("*.png")) + list(chapter_path.glob("*.webp")) + list(chapter_path.glob("*.avif"))) or 
            any(chapter_path.glob("*.jpeg"))
        )
        
        if is_in_history and not has_files:
            tracker.unmark_downloaded(url, num)
            is_in_history = False
            
        if is_in_history or has_files:
            if not is_in_history:
                tracker.mark_downloaded(url, num)
            verified_nums.append(num)
        else:
            to_process.append((num, link))
            
    return verified_nums, to_process
