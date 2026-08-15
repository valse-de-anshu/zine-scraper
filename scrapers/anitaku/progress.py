from rich.tree import Tree
from core.ui import console
from core.ui import format_video_ranges
from typing import Any

def render_completion_tree(title: str, folder: Any, metadata: dict, verified_ids: list, cover_exists: bool):
    def align_header(label: str, value: Any) -> str:
        return f"{label:<18} : {value}"
        
    display_title = title if title else "Unknown"
    display_loc = str(folder)
        
    root_tree = Tree(f"[title]◆ {display_title}[/title]")
    root_tree.add(align_header("❖ Location", f"[sexy_pink]{display_loc}[/sexy_pink]"))
    root_tree.add(align_header("Source", f"[info]{metadata.get('Source', 'Unknown')}[/info]"))
    root_tree.add(align_header("Total Videos", f"[info]{metadata.get('Total Videos', 0)}[/info]"))
    
    verified_count = len(verified_ids)
    root_tree.add(align_header("Existing", f"[success]{verified_count} videos[/success]"))
    
    cover_status = "[success]● Saved[/success]" if cover_exists else "[unselected]○ None[/unselected]"
    root_tree.add(align_header("Cover", cover_status))
    
    console.print(root_tree)
    console.print("")
