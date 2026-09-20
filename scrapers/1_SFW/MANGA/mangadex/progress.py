from typing import Any, List, Optional
from rich.tree import Tree
from rich.markup import escape
from core.ui import console, format_chapter_ranges

def render_completion_tree(title: str, folder: Any, source: str, total_chapters: int, verified_nums: list, cover_exists: bool = None, language: Optional[str] = None):
    def align_header(label: str, value: Any) -> str:
        return f"{label:<18} : {value}"
        
    root_tree = Tree(f"[title]◆ {escape(title)}[/title]")

    folder_path = str(folder.resolve()) if hasattr(folder, "resolve") else str(folder)
    root_tree.add(align_header("Location", f"[info]{escape(folder_path)}[/info]"))
    root_tree.add(align_header("Source", f"[info]{source}[/info]"))
    if language:
        root_tree.add(align_header("Language", f"[site]{escape(language)}[/site]"))
    root_tree.add(align_header("Total Chapters", f"[info]{total_chapters}[/info]"))
    root_tree.add(align_header("Existing", f"[success]{format_chapter_ranges(verified_nums)}[/success]"))
    
    if cover_exists is None:
        cover_status = "[unselected]Skipped[/unselected]"
    else:
        cover_status = "[success]●[/success]" if cover_exists else "[error]●[/error]"
    root_tree.add(align_header("Cover", cover_status))
    
    console.print(root_tree)
    console.print(" ")
