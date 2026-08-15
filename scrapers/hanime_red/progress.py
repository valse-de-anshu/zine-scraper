"""
scrapers/hanime_red/progress.py
-----------------------------
Progress tree rendering for HanimeRed vacuum and quick-grab sessions.
Mirrors youtube/progress.py aesthetic: minimalist, Tokyo Night styled.
"""

from rich.tree import Tree
from core.ui import align_header
from pathlib import Path
from typing import Dict, Any, Optional


def render_metadata_tree(
    title: str,
    sub_folder: Path,
    metadata: Dict[str, Any],
    verified_count: int,
    is_vacuum: bool,
    creator_root: Path,
) -> Tree:
    """
    Renders the summary metadata Tree shown before the download loop begins.

    Vacuum mode  → shows cover.png status, total video count, existing count
    Quick grab   → minimal tree, no cover/metadata info
    """
    display_title = title if title else "Unknown"
    root_tree = Tree(f"[title]◆ {display_title}[/title]")
    root_tree.add(align_header("Location", f"[info]{sub_folder.resolve()}[/info]"))
    root_tree.add(align_header("Source",   f"[info]{metadata.get('Source', 'HanimeRed')}[/info]"))
    root_tree.add(align_header("Total",    f"[info]{metadata.get('Total Videos', 0)} videos[/info]"))
    root_tree.add(align_header("Existing", f"[success]{verified_count} videos[/success]"))

    if is_vacuum:
        cover_path_jpg = creator_root / "cover.jpg"
        cover_path_png = creator_root / "cover.png"
        cover_status = "[success]●[/success]" if (cover_path_jpg.exists() or cover_path_png.exists()) else "[unselected]○[/unselected]"
        root_tree.add(align_header("Cover", cover_status))

    return root_tree
