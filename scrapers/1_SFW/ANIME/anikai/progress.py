from rich.tree import Tree
from core.ui import console
from typing import Any


def render_completion_tree(title: str, folder: Any, metadata: dict, verified_ids: list, cover_exists: bool):
    def align(label: str, value: Any) -> str:
        return f"{label:<18} : {value}"

    root = Tree(f"[title]◆ {title or 'Unknown'}[/title]")
    root.add(align("❖ Location", f"[sexy_pink]{folder}[/sexy_pink]"))
    root.add(align("Source",     f"[info]{metadata.get('Source', 'HiAnime')}[/info]"))
    root.add(align("Total Videos", f"[info]{metadata.get('Total Videos', 0)}[/info]"))
    root.add(align("Existing",   f"[success]{len(verified_ids)} videos[/success]"))

    cover_status = "[success]● Saved[/success]" if cover_exists else "[unselected]○ None[/unselected]"
    root.add(align("Cover", cover_status))

    console.print(root)
    console.print("")
