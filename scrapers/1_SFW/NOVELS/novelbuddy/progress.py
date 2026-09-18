"""
scrapers/light_novel/novelbuddy/progress.py
-------------------------------------------
Rich progress tree for the NovelBuddy TUI.
"""

from rich.tree import Tree
from core.ui import console, format_chapter_ranges
from typing import Any, Optional


def render_completion_tree(title: str, folder: Any, source: str,
                           total_chapters: int, verified_nums: list,
                           cover_exists: Optional[bool] = None):
    def align_header(label: str, value: Any) -> str:
        return f"{label:<18} : {value}"

    root_tree = Tree(f"[title]◆ {title}[/title]")

    root_tree.add(align_header("Location", f"[info]{folder.resolve()}[/info]"))
    root_tree.add(align_header("Source", f"[info]{source}[/info]"))
    root_tree.add(align_header("Total Chapters", f"[info]{total_chapters}[/info]"))
    root_tree.add(align_header("Downloaded", f"[success]{format_chapter_ranges(verified_nums)}[/success]"))

    if cover_exists is None:
        cover_status = "[unselected]Skipped[/unselected]"
    else:
        cover_status = "[success]●[/success]" if cover_exists else "[error]●[/error]"
    root_tree.add(align_header("Cover", cover_status))

    console.print(root_tree)
    console.print(" ")
