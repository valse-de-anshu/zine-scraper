from bs4 import BeautifulSoup
from core.generic_cover import extract as generic_extract

def extract(soup: BeautifulSoup, url: str) -> str:
    return generic_extract(soup, url)
