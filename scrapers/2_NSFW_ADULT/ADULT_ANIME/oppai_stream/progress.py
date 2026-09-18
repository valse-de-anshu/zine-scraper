"""
scrapers/oppai_stream/progress.py
-----------------------------
Progress tree rendering for OppaiStream vacuum and quick-grab sessions.
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
    root_tree.add(align_header("Source",   f"[info]{metadata.get('Source', 'OppaiStream')}[/info]"))
    root_tree.add(align_header("Total",    f"[info]{metadata.get('Total Videos', 0)} videos[/info]"))
    root_tree.add(align_header("Existing", f"[success]{verified_count} videos[/success]"))

    if is_vacuum:
        has_cover = False
        if creator_root.exists():
            for ext in ["cover.jpg", "cover.png", "cover.webp"]:
                for p in creator_root.rglob(ext):
                    has_cover = True
                    break
        cover_status = "[success]●[/success]" if has_cover else "[unselected]○[/unselected]"
        root_tree.add(align_header("Cover", cover_status))

    return root_tree
