from rich.tree import Tree
from core.ui import console

def render_completion_tree(title: str, folder: Any, pre_metadata: dict, verified_ids: list):
    def align_header(label: str, value: Any) -> str:
        return f"{label:<18} : {value}"
        
    display_title = title if title else "Unknown"
    display_loc = str(folder)
    root_tree = Tree(f"[title]◆ {display_title}[/title]")
    root_tree.add(align_header("❖ Location", f"[info]{display_loc}[/info]"))
    for k, v in pre_metadata.items():
        if k != "Title" and k != "Cover URL":
            root_tree.add(align_header(k, f"[info]{v}[/info]"))
    root_tree.add(align_header("Existing", f"[success]{len(verified_ids)} files[/success]"))
    
    import os
    if os.path.exists(folder / "cover.jpg"):
        root_tree.add(align_header("Cover", "[success]● Saved[/success]"))
    
    console.print(root_tree)
    console.print("")
