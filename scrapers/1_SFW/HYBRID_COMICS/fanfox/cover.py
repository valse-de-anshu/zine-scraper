from urllib.parse import urljoin
from bs4 import BeautifulSoup
from core.generic_cover import extract as generic_extract

def extract(soup: BeautifulSoup, url: str) -> str:
    # FanFox: Mobile site uses .detail-cover, desktop uses .detail-info-cover-img
    img = soup.select_one("img.detail-cover, img.detail-info-cover-img, img.detail-bg-img")
    if img:
        src = img.get("src")
        if src:
            if src.startswith("//"): src = "https:" + src
            return src
            
    return generic_extract(soup, url)
