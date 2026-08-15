from typing import Any
from rich.tree import Tree
from core.ui import console
from core.ui import format_video_ranges

def render_completion_tree(title: str, folder: Any, metadata: dict, verified_ids: list, cover_exists: bool):
    def align_header(label: str, value: Any) -> str:
        return f"{label:<18} : {value}"
        
    display_title = title if title else "Unknown"
    display_loc = str(folder)
    root_tree = Tree(f"[title]◆ {display_title}[/title]")
    root_tree.add(align_header("❖ Location", f"[sexy_pink]{display_loc}[/sexy_pink]"))
    for k, v in metadata.items():
        if k not in ["Channel/Series", "ID"]:
            root_tree.add(align_header(k, f"[info]{v}[/info]"))
    root_tree.add(align_header("Existing", f"[success]{format_video_ranges(verified_ids)}[/success]"))
    

    console.print(root_tree)
    console.print("")
