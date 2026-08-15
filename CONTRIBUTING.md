# Contributing to Zine Scraper Suite

Thank you for your interest in contributing to **Zine Scraper Suite**! 🎉

Whether you're fixing a bug, adding support for a new scraper platform, improving documentation, or optimizing the TUI performance, we welcome your contributions.

---

## 🏛️ Architectural Principles

Before writing code, please review our core architectural rules:

### 1. Absolute Site-Level Isolation
Every scraper platform lives under its own directory in `scrapers/<site>/` and must be **100% self-contained**:
```text
scrapers/<site>/
├── __init__.py
├── engine.py        # Extraction, API querying & download logic
├── scraper.py       # Scraper interface class
├── tui.py           # Site TUI entrypoint (handle_tui)
├── workflow.py      # Download loop, tree logging & verification
├── location.py      # Save path & collision resolution
├── verification.py  # Local file verification
└── progress.py      # Metadata tree formatting
```
* **Never import scrapers from one another.**
* **Do not leak scraper-specific logic back into the core monolithic engines.**

### 2. TTY & Batch Safety Guards
All interactive prompts (`Selector`, `MultiSelector`, `input()`, `theme_input`) must **always** be guarded by `sys.stdin.isatty()` and `is_batch` checks:
```python
import sys
if not is_batch and sys.stdin.isatty():
    choice = Selector(options, "Select Mode").select()
else:
    choice = "ALL"  # Headless / piped default
```

### 3. Tokyo Night Storm Palette & UI Themes
Map all terminal styling through Rich markup tags defined in the active theme:
* `[info]` : Cyan (`#7dcfff`)
* `[warning]` : Yellow (`#e0af68`)
* `[error]` : Bold Red (`#f7768e`)
* `[success]` : Bold Green (`#9ece6a`)
* `[site]` / `[sexy_pink]` : Lavender / Magenta (`#bb9af7`)
* `[unselected]` / `[tree.line]` : Dim Gray (`#565f89`)

### 4. Dependency Hygiene
When introducing a new Python package or system binary:
* Update `requirements.txt` with version constraints.
* Update `run me/install.sh` and `run me/install.bat` if introducing a system binary (`ffmpeg`, `deno`, etc.).

---

## 🛠️ Development Setup

1. **Fork and Clone**:
   ```bash
   git clone https://github.com/<your-username>/zine-scraper.git
   cd "zine scraper"
   ```

2. **Run the Automated Setup**:
   ```bash
   cd "run me"
   ./install.sh   # On Linux / macOS
   install.bat    # On Windows
   ```

3. **Create a Feature Branch**:
   ```bash
   git checkout -b feat/my-new-feature
   ```

---

## 🧪 Testing Your Changes

Before submitting a pull request:
1. Ensure your Python files compile cleanly:
   ```bash
   python -m py_compile core/*.py scrapers/**/*.py
   ```
2. Test interactive and batch modes for your changes:
   ```bash
   python orchestrator.py
   ```

---

## 📬 Submitting a Pull Request

1. **Commit your changes** with clear, descriptive commit messages (following Conventional Commits e.g. `feat(scrapers): add novelbin scraper`, `fix(core): resolve revolt shutdown`).
2. **Push your branch** to GitHub:
   ```bash
   git push origin feat/my-new-feature
   ```
3. **Open a Pull Request** against the `main` branch. Provide a brief description of your changes and steps to test them.

---

## 💬 Community & Support

Have questions or need help? Join our community Discord:
👉 **[https://discord.gg/suJD5xtFj](https://discord.gg/suJD5xtFj)**
