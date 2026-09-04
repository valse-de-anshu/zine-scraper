"""
core/secrets.py
---------------
Dedicated secrets and credentials manager for Zine Scraper.
Safely resolves API keys, client tokens, and user credentials from:
  1. System Environment Variables (e.g. MANGADEX_CLIENT_ID, MANGADEX_CLIENT_SECRET)
  2. secrets.json (Root project directory, strictly gitignored)
  3. core/settings.json (Gitignored user settings fallback)

This guarantees user credentials are NEVER committed or leaked to Git repositories.
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)

DEFAULT_SECRETS_TEMPLATE: Dict[str, Any] = {
    "mangadex": {
        "client_id": "",
        "client_secret": ""
    }
}

def get_secrets_file_path() -> Path:
    from core.paths import PathAuthority
    return PathAuthority().get_secrets_file()

def load_secrets() -> Dict[str, Any]:
    """Loads secrets from secrets.json, returns dict."""
    p = get_secrets_file_path()
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Failed to load secrets from {p}: {e}")
        return {}

def save_secrets(data: Dict[str, Any]) -> bool:
    """Saves secrets to secrets.json."""
    p = get_secrets_file_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save secrets to {p}: {e}")
        return False

def ensure_secrets_file() -> Path:
    """Ensures secrets.json exists with the standard template. Safe to call anytime."""
    p = get_secrets_file_path()
    if not p.exists():
        try:
            save_secrets(DEFAULT_SECRETS_TEMPLATE)
        except Exception:
            pass
    return p

def get_secret(key_path: str, default: Any = None) -> Any:
    """
    Retrieves a secret value by key or dotted path.
    Checks in order:
      1. Environment variables (e.g. 'mangadex.client_id' -> 'MANGADEX_CLIENT_ID')
      2. secrets.json nested dict lookup
      3. core/settings.json fallback
    """
    # 1. Check environment variable
    env_key = key_path.replace(".", "_").upper()
    if env_key in os.environ and os.environ[env_key]:
        return os.environ[env_key]

    direct_env = key_path.replace(".", "_")
    if direct_env in os.environ and os.environ[direct_env]:
        return os.environ[direct_env]

    # 2. Check secrets.json
    secrets = load_secrets()
    if secrets:
        parts = key_path.split(".")
        current = secrets
        found = True
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                found = False
                break
        if found and current not in (None, ""):
            return current

    # 3. Fallback to settings.json
    try:
        from core.paths import PathAuthority
        settings_file = PathAuthority().get_config_file()
        if settings_file.exists():
            with open(settings_file, "r", encoding="utf-8") as f:
                settings_data = json.load(f)
                if isinstance(settings_data, dict):
                    parts = key_path.split(".")
                    curr = settings_data
                    for part in parts:
                        if isinstance(curr, dict) and part in curr:
                            curr = curr[part]
                        else:
                            curr = None
                            break
                    if curr not in (None, ""):
                        return curr
    except Exception:
        pass

    return default
