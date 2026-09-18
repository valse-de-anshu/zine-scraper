import re
import json
from bs4 import BeautifulSoup

def extract(soup: BeautifulSoup, url: str) -> str:
    """
    Extracts high-resolution cover URL for Idagio albums/playlists.
    """
    # 1. Try Open Graph image
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return og_image["content"]

    # 2. Try to find the album image in the page structure
    # Idagio images often follow the pattern: idagio-images.global.ssl.fastly.net/albums/[ID]/main.jpg
    img = soup.find("img", src=re.compile(r"idagio-images.*\.jpg"))
    if img:
        return img["src"]

    # 3. Try to find JSON-LD
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                if data.get("@type") == "MusicAlbum" and data.get("image"):
                    return data["image"]
                # Sometimes it's a list
                if data.get("@type") == "ItemList" and "itemListElement" in data:
                    for item in data["itemListElement"]:
                        if item.get("image"):
                            return item["image"]
        except Exception:
            continue

    return None
