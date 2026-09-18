from urllib.parse import urljoin
from bs4 import BeautifulSoup
from core.generic_cover import extract as generic_extract

def extract(soup: BeautifulSoup, url: str) -> str:
    # Asura Scans: Uses specific CDN path for covers
    img = soup.select_one("img[src*='/asura-images/covers/']")
    if img:
        return urljoin(url, img["src"])
    
    return generic_extract(soup, url)
