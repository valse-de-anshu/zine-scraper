import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class DomainManager:
    """Manages dynamic domain resolution and aliases across all scrapers."""
    
    def __init__(self, scrapers_dir: Path):
        self.scrapers_dir = scrapers_dir
        self.configs = {}
        self.site_map_additions = {}
        self.load_configs()
        
    def load_configs(self):
        """Discovers and loads all site_config.json files in scrapers subdirectories."""
        if not self.scrapers_dir.exists():
            return
            
        for config_path in self.scrapers_dir.glob("*/site_config.json"):
            scraper_folder = config_path.parent.name
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    
                self.configs[scraper_folder] = config
                
                # Register primary domain and all aliases
                domains = [config.get("primary_domain")] + config.get("aliases", [])
                for domain in domains:
                    if domain:
                        # Clean domain (remove http/www)
                        clean_domain = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
                        self.site_map_additions[clean_domain] = scraper_folder
                        
            except Exception as e:
                logger.error(f"Failed to load config {config_path}: {e}")
                
    def get_dynamic_site_map(self) -> dict:
        """Returns the dictionary mapping domain -> scraper folder for dynamically discovered sites."""
        return self.site_map_additions
        
    def get_config(self, scraper_folder: str) -> dict:
        """Returns the loaded config for a given scraper folder."""
        return self.configs.get(scraper_folder, {})
        
    def normalize_url(self, url: str, scraper_folder: str) -> str:
        """Converts an alias URL into the primary domain URL for consistency."""
        config = self.get_config(scraper_folder)
        if not config:
            return url
            
        primary = config.get("primary_domain")
        if not primary:
            return url
            
        # Find if it uses an alias
        aliases = config.get("aliases", [])
        for alias in aliases:
            if alias in url:
                return url.replace(alias, primary)
                
        return url
