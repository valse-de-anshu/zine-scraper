from pathlib import Path
from typing import Dict, Any, Optional
from rich.tree import Tree
from core.ui import align_header

def render_metadata_tree(
    title: str,
    folder: Path,
    metadata: Dict[str, Any],
    verified_count: int,
    custom_thumb_path: Optional[Path] = None,
    is_multi: bool = True
) -> Tree:
    """Render the summary metadata Tree representation to the console using YouTube styling."""
    display_title = title if title else "YouTube Music"
    root_tree = Tree(f"[title]◆ {display_title}[/title]")
    root_tree.add(align_header("Location", f"[info]{folder.resolve()}[/info]"))
    root_tree.add(align_header("Source", f"[info]{metadata.get('Source', 'YouTube Music')}[/info]"))
    root_tree.add(align_header("Total Tracks", f"[info]{metadata.get('Total Videos', 1)}[/info]"))
    root_tree.add(align_header("Existing", f"[success]{verified_count} tracks[/success]"))

    if custom_thumb_path:
        root_tree.add(align_header("Cover", "[success]●[/success]"))
    elif not is_multi:
        has_cover = bool(metadata.get("Thumbnail"))
        cover_status = "[success]●[/success]" if has_cover else "[unselected]○[/unselected]"
        root_tree.add(align_header("Cover", cover_status))
    else:
        cover_path = folder / "cover.jpg"
        cover_png = folder / "cover.png"
        cover_status = "[success]●[/success]" if (cover_path.exists() or cover_png.exists()) else "[unselected]○[/unselected]"
        root_tree.add(align_header("Album Art", cover_status))

    return root_tree
