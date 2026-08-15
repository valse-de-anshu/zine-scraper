from urllib.parse import urljoin
from bs4 import BeautifulSoup
from core.generic_cover import extract as generic_extract

def extract(soup: BeautifulSoup, url: str) -> str:
    # ManhuaPlus: Usually img.full or meta og:image
    img = soup.select_one("img.full, .hero-background img, .post-thumb")
    if img:
        src = img.get("src") or img.get("data-src")
        if src: return urljoin(url, src)
    
    return generic_extract(soup, url)
