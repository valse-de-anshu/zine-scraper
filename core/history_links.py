import os
from pathlib import Path
from core.paths import PathAuthority

class URLHistoryManager:
    def __init__(self):
        paths = PathAuthority()
        self.history_file = paths.get_url_history_file()
        self.history = []
        self.reload()
        self.index = len(self.history)
        self.temp_input = ""

    def _is_valid_url(self, url: str) -> bool:
        if not url:
            return False
        val = url.strip().lower()
        return val.startswith("http://") or val.startswith("https://") or val.startswith("www.")

    def reload(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip()]
                seen = {}
                for line in lines:
                    if not self._is_valid_url(line):
                        continue
                    if line in seen:
                        del seen[line]
                    seen[line] = True
                self.history = list(seen.keys())
                if len(self.history) != len(lines):
                    with open(self.history_file, "w", encoding="utf-8") as f:
                        for line in self.history:
                            f.write(line + "\n")
            except Exception:
                self.history = []
        else:
            self.history = []
        self.index = len(self.history)

    def append(self, url: str):
        if not self._is_valid_url(url):
            return

        self.reload()

        if url in self.history:
            self.history.remove(url)

        self.history.append(url)

        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as f:
                for line in self.history:
                    f.write(line + "\n")
        except Exception:
            pass

        self.index = len(self.history)

    def get_up(self, current_text: str) -> str:
        if not self.history:
            return current_text
        if self.index == len(self.history):
            self.temp_input = current_text
        
        self.index = max(0, self.index - 1)
        return self.history[self.index]

    def get_down(self, current_text: str) -> str:
        if not self.history:
            return current_text
        if self.index >= len(self.history) - 1:
            self.index = len(self.history)
            return self.temp_input
        self.index = min(len(self.history), self.index + 1)
        return self.history[self.index]
