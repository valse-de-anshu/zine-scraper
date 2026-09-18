from rich.tree import Tree
from typing import Any, Dict
from pathlib import Path
from core.ui import format_video_ranges

def custom_align(label: str, value: Any) -> str:
    return f"{label:<30} : {value}"

def render_metadata_tree(
    title: str,
    folder: Path,
    metadata: Dict[str, Any],
    verified_ids: list,
    cover_path: Path
) -> Tree:
    """Construct and return the summary metadata Tree representation to the console."""
    display_title = title if title else "Unknown"
    display_loc = str(folder)
    root_tree = Tree(f"[title]◆ {display_title}[/title]")
    root_tree.add(custom_align("Location", f"[sexy_pink]{display_loc}[/sexy_pink]"))
    root_tree.add(custom_align("Source", f"[info]Idagio[/info]"))
    root_tree.add(custom_align("Total Song", f"[info]{metadata.get('Total Videos', 0)}[/info]"))
    root_tree.add(custom_align("Existing", f"[success]{format_video_ranges(verified_ids)}[/success]"))
    return root_tree
