from urllib.parse import urljoin
from bs4 import BeautifulSoup
from core.generic_cover import extract as generic_extract

def extract(soup: BeautifulSoup, url: str) -> str:
    # Hentai18: Often in div.tit or thumbs path
    img = soup.select_one("img[src*='/images/thumbs/'], div.tit img")
    if img:
        return urljoin(url, img["src"])

    return generic_extract(soup, url)
