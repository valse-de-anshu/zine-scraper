# Theme logic and helper functions for Zine Scraper
from rich.style import Style
from theme.registry import THEMES

def apply_theme(console, theme_name: str):
    """Dynamically applies custom style properties to the active console theme."""
    styles = THEMES.get(theme_name, THEMES["tokyo-night-storm"])
    for name, style_str in styles.items():
        console._theme_stack._entries[-1][name] = Style.parse(style_str)

def get_theme_input_ansi(console) -> str:
    """Returns the ANSI escape sequence for the active console theme's 'selected' style color."""
    try:
        entry = console._theme_stack._entries[-1]
        style = entry.get("selected")
        if style and style.color:
            r, g, b = style.color.get_truecolor()
            return f"\033[38;2;{r};{g};{b}m"
    except Exception:
        pass
    return "\033[38;2;187;154;247m"
