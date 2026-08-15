import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class UnifiedBaseScraper:
    """Shared Base Class for configuration-driven scrapers (e.g. Hanime, HentaiHaven)."""
    
    def __init__(self, url: str, config_path: Path):
        self.raw_url = url
        self.config_path = config_path
        self.config = self.load_config()
        self.url = self.normalize_url(url)
        self.scraper_type = "video"
        self.is_playlist = False

    def load_config(self) -> dict:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load site config {self.config_path}: {e}")
            return {}

    def normalize_url(self, url: str) -> str:
        """Converts alias domains to the primary domain."""
        primary = self.config.get("primary_domain")
        aliases = self.config.get("aliases", [])
        if not primary:
            return url
            
        parsed = urlparse(url)
        if parsed.netloc in aliases or any(a in parsed.netloc for a in aliases):
            new_netloc = primary
            return parsed._replace(netloc=new_netloc).geturl()
            
        return url

    def get_selector(self, key: str) -> str:
        return self.config.get("selectors", {}).get(key, "")

    def get_api_endpoint(self, key: str) -> str:
        return self.config.get("api", {}).get(key, "")

    def retry(self, func, retries=3, backoff=2):
        """Exponential backoff retry wrapper."""
        for attempt in range(retries):
            try:
                return func()
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed: {e}")
                if attempt == retries - 1:
                    raise
                time.sleep(backoff ** attempt)
