import sys
import time
import os
import platform
from pathlib import Path
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from rich.live import Live
from core.ui import console, startup_clear, print_banner, Selector, clean_exit, get_banner_renderable

def detect_terminal() -> str:
    """Detects the terminal emulator program running the script."""
    term_program = os.environ.get("TERM_PROGRAM")
    term = os.environ.get("TERM", "")
    
    if "kitty" in term.lower() or term_program == "kitty":
        return "Kitty"
    if "alacritty" in term.lower() or os.environ.get("ALACRITTY_WINDOW_ID"):
        return "Alacritty"
    if "wezterm" in term.lower() or os.environ.get("WEZTERM_PANE"):
        return "WezTerm"
    if term_program == "Apple_Terminal":
        return "Apple Terminal"
    if term_program == "vscode":
        return "VS Code Terminal"
    if term_program == "iTerm.app":
        return "iTerm2"
    if "WT_SESSION" in os.environ:
        return "Windows Terminal"
    if "GNOME_TERMINAL_SCREEN" in os.environ:
        return "GNOME Terminal"
    if "KONSOLE_VERSION" in os.environ or "KONSOLE_PROFILE_NAME" in os.environ:
        return "Konsole"
    if term:
        return f"Generic Terminal ({term})"
    return "Unknown Terminal"

def render_setup_tree(os_display: str, term_display: str, library_path: str = None, theme_name: str = None, delay_val: str = None, active_step: int = 1, tick: int = 0):
    """Renders a beautiful, balanced, and symmetrical layout showing setup status and preferences."""
    from rich.table import Table
    from rich.text import Text
    from rich.align import Align
    from rich.console import Group

    # Steady indicator style for active configuring step
    active_ball_style = "warning"

    # Environment Grid
    env_grid = Table.grid(padding=(0, 1))
    env_grid.add_column("label", justify="right", width=14)
    env_grid.add_column("colon", justify="center", width=2)
    env_grid.add_column("ball", justify="center", width=2)
    env_grid.add_column("value", justify="left", width=22)

    env_grid.add_row(
        Text("OS", style="unselected"),
        Text(":", style="unselected"),
        Text("●", style="success"),
        Text(os_display, style="info")
    )
    env_grid.add_row(
        Text("Terminal", style="unselected"),
        Text(":", style="unselected"),
        Text("●", style="success"),
        Text(term_display, style="info")
    )

    # Funnel Grid
    funnel_grid = Table.grid(padding=(0, 1))
    funnel_grid.add_column("label", justify="right", width=14)
    funnel_grid.add_column("colon", justify="center", width=2)
    funnel_grid.add_column("ball", justify="center", width=2)
    funnel_grid.add_column("value", justify="left", width=22)

    # Library Root
    if library_path:
        lib_ball = Text("●", style="success")
        lib_val = Text(library_path, style="site")
    elif active_step == 1:
        lib_ball = Text("●", style=active_ball_style)
        lib_val = Text("Configuring...", style="selected")
    else:
        lib_ball = Text("○", style="unselected")
        lib_val = Text("Pending", style="unselected")
    funnel_grid.add_row(Text("Library Root", style="unselected"), Text(":", style="unselected"), lib_ball, lib_val)

    # Color Theme
    if theme_name:
        theme_ball = Text("●", style="success")
        theme_val = Text(theme_name, style="site")
    elif active_step == 2:
        theme_ball = Text("●", style=active_ball_style)
        theme_val = Text("Configuring...", style="selected")
    else:
        theme_ball = Text("○", style="unselected")
        theme_val = Text("Pending", style="unselected")
    funnel_grid.add_row(Text("Color Theme", style="unselected"), Text(":", style="unselected"), theme_ball, theme_val)

    # Chapter Delay
    if delay_val:
        delay_ball = Text("●", style="success")
        delay_val_text = Text(delay_val, style="site")
    elif active_step == 3:
        delay_ball = Text("●", style=active_ball_style)
        delay_val_text = Text("Configuring...", style="selected")
    else:
        delay_ball = Text("○", style="unselected")
        delay_val_text = Text("Pending", style="unselected")
    funnel_grid.add_row(Text("Chapter Delay", style="unselected"), Text(":", style="unselected"), delay_ball, delay_val_text)

    # Build the Group of elements
    parts = []
    
    parts.append(Align.center(Text("❖ System Environment ❖", style="menu bold")))
    parts.append(Align.center(env_grid))
    parts.append(Text(""))
    
    parts.append(Align.center(Text("❖ Configuration Funnel ❖", style="menu bold")))
    parts.append(Align.center(funnel_grid))

    # Palette Swatches if configuring theme
    if active_step == 2:
        parts.append(Text(""))
        parts.append(Align.center(Text("❖ Palette Swatches ❖", style="menu bold")))
        
        swatches_grid = Table.grid(padding=(0, 1))
        swatches_grid.add_column("label", justify="right", width=14)
        swatches_grid.add_column("colon", justify="center", width=2)
        swatches_grid.add_column("ball", justify="center", width=2)
        swatches_grid.add_column("value", justify="left", width=22)
        
        swatches = [
            ("Info / Success", "[info]Info[/info] / [success]Success[/success]"),
            ("Warn / Error", "[warning]Warning[/warning] / [error]Error[/error]"),
            ("Select / Unsel", "[selected]Selected[/selected] / [unselected]Unselected[/unselected]"),
            ("Count / Pink", "[count]Count[/count] / [sexy_pink]Pink Accent[/sexy_pink]")
        ]
        for label, val_markup in swatches:
            swatches_grid.add_row(
                Text(label, style="unselected"),
                Text(":", style="unselected"),
                Text("●", style="success"),
                Text.from_markup(val_markup)
            )
        parts.append(Align.center(swatches_grid))

    return Group(*parts)

def get_welcome_header_renderable():
    """Returns the dominance ASCII art tagline wrapped in a centred panel."""
    from rich.text import Text
    from rich.panel import Panel
    from rich.align import Align

    # Fixed column width — each side is this many chars
    COL = 28
    # Centre divider — trunk sits at char 28 of inner content

    def row(left: str, right: str, lstyle: str, rstyle: str) -> Text:
        """Build one text row: left padded to COL, right padded to COL."""
        t = Text()
        t.append(left.center(COL), style=lstyle)
        t.append(right.center(COL), style=rstyle)
        return t

    lines = []

    # Title
    title_t = Text()
    title_t.append("Z I N E   S C R A P E R".center(COL * 2), style="bold title")
    lines.append(title_t)

    # Trunk
    trunk_t = Text()
    trunk_t.append("│".center(COL * 2), style="menu")
    lines.append(trunk_t)

    # Branch line connecting trunk to the two side columns
    # The left column is centered at index 13, trunk at 27, right column at 41.
    branch_line = "┌" + "─" * 13 + "┼" + "─" * 13 + "┐"
    branch_t = Text()
    branch_t.append(branch_line.center(COL * 2), style="menu")
    lines.append(branch_t)

    # Leg rows  │  │
    leg_t = Text()
    leg_t.append("│".center(COL), style="menu")
    leg_t.append("│".center(COL), style="menu")
    lines.append(leg_t)

    # Arrow row  ▼  ▼
    arr1_t = Text()
    arr1_t.append("▼".center(COL), style="warning")
    arr1_t.append("▼".center(COL), style="sexy_pink")
    lines.append(arr1_t)

    lines.append(Text(""))

    # Tagline row 1
    lines.append(row('Built for the "what if it', "Not all heroes", "warning", "sexy_pink"))
    # Tagline row 2
    lines.append(row("gets deleted?” crowd.", "wear capes.", "warning", "sexy_pink"))

    lines.append(Text(""))

    # Second leg  │  │
    leg2_t = Text()
    leg2_t.append("│".center(COL), style="menu")
    leg2_t.append("│".center(COL), style="menu")
    lines.append(leg2_t)

    # Second arrow  ▼  ▼
    arr2_t = Text()
    arr2_t.append("▼".center(COL), style="success")
    arr2_t.append("▼".center(COL), style="info")
    lines.append(arr2_t)

    # Bottom taglines
    lines.append(row("Your paranoia was justified.", "Some just save files.", "success", "info"))

    from rich.console import Group
    return Panel(
        Group(*lines),
        border_style="menu",
        expand=False,
        width=COL * 2 + 4,
    )

def print_welcome_header():
    """Prints the dominance tagline to console."""
    console.print(get_welcome_header_renderable())

class TextInput(Selector):
    def __init__(self, title: str, instruction: str, default_value: str, os_display: str, term_display: str, active_step: int, display_library: str = None, theme_display_name: str = None, display_delay: str = None):
        super().__init__([], title)
        self.instruction = instruction
        self.default_value = default_value
        self.os_display = os_display
        self.term_display = term_display
        self.active_step = active_step
        self.display_library = display_library
        self.theme_display_name = theme_display_name
        self.display_delay = display_delay
        self.input_text = ""

    def select_fallback(self) -> str:
        startup_clear()
        print_banner()
        print_welcome_header()
        tree = render_setup_tree(self.os_display, self.term_display, self.display_library, self.theme_display_name, self.display_delay, self.active_step)
        tree_panel = Panel(tree, title="[title]❖ Setup Progress ❖[/title]", border_style="menu", width=60, expand=False)
        console.print(tree_panel)
        console.print("")
        console.print(f"[menu]{self.title}[/menu]")
        if self.instruction:
            console.print(self.instruction)
        console.print("[menu]❯ [/menu]", end="")
        sys.stdout.flush()
        val = input().strip()
        return val if val else self.default_value

    def get_input(self) -> str:
        global _LIVE_INSTANCE
        startup_clear()
        console.show_cursor(False)
        try:
            with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                import core.ui
                core.ui._LIVE_INSTANCE = live
                while True:
                    live.update(self._render(), refresh=True)
                    # non-blocking read: returns '' on timeout so blink refreshes
                    key = self._get_key_timeout(0.25)
                    if key == '':
                        continue          # just refresh the blink, no key pressed
                    if key in ('\r', '\n'):
                        return self.input_text.strip() if self.input_text.strip() else self.default_value
                    elif key in ('\x7f', '\x08'):
                        self.input_text = self.input_text[:-1]
                    elif key == '\x03':
                        clean_exit(forceful=True)
                    elif len(key) == 1 and key.isprintable():
                        self.input_text += key
        except Exception:
            return self.select_fallback()
        finally:
            import core.ui
            core.ui._LIVE_INSTANCE = None
            console.show_cursor(True)

    def _render(self) -> Table:
        table = Table.grid(padding=(0, 0))
        table.add_column("main", width=92)
        
        group_content = []
        group_content.append(get_banner_renderable())
        group_content.append(Text("\n"))
        # Welcome header omitted for clean layout
        
        import time
        tick = int(time.time() * 2) % 2
        tree = render_setup_tree(
            self.os_display,
            self.term_display,
            library_path=self.display_library,
            theme_name=self.theme_display_name,
            delay_val=self.display_delay,
            active_step=self.active_step,
            tick=tick
        )
        tree_panel = Panel(
            tree,
            title="[title]❖ Setup Progress ❖[/title]",
            border_style="menu",
            width=60,
            expand=False
        )
        group_content.append(tree_panel)
        group_content.append(Text("\n"))
        
        prompt_sec = Text()
        prompt_sec.append(f"{self.title}\n", style="menu")
        if self.instruction:
            prompt_sec.append(f"{self.instruction}\n", style="unselected")
            
        prompt_sec.append("❯ ", style="menu")
        prompt_sec.append(self.input_text, style="selected")
        
        group_content.append(prompt_sec)
        
        from rich.console import Group
        table.add_row(Group(*group_content))
        return table

class ThemeSelector(Selector):
    def __init__(self, options: list, title: str, os_display: str, term_display: str, library_display: str, curr_theme: str = None):
        self.section_1 = [
            ("Tokyo Night", "tokyo-night-storm"),
            ("Catppuccin", "catppuccin"),
            ("GitHub Dark", "github-dark"),
            ("Dracula", "dracula"),
            ("Nord", "nord"),
            ("One Dark", "one-dark"),
            ("Everforest", "everforest"),
            ("Gruvbox Dark", "gruvbox-dark"),
            ("Rose Pine", "rose-pine"),
            ("Night Owl", "night-owl"),
            ("Ayu Dark", "ayu-dark"),
            ("Monokai Pro", "monokai-pro"),
            ("Solarized Dark", "solarized-dark"),
            ("Horizon", "horizon"),
            ("Oxocarbon", "oxocarbon"),
            ("Synthwave 84", "synthwave-84"),
            ("Cyberpunk", "cyberpunk"),
            ("Neon Night", "neon-night"),
            ("Cobalt2", "cobalt2"),
            ("Kanagawa", "kanagawa"),
            ("Andromeda", "andromeda"),
            ("Palenight", "palenight"),
            ("Material Darker", "material-darker"),
            ("Shades of Purple", "shades-of-purple"),
            ("Deep Ocean", "deep-ocean"),
            ("Tokyo Night Dark", "tokyonight-night"),
            ("Catppuccin Macchiato", "catppuccin-macchiato"),
            ("Catppuccin Frappe", "catppuccin-frappe"),
            ("Rose Pine Moon", "rose-pine-moon"),
            ("Dracula Purple", "dracula-purple"),
            ("Moonlight", "moonlight"),
            ("Outrun Neon", "outrun-neon"),
            ("Laserwave", "laserwave"),
            ("Velvet Violet", "velvet-violet"),
            ("Electric Blue", "electric-blue"),
            ("Emerald Dark", "emerald-dark"),
            ("Crimson Dusk", "crimson-dusk"),
            ("Amber Gold", "amber-gold"),
            ("Copper Oxide", "copper-oxide"),
            ("Midnight Synth", "midnight-synth")
        ]
        self.section_2 = [
            ("Nordic Frost", "nordic-frost"),
            ("Jungle Dim", "jungle-dim"),
            ("Muted Lavender", "muted-lavender"),
            ("Dim Charcoal", "dim-charcoal"),
            ("Calm Ocean", "calm-ocean"),
            ("Earthy Moss", "earthy-moss"),
            ("Soft Sepia", "soft-sepia"),
            ("Dusk Rose", "dusk-rose"),
            ("Slate Storm", "slate-storm"),
            ("Night Sky", "night-sky"),
            ("Sage Mist", "sage-mist"),
            ("Soft Zen", "soft-zen"),
            ("Cozy Warmth", "cozy-warmth"),
            ("Twilight Fog", "twilight-fog"),
            ("Olive Branch", "olive-branch"),
            ("Autumn Forest", "autumn-forest"),
            ("Gentle Indigo", "gentle-indigo"),
            ("Whispering Teal", "whispering-teal"),
            ("Muted Plum", "muted-plum"),
            ("Sandstone Warm", "sandstone-warm"),
            ("Misty Pines", "misty-pines"),
            ("Quiet Ember", "quiet-ember"),
            ("Sea Breeze", "sea-breeze"),
            ("Rose Quartz", "rose-quartz"),
            ("Velvet Dusk", "velvet-dusk"),
            ("Silent Moon", "silent-moon"),
            ("Frosted Glass", "frosted-glass"),
            ("Pastel Midnight", "pastel-midnight"),
            ("Warm Hazelnut", "warm-hazelnut"),
            ("Dusty Amber", "dusty-amber"),
            ("Nordic Wood", "nordic-wood"),
            ("Mossy Stone", "mossy-stone"),
            ("Peaceful Horizon", "peaceful-horizon"),
            ("Soothing Emerald", "soothing-emerald"),
            ("Calm Cobalt", "calm-cobalt"),
            ("Mild Amethyst", "mild-amethyst"),
            ("Soft Clay", "soft-clay"),
            ("Deep Silence", "deep-silence"),
            ("Winter Hearth", "winter-hearth"),
            ("Soft Monochrome", "soft-monochrome")
        ]
        
        # If curr_theme is not explicitly passed, try to detect it from back_opt
        back_opt = next((opt for opt in options if "Back" in opt[0]), None)
        if back_opt and not curr_theme:
            curr_theme = back_opt[1]
            
        self.current_section = 1
        self.active_options = self.section_1
        
        # Initialize base Selector class first, then set self.index to avoid it being reset
        super().__init__(self.active_options, title, vertical=True, align_width=6)
        
        self.index = 0
        
        # Auto-focus the current theme if it is configured
        if curr_theme:
            found = False
            for idx, (label, val) in enumerate(self.section_2):
                if val == curr_theme:
                    self.current_section = 2
                    self.active_options = self.section_2
                    self.options = self.active_options
                    self.index = idx
                    found = True
                    break
            if not found:
                for idx, (label, val) in enumerate(self.section_1):
                    if val == curr_theme:
                        self.current_section = 1
                        self.active_options = self.section_1
                        self.options = self.active_options
                        self.index = idx
                        found = True
                        break
                        
        if back_opt:
            self.section_1.append(back_opt)
            self.section_2.append(back_opt)
                        
        self.os_display = os_display
        self.term_display = term_display
        self.library_display = library_display
        
        self.scroll_offset = 0
        self.page_size = 6  # Show 6 items at a time
        
        # Keep selected theme in view initially
        if self.index >= self.page_size:
            self.scroll_offset = self.index - self.page_size + 1

    def _clamp_scroll(self):
        max_offset = len(self.active_options) - self.page_size
        if max_offset < 0:
            max_offset = 0
        if self.scroll_offset < 0:
            self.scroll_offset = 0
        elif self.scroll_offset > max_offset:
            self.scroll_offset = max_offset

    def select_fallback(self) -> str:
        startup_clear()
        print_banner()
        print_welcome_header()
        
        all_options = self.section_1 + self.section_2
        console.print(f"[menu]{self.title}[/menu]")
        for i, (label, _) in enumerate(all_options, 1):
            console.print(f" {i}) {label}")
        while True:
            console.print(f"[menu]Enter choice (1-{len(all_options)}):[/menu]")
            console.print("[menu]❯ [/menu]", end="")
            sys.stdout.flush()
            try:
                val = input().strip()
                idx = int(val) - 1
                if 0 <= idx < len(all_options):
                    from core.ui import apply_theme
                    apply_theme(all_options[idx][1])
                    return all_options[idx][1]
            except Exception:
                pass
            console.print("[error]● Invalid selection. Please try again.[/error]")

    def select(self) -> str:
        global _LIVE_INSTANCE
        startup_clear()
        console.show_cursor(False)
        
        from core.ui import apply_theme
        apply_theme(self.active_options[self.index][1])
        
        try:
            with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                import core.ui
                core.ui._LIVE_INSTANCE = live
                live.update(self._render(), refresh=True)
                while True:
                    key = self._get_key()
                    if not key:
                        return self.select_fallback()
                    
                    if key in ('1', '2'):
                        new_sec = int(key)
                        if new_sec != self.current_section:
                            self.current_section = new_sec
                            self.active_options = self.section_2 if new_sec == 2 else self.section_1
                            self.options = self.active_options
                            self.index = 0
                            self.scroll_offset = 0
                            apply_theme(self.active_options[self.index][1])
                            live.update(self._render(), refresh=True)
                            
                    elif key == '[D' or key == '[A':  # Up
                        self.index = (self.index - 1) % len(self.active_options)
                        if self.index < self.scroll_offset:
                            self.scroll_offset = self.index
                        elif self.index >= self.scroll_offset + self.page_size:
                            self.scroll_offset = len(self.active_options) - self.page_size
                        self._clamp_scroll()
                        apply_theme(self.active_options[self.index][1])
                        live.update(self._render(), refresh=True)
                        
                    elif key == '[C' or key == '[B':  # Down
                        self.index = (self.index + 1) % len(self.active_options)
                        if self.index >= self.scroll_offset + self.page_size:
                            self.scroll_offset = self.index - self.page_size + 1
                        elif self.index < self.scroll_offset:
                            self.scroll_offset = 0
                        self._clamp_scroll()
                        apply_theme(self.active_options[self.index][1])
                        live.update(self._render(), refresh=True)
                        
                    elif key in ('\r', '\n'):
                        return self.active_options[self.index][1]
                    elif key == '\x03':
                        clean_exit(forceful=True)
        except Exception:
            return self.select_fallback()
        finally:
            import core.ui
            core.ui._LIVE_INSTANCE = None
            console.show_cursor(True)

    def _render(self) -> Table:
        table = Table.grid(padding=(0, 0))
        table.add_column("main", width=92)
        
        group_content = []
        
        group_content.append(get_banner_renderable())
        group_content.append(Text("\n"))
        
        # Welcome header omitted for clean layout
        
        split_table = Table.grid(padding=(0, 4))
        split_table.add_column("options", width=36)
        split_table.add_column("preview", width=52)
        
        left_text = Text()
        left_text.append(f"{self.title}\n\n", style="menu")
        
        left_text.append("Sections:\n", style="menu")
        if self.current_section == 1:
            left_text.append("  ● [1] Classic (Active)\n", style="bold success")
            left_text.append("  ○ [2] Soothing\n\n", style="unselected")
        else:
            left_text.append("  ○ [1] Classic\n", style="unselected")
            left_text.append("  ● [2] Soothing (Active)\n\n", style="bold success")
        
        if self.scroll_offset > 0:
            left_text.append("   ▲ ... more themes above ...\n", style="warning")
        else:
            left_text.append("\n")
            
        visible_options = self.active_options[self.scroll_offset : self.scroll_offset + self.page_size]
        for i_vis, (label, _) in enumerate(visible_options):
            idx = i_vis + self.scroll_offset
            is_selected = (idx == self.index)
            is_last = (i_vis == len(visible_options) - 1)
            newline = "\n" if not is_last else ""
            if is_selected:
                left_text.append(f" ❯ {label}{newline}", style="selected")
            else:
                left_text.append(f"   {label}{newline}", style="unselected")
                
        remaining = len(self.active_options) - (self.scroll_offset + self.page_size)
        if remaining > 0:
            left_text.append("\n   ▼ ... more themes below ...", style="warning")
        else:
            left_text.append("\n")
            
        tree_preview = render_setup_tree(
            self.os_display,
            self.term_display,
            library_path=self.library_display,
            theme_name=self.active_options[self.index][0],
            active_step=2
        )
        
        preview_panel = Panel(
            tree_preview,
            title="Theme Preview",
            border_style="menu",
            width=52,
            expand=False
        )
        
        split_table.add_row(left_text, preview_panel)
        group_content.append(split_table)
        
        from rich.console import Group
        table.add_row(Group(*group_content))
        return table


def check_all_requirements() -> dict:
    """
    Performs a deep audit of all system binaries, Python packages, and browser drivers.
    Returns audit status, list of critical/optional missing items, and detailed result rows.
    """
    import shutil
    import importlib.util

    results = []
    critical_missing = []
    optional_missing = []

    # 1. System Binaries
    has_ffmpeg = shutil.which("ffmpeg") is not None
    if has_ffmpeg:
        results.append({"name": "ffmpeg", "type": "System Binary", "status": "OK", "critical": True, "desc": "Audio/Video muxer & stream stitcher"})
    else:
        critical_missing.append("ffmpeg")
        results.append({"name": "ffmpeg", "type": "System Binary", "status": "MISSING", "critical": True, "desc": "Audio/Video muxer & stream stitcher"})

    has_deno = (shutil.which("deno") is not None) or (shutil.which("node") is not None)
    if has_deno:
        bin_name = "deno" if shutil.which("deno") else "node"
        results.append({"name": f"JS Engine ({bin_name})", "type": "System Binary", "status": "OK", "critical": False, "desc": "Javascript decrypter for protected streams"})
    else:
        optional_missing.append("deno")
        results.append({"name": "deno / node", "type": "System Binary", "status": "OPTIONAL", "critical": False, "desc": "Javascript decrypter for protected streams"})

    has_aria = shutil.which("aria2c") is not None
    if has_aria:
        results.append({"name": "aria2c", "type": "System Binary", "status": "OK", "critical": False, "desc": "Accelerated multi-connection downloader"})
    else:
        optional_missing.append("aria2c")
        results.append({"name": "aria2c", "type": "System Binary", "status": "OPTIONAL", "critical": False, "desc": "Accelerated multi-connection downloader"})

    # 2. Key Python Package Dependencies
    py_deps = [
        ("rich", "rich", True, "TUI presentation framework"),
        ("requests", "requests", True, "HTTP API network request engine"),
        ("bs4", "beautifulsoup4", True, "HTML DOM parser"),
        ("yt_dlp", "yt-dlp", True, "Universal media extractor"),
        ("m3u8", "m3u8", True, "HLS video stream playlist parser"),
        ("curl_cffi", "curl_cffi", True, "TLS/JA3 fingerprint bypass engine"),
        ("playwright", "playwright", True, "Browser automation engine"),
        ("PIL", "Pillow", True, "Thumbnail and cover image processor"),
        ("Crypto", "pycryptodome", True, "AES decryption module"),
        ("browser_cookie3", "browser-cookie3", False, "Browser cookie session importer"),
        ("aiohttp", "aiohttp", True, "Async HTTP downloader"),
    ]

    for mod_name, pkg_name, is_crit, desc in py_deps:
        spec = importlib.util.find_spec(mod_name)
        if spec is not None:
            results.append({"name": pkg_name, "type": "Python Package", "status": "OK", "critical": is_crit, "desc": desc})
        else:
            if is_crit:
                critical_missing.append(pkg_name)
                results.append({"name": pkg_name, "type": "Python Package", "status": "MISSING", "critical": True, "desc": desc})
            else:
                optional_missing.append(pkg_name)
                results.append({"name": pkg_name, "type": "Python Package", "status": "OPTIONAL", "critical": False, "desc": desc})

    # 3. Playwright Chromium Driver Check
    playwright_ok = False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exec_path = p.chromium.executable_path
            if exec_path and Path(exec_path).exists():
                playwright_ok = True
    except Exception:
        pass

    if playwright_ok:
        results.append({"name": "Playwright Chromium", "type": "Browser Driver", "status": "OK", "critical": True, "desc": "Chromium engine for browser scrapers"})
    else:
        critical_missing.append("Playwright Chromium Driver")
        results.append({"name": "Playwright Chromium", "type": "Browser Driver", "status": "MISSING", "critical": True, "desc": "Chromium engine for browser scrapers"})

    return {
        "satisfied": len(critical_missing) == 0,
        "critical_missing": critical_missing,
        "optional_missing": optional_missing,
        "results": results
    }

def verify_system_requirements(os_display: str):
    """
    Performs requirement audit and displays a rich table.
    If critical requirements are missing, presents OS-specific remediation commands
    and blocks setup execution until all critical requirements pass.
    """
    from rich.table import Table
    from rich.panel import Panel

    while True:
        reqs = check_all_requirements()

        table = Table(title="[bold white]❖ System Requirements & Dependencies Audit ❖[/bold white]",
                      box=None, padding=(0, 1), show_header=True, header_style="bold white")
        table.add_column("Component", style="white", width=22)
        table.add_column("Type", style="unselected", width=16)
        table.add_column("Status", width=12)
        table.add_column("Description", style="unselected", width=42)

        for item in reqs["results"]:
            st = item["status"]
            if st == "OK":
                status_text = Text("● OK", style="bold success")
            elif st == "MISSING":
                status_text = Text("✗ MISSING", style="bold error")
            else:
                status_text = Text("○ OPTIONAL", style="warning")

            table.add_row(item["name"], item["type"], status_text, item["desc"])

        console.print("")
        console.print(table)
        console.print("")

        if reqs["satisfied"]:
            console.print("[success]● All critical system requirements & dependencies are satisfied![/success]\n")
            time.sleep(1.0)
            break

        # Block setup and show remediation commands
        crit_list = ", ".join(reqs["critical_missing"])
        console.print(f"[error]● Scraper setup blocked: Critical requirement(s) missing ({crit_list})[/error]\n")

        remediation_text = Text()
        remediation_text.append("Action Required: ", style="bold warning")
        remediation_text.append("Please install the missing dependencies to continue.\n\n", style="white")

        if "Windows" in os_display:
            remediation_text.append("• Option A (Automated Setup Script):\n", style="bold info")
            remediation_text.append("  run me\\install.bat\n\n", style="bold success")
            remediation_text.append("• Option B (Manual Windows Terminal / PowerShell):\n", style="bold info")
            if "ffmpeg" in reqs["critical_missing"]:
                remediation_text.append("  winget install Gyan.FFmpeg DenoLand.Deno\n", style="info")
            remediation_text.append("  pip install -r requirements.txt\n", style="info")
            if "Playwright Chromium Driver" in reqs["critical_missing"]:
                remediation_text.append("  python -m playwright install chromium\n", style="info")
        elif "macOS" in os_display:
            remediation_text.append("• Option A (Automated Setup Script):\n", style="bold info")
            remediation_text.append("  ./run\\ me/install.sh\n\n", style="bold success")
            remediation_text.append("• Option B (Manual macOS Terminal via Homebrew):\n", style="bold info")
            if "ffmpeg" in reqs["critical_missing"]:
                remediation_text.append("  brew install ffmpeg deno\n", style="info")
            remediation_text.append("  pip install -r requirements.txt\n", style="info")
            if "Playwright Chromium Driver" in reqs["critical_missing"]:
                remediation_text.append("  python -m playwright install chromium\n", style="info")
        else:
            # Linux
            remediation_text.append("• Option A (Automated Setup Script):\n", style="bold info")
            remediation_text.append("  ./run\\ me/install.sh\n\n", style="bold success")
            remediation_text.append("• Option B (Manual Linux Terminal):\n", style="bold info")
            if "ffmpeg" in reqs["critical_missing"]:
                remediation_text.append("  Ubuntu/Debian : sudo apt install -y ffmpeg python3-venv curl\n", style="info")
                remediation_text.append("  Arch Linux    : sudo pacman -S ffmpeg deno\n", style="info")
                remediation_text.append("  Fedora/RHEL   : sudo dnf install ffmpeg deno\n", style="info")
            remediation_text.append("  pip install -r requirements.txt\n", style="info")
            if "Playwright Chromium Driver" in reqs["critical_missing"]:
                remediation_text.append("  python -m playwright install chromium\n", style="info")

        rem_panel = Panel(remediation_text, title="[error]System Setup Remediation Guide[/error]",
                          border_style="error", padding=(1, 2), expand=False, width=88)
        console.print(rem_panel)
        console.print("")

        opts = [
            ("Re-check Requirements", "RECHECK"),
            ("Quit Setup & Exit", "QUIT")
        ]
        choice = Selector(opts, "Requirements Action").select()
        if choice == "QUIT":
            clean_exit(forceful=True)
        elif choice == "RECHECK":
            startup_clear()
            print_banner()
            console.print("[info]◆ Re-auditing system requirements...[/info]")
            time.sleep(0.5)

def run_first_launch_setup(paths, storage, config):
    """First-launch setup to configure basic preferences interactively and playfully."""
    startup_clear()
    print_banner()
    
    # ── System Detection with blinking spinner ─────────────────────
    console.print("[menu]◆ Zine First-Launch Setup Guide[/menu]\n")

    def blink_line(label: str, duration: float = 0.9):
        """Show a blinking ● label for `duration` seconds then leave cursor."""
        import sys, time as _time
        from rich.live import Live
        from rich.text import Text as _Text
        deadline = _time.time() + duration
        with Live("", console=console, auto_refresh=False, transient=True) as live:
            while _time.time() < deadline:
                tick = int(_time.time() * 2) % 2
                t = _Text()
                t.append("● ", style="warning" if tick else "unselected")
                t.append(label, style="unselected")
                live.update(t, refresh=True)
                _time.sleep(0.12)

    blink_line("Detecting operating system...")

    os_name = platform.system()
    os_release = platform.release()

    if os_name == "Linux":
        try:
            os_display = f"Linux ({platform.freedesktop_os_release().get('NAME', 'Generic Linux')})"
        except Exception:
            os_display = "Linux"
    elif os_name == "Darwin":
        os_display = f"macOS ({os_release})"
    elif os_name == "Windows":
        os_display = f"Windows {os_release}"
    else:
        os_display = f"Unknown OS ({os_name})"

    console.print(f"[unselected]● Detecting operating system  :[/unselected] [success]{os_display}[/success]")

    blink_line("Detecting terminal...")
    term_display = detect_terminal()
    console.print(f"[unselected]● Terminal detected           :[/unselected] [success]{term_display}[/success]")
    time.sleep(0.3)

    blink_line("Checking path configurations...", 0.7)
    console.print("[unselected]● Checking path configurations :[/unselected] [success]OK![/success]")
    time.sleep(0.7)

    # Requirement check audit
    verify_system_requirements(os_display)

    # Formatter for paths shown in UI
    def get_display_path(path: Path) -> str:
        try:
            home = Path.home().resolve()
            resolved_path = Path(path).resolve()
            if resolved_path == home:
                return "%USERPROFILE%" if os_name == "Windows" else "~"
            rel = resolved_path.relative_to(home)
            if os_name == "Windows":
                return f"%USERPROFILE%\\{rel}"
            else:
                return f"~/{rel}"
        except (ValueError, Exception):
            pass
        return str(path)

    # OS-agnostic default path display — never expose a personal username
    default_root = paths.get_downloads_root()
    if os_name == "Windows":
        display_default = "%USERPROFILE%\\Downloads\\Zine"
    elif os_name == "Darwin":
        display_default = "~/Downloads/Zine"
    else:
        display_default = "~/Downloads/Zine"

    # 1. Library Root Path Setup
    while True:
        prompt = TextInput(
            title="Step 1: Enter Library Root Path",
            instruction=f"(Press Enter to use default: {display_default})",
            default_value=str(default_root),
            os_display=os_display,
            term_display=term_display,
            active_step=1
        )
        library_input = prompt.get_input()
        
        resolved = Path(library_input).expanduser().resolve()
        if resolved.name.lower() == "zine":
            resolved = resolved.parent / "Zine"
        else:
            resolved = resolved / "Zine"
        try:
            storage.create_directory(resolved)
            # Build the full Zine folder structure before continuing
            console.print("[info]● Scaffolding Zine library structure...[/info]")
            from core.library import scaffold_library
            scaffold_library(resolved, storage)
            console.print("[success]● Library structure created.[/success]")
            time.sleep(0.6)
            config.set("download_base", str(resolved))
            display_library = get_display_path(resolved)
            break
        except Exception as e:
            console.print(f"[error]● Invalid path or failed to create directory: {e}[/error]")
            time.sleep(2)

    # 2. Color Theme Selection
    theme_options = [
        ("Tokyo Night", "tokyo-night-storm"),
        ("Catppuccin", "catppuccin"),
        ("GitHub Dark", "github-dark"),
        ("Dracula", "dracula"),
        ("Nord", "nord"),
        ("One Dark", "one-dark"),
        ("Everforest", "everforest"),
        ("Gruvbox Dark", "gruvbox-dark"),
        ("Rose Pine", "rose-pine"),
        ("Night Owl", "night-owl"),
        ("Ayu Dark", "ayu-dark"),
        ("Monokai Pro", "monokai-pro"),
        ("Solarized Dark", "solarized-dark"),
        ("Horizon", "horizon"),
        ("Oxocarbon", "oxocarbon"),
        # Section 2: Soothing Dark Themes
        ("Nordic Frost", "nordic-frost"),
        ("Jungle Dim", "jungle-dim"),
        ("Muted Lavender", "muted-lavender"),
        ("Dim Charcoal", "dim-charcoal"),
        ("Calm Ocean", "calm-ocean"),
        ("Earthy Moss", "earthy-moss"),
        ("Soft Sepia", "soft-sepia"),
        ("Dusk Rose", "dusk-rose"),
        ("Slate Storm", "slate-storm"),
        ("Night Sky", "night-sky")
    ]
    new_theme = ThemeSelector(theme_options, "Step 2: Choose Color Theme", os_display, term_display, display_library).select()
    config.set("theme", new_theme)
    theme_display_name = next((opt[0] for opt in theme_options if opt[1] == new_theme), new_theme)

    # 3. Chapter Delay Configuration
    while True:
        prompt = TextInput(
            title="Step 3: Enter Chapter Download Delay in seconds",
            instruction="(Press Enter to use default: 1.0s)",
            default_value="1.0",
            os_display=os_display,
            term_display=term_display,
            active_step=3,
            display_library=display_library,
            theme_display_name=theme_display_name
        )
        delay_input = prompt.get_input()
        try:
            val = float(delay_input)
            if val < 0:
                raise ValueError("Delay cannot be negative")
            config.set("chapter_delay", val)
            display_delay = f"{val}s"
            break
        except ValueError as e:
            console.print(f"[error]● Invalid delay value: {e}[/error]")
            time.sleep(2)

    # Save first_launch = False to write settings.json permanently
    config.mark_launched()
    
    # ── Final Success Screen ──────────────────────────────────────────────
    startup_clear()
    
    success_tree = render_setup_tree(
        os_display, term_display, display_library, theme_display_name, display_delay, active_step=4
    )
    
    config_display_path = get_display_path(paths.get_config_file())
    
    success_text = Text()
    success_text.append("\n✔ ZINE SCRAPER INITIALIZED SUCCESSFULLY!\n\n", style="success")
    success_text.append("All preferences have been written to disk.\n", style="info")
    success_text.append(f"Settings Path: {config_display_path}\n", style="site")
    
    success_panel = Panel(
        success_tree,
        title="[success]❖ Initialization Complete ❖[/success]",
        border_style="success",
        expand=False,
        width=60,
        subtitle="[success]Press Enter to launch[/success]"
    )
    
    print_banner()
    print_welcome_header()
    console.print(success_panel)
    console.print(success_text)
    
    console.print("\n[success]Press Enter to launch Zine Scraper...[/success]")
    try:
        input()
    except (KeyboardInterrupt, SystemExit):
        clean_exit(forceful=True)
