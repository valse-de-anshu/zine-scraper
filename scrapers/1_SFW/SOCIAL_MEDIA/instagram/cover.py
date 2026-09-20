import re
from bs4 import BeautifulSoup

def extract(soup: BeautifulSoup, url: str) -> str:
    """
    Extracts high-resolution cover URL for Pinterest boards/profiles.
    """
    # 1. Try Open Graph image (usually the profile pic or board cover)
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return og_image["content"]

    # 2. Try to find the large image in the page
    # Pins often have a large image
    img = soup.find("img", src=re.compile(r"i\.pinimg\.com/originals/"))
    if img:
        return img["src"]
    
    # 3. Fallback to 736x
    img = soup.find("img", src=re.compile(r"i\.pinimg\.com/736x/"))
    if img:
        return img["src"]

    return None
