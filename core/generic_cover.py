from urllib.parse import urljoin
from bs4 import BeautifulSoup

def extract(soup: BeautifulSoup, url: str) -> str:
    """Generic fallback extraction logic."""
    # 1. OpenGraph
    og_image = soup.select_one('meta[property="og:image"]')
    if og_image and og_image.get("content"):
        return urljoin(url, og_image["content"])
            
    # 2. Twitter Image
    twitter_image = soup.select_one('meta[name="twitter:image"], meta[name="twitter:image:src"]')
    if twitter_image and twitter_image.get("content"):
        return urljoin(url, twitter_image["content"])

    # 3. Common CSS Patterns
    generic_selectors = [
        "div.summary_image img",
        ".post-thumbnail img",
        ".manga-poster img",
        ".book-cover img",
        ".cover img",
        ".series-cover img",
        "div.thumb img",
        ".img-item img",
        ".ts-post-image",
        ".img-cover img",
        ".media-cover img",
        ".anime-detail .film-poster img",
        ".novel-cover img",
        "img.img-responsive",
        "img.object-cover", # common in tailwind based sites (omegascans/weebcentral)
        ".thumb img"
    ]
    for sel in generic_selectors:
        img = soup.select_one(sel)
        if img:
            src = img.get("data-src") or img.get("src") or img.get("data-lazy-src") or img.get("srcset", "").split(" ")[0]
            if src and not src.startswith("data:image"): 
                return urljoin(url, src)
            
    return None
