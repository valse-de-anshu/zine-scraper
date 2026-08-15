import importlib
import logging
from bs4 import BeautifulSoup

SITE_MAP = {
    "manhuaplus.org": "manhuaplus",
    "manhwaus.net": "manhwaus",
    "hentai18.net": "hentai18",
    "hentai20.io": "hentai20",
    "asurascans.com": "asurascans",
    "asuracomic.net": "asurascans",
    "asuratoon.com": "asurascans",
    "omegascans.org": "omegascans",
    "kunmanga.co.uk": "kunmanga",
    "fanfox.net": "fanfox",
    "mangafox.la": "fanfox",
    "nhentai.net": "nhentai",
    "weebcentral.com": "weebcentral",
    "mangak.io": "mangak",
    "idagio.com": "idagio",
    "pinterest.com": "pinterest",
}

def extract_cover_url(soup: BeautifulSoup, url: str) -> str:
    """
    Dynamically loads site-specific cover extraction logic.
    """
    url_lower = url.lower()
    site_folder = next((folder for domain, folder in SITE_MAP.items() if domain in url_lower), None)
    
    if site_folder:
        try:
            # Import the site-specific module
            module = importlib.import_module(f"scrapers.{site_folder}.cover")
            if hasattr(module, "extract"):
                return module.extract(soup, url)
        except ImportError:
            pass
        except Exception as e:
            logging.debug(f"Error in site-specific cover logic for {site_folder}: {e}")

    # Fallback to generic
    try:
        from .generic_cover import extract as generic_extract
        return generic_extract(soup, url)
    except Exception:
        return None
