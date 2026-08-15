def _upgrade_fb_img_url(url: str) -> str:
    if not url:
        return url
    url = url.replace("&amp;", "&")
    url = re.sub(r"ctp=s\d+x\d+", "ctp=s960x960", url)
    url = re.sub(r"stp=c[^\&]+", "stp=dst-jpg", url)
    url = re.sub(r"p\d+x\d+/", "", url)
    return url


def extract(soup: BeautifulSoup, url: str) -> str:
    """
    Extracts high-resolution cover image URL for Facebook profiles/pages.
    """
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return _upgrade_fb_img_url(og_image["content"])

    og_img_sec = soup.find("meta", property="og:image:secure_url")
    if og_img_sec and og_img_sec.get("content"):
        return _upgrade_fb_img_url(og_img_sec["content"])

    return None
