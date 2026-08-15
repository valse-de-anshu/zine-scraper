import sys
import os
import select
import readline
from pathlib import Path
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.tree import Tree
from rich.table import Table
from rich.console import Group
from core.ui import console

class CategoryImportTUI:
    def __init__(self, categories_data, title="ZINE SCRAPER · Anime Import Wizard", quality_callback=None):
        self.categories = categories_data
        self.default_title = title
        self.quality_callback = quality_callback
        
        self.state = "TYPE_SELECTION"
        self.active_index = 0
        self.scroll_offset = 0
        self.visible_lines = 15
        
        # State memory to preserve Phase 1 cursor
        self.phase1_index = 0
        self.phase1_scroll = 0
        
        # State memory for Phase 2 cursor
        self.phase2_index = 0
        self.phase2_scroll = 0
        
        self.selected_category = None
        self.selected_folder_name = None
        self.qualities = []

    def _get_key(self):
        """Blocking key read with termios raw mode (preserves OPOST)."""
        if os.name == 'nt':
            import msvcrt
            ch = msvcrt.getch()
            if ch in (b'\x00', b'\xe0'):
                ch2 = msvcrt.getch()
                if ch2 == b'H': return 'UP'
                elif ch2 == b'P': return 'DOWN'
            if ch in (b'\r', b'\n'): return 'ENTER'
            if ch == b'\x1b': return 'ESC'
            return ''
        else:
            import tty, termios
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                mode = termios.tcgetattr(fd)
                mode[3] = mode[3] | termios.ISIG  # Allow Ctrl+C
                mode[1] = mode[1] | termios.OPOST # Preserve newlines
                termios.tcsetattr(fd, termios.TCSADRAIN, mode)
                
                select.select([fd], [], [])
                ch_bytes = os.read(fd, 1)
                if not ch_bytes: return ''
                ch = ch_bytes.decode('utf-8', errors='ignore')
                
                if ch == '\x1b':
                    r, _, _ = select.select([fd], [], [], 0.05)
                    if r:
                        ch2 = os.read(fd, 1).decode('utf-8', errors='ignore')
                        if ch2 in ('[', 'O'):
                            r2, _, _ = select.select([fd], [], [], 0.05)
                            if r2:
                                ch3 = os.read(fd, 1).decode('utf-8', errors='ignore')
                                if ch3 == 'A': return 'UP'
                                if ch3 == 'B': return 'DOWN'
                    return 'ESC'
                if ch in ('\r', '\n'): return 'ENTER'
                if ch == '\x03': return 'CTRL_C'
                return ch
            except Exception:
                return ''
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _wrap(self, text: str, width: int = 85) -> str:
        import textwrap
        lines = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
            else:
                lines.extend(textwrap.wrap(paragraph, width=width))
        return "\n".join(lines)

    def ask_custom(self, prompt_text: str) -> str:
        """Inline prompt for custom folder name."""
        console.show_cursor(True)
        console.print(f"\n[menu]{prompt_text}[/menu]")
        val = ""
        while True:
            # Re-draw line
            print(f"\r\033[K❯ {val}", end="", flush=True)
            
            k = self._get_key()
            if k == 'ESC':
                console.show_cursor(False)
                return ""
            elif k == 'ENTER':
                console.show_cursor(False)
                return val.strip()
            elif k == 'CTRL_C':
                console.show_cursor(False)
                return ""
            elif k in ('UP', 'DOWN', 'LEFT', 'RIGHT'):
                pass
            elif k == '\x7f' or k == '\x08': # Backspace
                val = val[:-1]
            elif len(k) == 1:
                val += k

    def render_left_panel(self) -> Group:
        lines = []
        if self.state == "TYPE_SELECTION":
            items = self.categories
            question = "What are you importing?"
        elif self.state == "FOLDER_SELECTION":
            items = self.selected_category["templates"]
            question = "Which folder should this use?"
        elif self.state == "LOADING_QUALITY":
            lines.append(Text("Probing stream qualities...", style="bold info"))
            lines.append(Text("Please wait..."))
            while len(lines) < 28:
                lines.append(Text(""))
            return Group(*lines)
        else:
            items = self.qualities
            question = "Select Resolution"

        lines.append(Text(question, style="bold white"))
        lines.append(Text(""))

        if self.active_index < self.scroll_offset:
            self.scroll_offset = self.active_index
        elif self.active_index >= self.scroll_offset + self.visible_lines:
            self.scroll_offset = self.active_index - self.visible_lines + 1

        total_items = len(items)
        for i in range(self.scroll_offset, min(total_items, self.scroll_offset + self.visible_lines)):
            item = items[i]
            display_name = item.get("display_name", item.get("label", "Unknown"))
            
            is_thumb = (i == self.active_index)
            scroll_char = "┃" if is_thumb else "│"
            
            if i == self.active_index:
                lines.append(Text(f" {scroll_char} > {display_name}", style="bold sexy_pink"))
            else:
                lines.append(Text(f" {scroll_char}   {display_name}", style="unselected"))
                
        # Pad left panel to strict fixed height of 28
        while len(lines) < 28:
            lines.append(Text(""))
            
        return Group(*lines)

    def render_right_panel(self) -> Group:
        lines = []
        if self.state == "TYPE_SELECTION":
            cat = self.categories[self.active_index]
            desc = self._wrap(cat.get("description", ""))
            examples = cat.get("examples", [])
            pop = self._wrap(cat.get("popularity", ""))
            tip = self._wrap(cat.get("tip", ""))
            folder_base = cat.get("storage_name", "Unknown")
            
            lines.append(Text(desc, style="white"))
            lines.append(Text(""))
            
            if tip:
                lines.append(Text(tip, style="info"))
                lines.append(Text(""))
                
            if examples:
                lines.append(Text("Examples", style="bold unselected"))
                for ex in examples:
                    lines.append(Text(f"• {ex}", style="white"))
                lines.append(Text(""))

            lines.append(Text("Common Structure", style="bold unselected"))
            tree = Tree(f"[unselected]Anime/[/unselected]", guide_style="unselected")
            tree.add(f"[unselected]{folder_base}/[/unselected]").add(f"[success][Anime Name]/[/success]")
            lines.append(tree)
            lines.append(Text(""))

            if pop:
                lines.append(Text("Popularity", style="bold unselected"))
                lines.append(Text(pop, style="warning"))

        elif self.state == "FOLDER_SELECTION":
            tmpl = self.selected_category["templates"][self.active_index]
            cat_name = self.selected_category["display_name"]
            folder_base = self.selected_category["storage_name"]
            folder_name = tmpl.get("storage_name", "<Custom Name>")
            
            info = self._wrap(tmpl.get("description", ""))
            tip = self._wrap(tmpl.get("tip", ""))
            examples = self.selected_category.get("examples", [])
            
            lines.append(Text("Selected Template", style="unselected"))
            lines.append(Text(tmpl["display_name"], style="bold white"))
            lines.append(Text("────────────────────────────", style="unselected"))
            
            if info:
                lines.append(Text(info, style="white"))
                lines.append(Text(""))
                
            if examples:
                lines.append(Text("Typical Usage", style="bold unselected"))
                for ex in examples:
                    lines.append(Text(f"• {ex}", style="white"))
                lines.append(Text(""))
            
            lines.append(Text("Folder Preview", style="bold unselected"))
            tree = Tree(f"[unselected]Zine/[/unselected]", guide_style="unselected")
            vacuum_node = tree.add(f"[unselected]Vacuum/[/unselected]")
            site_node = vacuum_node.add(f"[unselected]Website Name/[/unselected]")
            series_node = site_node.add(f"[unselected][Anime Name]/[/unselected]")
            base_node = series_node.add(f"[unselected]{folder_base}/[/unselected]")
            
            if tmpl.get("is_custom"):
                base_node.add(f"[sexy_pink]<Custom Name>/[/sexy_pink]")
            else:
                base_node.add(f"[success]{folder_name}/[/success]")
            lines.append(tree)
            lines.append(Text(""))
            
            if tip:
                lines.append(Text("Tip", style="bold unselected"))
                lines.append(Text(tip, style="info"))
                lines.append(Text(""))
                
            lines.append(Text("Related Release Type", style="bold unselected"))
            lines.append(Text(cat_name, style="white"))
            
        elif self.state == "LOADING_QUALITY":
            lines.append(Text("Waiting for network...", style="bold unselected"))
            
        elif self.state == "QUALITY_SELECTION":
            q = self.qualities[self.active_index]
            lines.append(Text("Selected Resolution", style="unselected"))
            lines.append(Text(q.get("label", "Auto"), style="bold white"))
            lines.append(Text("────────────────────────────", style="unselected"))
            lines.append(Text(""))
            if q.get("resolution"):
                lines.append(Text(f"Resolution: {q['resolution']}", style="info"))
            else:
                lines.append(Text("Resolution: Best available stream matching your choice.", style="info"))

        # Right panel padding calculation (Flawless due to pre-wrapping text)
        rendered_lines = 0
        for l in lines:
            if isinstance(l, Text):
                rendered_lines += len(l.plain.split("\n"))
            elif isinstance(l, Tree):
                if self.state == "TYPE_SELECTION":
                    rendered_lines += 3
                elif self.state == "FOLDER_SELECTION":
                    rendered_lines += 6
                
        # Pad right panel to strict fixed height of 28
        while rendered_lines < 28:
            lines.append(Text(""))
            rendered_lines += 1

        return Group(*lines)

    def render(self):
        # By setting the width explicitly on the Table, it mathematically locks the horizontal size.
        table = Table(show_header=False, show_edge=False, box=None, padding=(0, 4), width=135)
        table.add_column("Left", width=35, justify="left", vertical="top")
        table.add_column("Right", width=90, justify="left", vertical="top")
        table.add_row(self.render_left_panel(), self.render_right_panel())
        
        title = self.default_title if self.state == "TYPE_SELECTION" else f"ZINE SCRAPER · {self.selected_category['display_name']}"
        header = Text(title, style="bold menu", justify="left")
        footer = Text("↑↓ Navigate   Enter Select   Esc Back", style="unselected", justify="left")
        
        dashboard = Group(
            header,
            Text(""),
            table,
        )
        
        return Panel(
            dashboard,
            title="", 
            subtitle=footer,
            subtitle_align="left",
            border_style="unselected",
            padding=(1, 2),
            expand=False
        )

    def run(self) -> Path:
        """Run the TUI and return the final relative Path, or None if cancelled."""
        console.show_cursor(False)
        
        with Live(self.render(), console=console, screen=False, auto_refresh=False) as live:
            while True:
                live.update(self.render(), refresh=True)
                
                key = self._get_key()
                
                if self.state == "TYPE_SELECTION":
                    max_idx = len(self.categories) - 1
                    if key == 'UP' and self.active_index > 0:
                        self.active_index -= 1
                    elif key == 'DOWN' and self.active_index < max_idx:
                        self.active_index += 1
                    elif key == 'ENTER':
                        self.phase1_index = self.active_index
                        self.phase1_scroll = self.scroll_offset
                        self.selected_category = self.categories[self.active_index]
                        self.state = "FOLDER_SELECTION"
                        self.active_index = 0
                        self.scroll_offset = 0
                    elif key in ('ESC', 'CTRL_C'):
                        console.show_cursor(True)
                        return None
                        
                elif self.state == "FOLDER_SELECTION":
                    templates = self.selected_category["templates"]
                    max_idx = len(templates) - 1
                    if key == 'UP' and self.active_index > 0:
                        self.active_index -= 1
                    elif key == 'DOWN' and self.active_index < max_idx:
                        self.active_index += 1
                    elif key == 'ESC':
                        self.state = "TYPE_SELECTION"
                        self.active_index = self.phase1_index
                        self.scroll_offset = self.phase1_scroll
                    elif key == 'CTRL_C':
                        console.show_cursor(True)
                        return None
                    elif key == 'ENTER':
                        tmpl = templates[self.active_index]
                        folder_base = self.selected_category["storage_name"]
                        
                        if tmpl.get("is_custom"):
                            live.stop()
                            custom_name = self.ask_custom("Enter custom folder name:")
                            if not custom_name:
                                live.start()
                                continue
                            self.selected_folder_name = custom_name
                            live.start()
                        else:
                            self.selected_folder_name = tmpl["storage_name"]
                            
                        final_path = Path(folder_base) / self.selected_folder_name
                        
                        if self.quality_callback:
                            self.phase2_index = self.active_index
                            self.phase2_scroll = self.scroll_offset
                            self.state = "LOADING_QUALITY"
                            live.update(self.render(), refresh=True)
                            
                            self.qualities = self.quality_callback()
                            if self.qualities:
                                if len(self.qualities) == 1:
                                    console.show_cursor(True)
                                    return (final_path, None)
                                
                                # Append an "Auto" option
                                self.qualities.append({"label": "Best (auto)", "url": "auto"})
                                self.state = "QUALITY_SELECTION"
                                self.active_index = 0
                                self.scroll_offset = 0
                            else:
                                console.show_cursor(True)
                                return (final_path, None)
                        else:
                            console.show_cursor(True)
                            return final_path
                elif self.state == "QUALITY_SELECTION":
                    max_idx = len(self.qualities) - 1
                    if key == 'UP' and self.active_index > 0:
                        self.active_index -= 1
                    elif key == 'DOWN' and self.active_index < max_idx:
                        self.active_index += 1
                    elif key == 'ESC':
                        self.state = "FOLDER_SELECTION"
                        self.active_index = self.phase2_index
                        self.scroll_offset = self.phase2_scroll
                    elif key == 'CTRL_C':
                        console.show_cursor(True)
                        return (None, None)
                    elif key == 'ENTER':
                        chosen_q = self.qualities[self.active_index]
                        console.show_cursor(True)
                        folder_base = self.selected_category["storage_name"]
                        final_path = Path(folder_base) / self.selected_folder_name
                        
                        q_url = chosen_q.get("url")
                        if q_url == "auto": q_url = None
                        return (final_path, q_url)
