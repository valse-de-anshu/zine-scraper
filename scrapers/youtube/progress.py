from rich.tree import Tree
from core.ui import align_header
from pathlib import Path
from typing import Dict, Any

def render_metadata_tree(title: str, sub_folder: Path, metadata: Dict[str, Any], verified_count: int, custom_thumb_path: Any, is_multi: bool, folder: Path) -> Tree:
    """Render the summary metadata Tree representation to the console."""
    display_title = title if title else "Unknown"
    root_tree = Tree(f"[title]◆ {display_title}[/title]")
    root_tree.add(align_header("Location", f"[info]{sub_folder.resolve()}[/info]"))
    root_tree.add(align_header("Source", f"[info]{metadata.get('Source', 'Unknown')}[/info]"))
    root_tree.add(align_header("Total Videos", f"[info]{metadata.get('Total Videos', 0)}[/info]"))
    root_tree.add(align_header("Existing", f"[success]{verified_count} videos[/success]"))

    if custom_thumb_path:
        root_tree.add(align_header("Cover", "[success]●[/success]"))
    elif is_multi:
        cover_path = folder / "cover.jpg"
        cover_status = "[success]●[/success]" if cover_path.exists() else "[unselected]○[/unselected]"
        root_tree.add(align_header("Channel Avatar", cover_status))
    return root_tree
