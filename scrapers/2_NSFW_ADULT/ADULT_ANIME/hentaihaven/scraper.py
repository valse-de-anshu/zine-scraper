import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from bs4 import BeautifulSoup
from curl_cffi import requests
from core.base_scraper import UnifiedBaseScraper
from .engine import HentaiHavenEngine

logger = logging.getLogger(__name__)


class HentaiHavenScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        self.engine = HentaiHavenEngine()
        self.is_playlist = not bool(re.search(r"/episode-\d+", url))
        self.session = requests.Session(impersonate="chrome124")
        self.title = "Unknown"
        self._folder_name = "Unknown"

    def get_link_type(self) -> str:
        return "episode" if bool(re.search(r"/episode-\d+", self.url)) else "series"

    @staticmethod
    def _extract_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Parses and flattens all application/ld+json blocks."""
        results = []
        for s in soup.select('script[type="application/ld+json"]'):
            if s.string:
                try:
                    data = json.loads(s.string)
                    if isinstance(data, dict):
                        if "@graph" in data and isinstance(data["@graph"], list):
                            results.extend([x for x in data["@graph"] if isinstance(x, dict)])
                        else:
                            results.append(data)
                    elif isinstance(data, list):
                        results.extend([x for x in data if isinstance(x, dict)])
                except Exception:
                    pass
        return results

    @staticmethod
    def _extract_poster(soup: BeautifulSoup, json_ld_list: Optional[List[Dict[str, Any]]] = None) -> str:
        """Finds high-resolution poster image, stripping thumbnail prefixes."""
        # 1. Look for explicit img.hentaihaven.xxx image in HTML
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if "img.hentaihaven.xxx/images/" in src:
                # Strip thumbnail '/s_' prefix to obtain full-resolution cover
                full_res = re.sub(r"/s_([^/]+)$", r"/\1", src)
                if full_res.startswith("http"):
                    return full_res

        # 2. Look in JSON-LD objects
        if json_ld_list:
            for item in json_ld_list:
                item_type = item.get("@type")
                if item_type == "ImageObject":
                    cand = item.get("contentUrl") or item.get("url")
                    if cand and "img.hentaihaven.xxx" in cand:
                        return re.sub(r"/s_([^/]+)$", r"/\1", cand)
                    elif cand:
                        return cand
                elif item_type == "VideoObject":
                    thumbs = item.get("thumbnailUrl", [])
                    if thumbs:
                        cand = thumbs[0]
                        return re.sub(r"/s_([^/]+)$", r"/\1", cand)

        # 3. Look for coverlanyvd or himg images
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if any(h in src for h in ["himg.nl", "coverlanyvd.org"]):
                full_res = src.replace("s_poster.", "poster.").replace("s_thumbnail.", "thumbnail.")
                if full_res.startswith("http"):
                    return full_res

        # 4. Fallback to OpenGraph image
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]

        return ""

    @staticmethod
    def _extract_tags(soup: BeautifulSoup) -> List[str]:
        """Collects unique genre/category tags from series links."""
        tags = []
        for a in soup.select('a[href*="/series/"], a[href*="/genre/"], a[href*="/tag/"]'):
            href = a.get("href", "")
            if any(x in href.lower() for x in ["/login", "/register", "/search", "/page/"]):
                continue
            text = a.text.strip()
            if text and text.lower() not in [t.lower() for t in tags]:
                tags.append(text)
        return tags

    @staticmethod
    def _extract_studio(soup: BeautifulSoup) -> str:
        """Collects animation studio/brand from link."""
        for a in soup.select('a[href*="/studio/"], a[href*="/brand/"], a[href*="/producer/"]'):
            text = a.text.strip()
            if text:
                return text
        return ""

    @staticmethod
    def _extract_year(soup: BeautifulSoup, json_ld_list: Optional[List[Dict[str, Any]]] = None) -> str:
        """Collects release year from release links or JSON-LD."""
        for a in soup.select('a[href*="/release/"]'):
            text = a.text.strip()
            if re.match(r"^\d{4}$", text):
                return text
        if json_ld_list:
            for item in json_ld_list:
                date_str = item.get("datePublished") or item.get("uploadDate") or ""
                if date_str:
                    m = re.match(r"^(\d{4})", date_str)
                    if m:
                        return m.group(1)
        return ""

    @staticmethod
    def _extract_synopsis(soup: BeautifulSoup, json_ld_list: Optional[List[Dict[str, Any]]] = None) -> str:
        """Extracts work content synopsis."""
        for p in soup.find_all("p"):
            text = p.text.strip()
            if len(text) > 40 and not "premium destination" in text.lower() and not "all rights reserved" in text.lower():
                return text
        if json_ld_list:
            for item in json_ld_list:
                desc = item.get("description", "")
                if len(desc) > 30 and not "premium destination" in desc.lower():
                    return desc.strip()
        og = soup.find("meta", property="og:description")
        if og and og.get("content"):
            return og["content"].strip()
        return ""

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        def fetch(u: str) -> str:
            res = self.session.get(u, timeout=(10, 30))
            res.raise_for_status()
            return res.text

        html = self.retry(lambda: fetch(self.url))
        soup = BeautifulSoup(html, "html.parser")

        # Parse series_slug and ep_slug
        m = re.match(r"https?://([^/]+)/watch/([^/]+)(?:/([^/]+))?/?", self.url)
        domain = m.group(1) if m else "hentaihaven.xxx"
        series_slug = m.group(2) if m else self.url.strip("/").split("/")[-1]
        ep_slug = m.group(3) if m else None
        series_url = f"https://{domain}/watch/{series_slug}/"

        # If accessed via single episode, fetch series catalog page for complete franchise context
        series_soup = soup
        series_ld: List[Dict[str, Any]] = []
        if ep_slug:
            try:
                series_html = self.retry(lambda: fetch(series_url))
                series_soup = BeautifulSoup(series_html, "html.parser")
                series_ld = self._extract_json_ld(series_soup)
            except Exception as e:
                logger.warning(f"Could not fetch series catalog {series_url}: {e}")
                series_soup = soup

        curr_ld = self._extract_json_ld(soup)
        all_ld = curr_ld + series_ld

        # 1. Resolve Series Title
        series_title = ""
        for item in all_ld:
            if item.get("@type") == "BreadcrumbList":
                elements = item.get("itemListElement", [])
                if len(elements) >= 3 and not series_title:
                    cand = elements[2].get("name")
                    if cand and cand.lower() not in ["home", "hentai"]:
                        series_title = cand
            elif item.get("@type") == "WebPage" and not series_title and not ep_slug:
                series_title = item.get("name", "")

        if not series_title:
            h1 = series_soup.select_one("h1")
            if h1:
                series_title = h1.text.strip()
        if not series_title:
            series_title = series_slug.replace("-", " ").title()

        self.title = series_title
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()

        # 2. Rich Metadata fields
        cover_url = self._extract_poster(series_soup, all_ld)
        if not cover_url:
            cover_url = self._extract_poster(soup, curr_ld)

        studio = self._extract_studio(series_soup) or self._extract_studio(soup) or "Unknown"
        tags = self._extract_tags(series_soup) or self._extract_tags(soup)
        year = self._extract_year(series_soup, all_ld) or self._extract_year(soup, curr_ld)
        synopsis = self._extract_synopsis(series_soup, all_ld) or self._extract_synopsis(soup, curr_ld)

        # Release date extraction (ISO formatted)
        release_date = ""
        for item in all_ld:
            raw_d = item.get("datePublished") or item.get("uploadDate") or ""
            if raw_d:
                release_date = raw_d.split("T")[0]
                break
        if not release_date and year:
            release_date = f"{year}-01-01"

        # 3. Discover all episodes from franchise series page
        episodes_map: Dict[int, Dict[str, Any]] = {}
        for a in series_soup.find_all("a", href=True):
            href = a["href"]
            if f"/watch/{series_slug}" in href:
                full = f"https://{domain}" + href if href.startswith("/") else href
                full_norm = full.rstrip("/")
                if full_norm != series_url.rstrip("/"):
                    m_ep = re.search(r"/episode-(\d+)", full_norm)
                    num = int(m_ep.group(1)) if m_ep else 999
                    raw_text = a.get_text(separator=" ", strip=True)

                    ep_thumb = None
                    img_node = a.find("img")
                    if img_node:
                        ep_thumb_src = img_node.get("src") or img_node.get("data-src") or ""
                        if ep_thumb_src:
                            ep_thumb = ep_thumb_src.replace("s_thumbnail.", "thumbnail.").replace("s_poster.", "poster.")

                    if num not in episodes_map:
                        episodes_map[num] = {
                            "url": full_norm + "/",
                            "title": f"Episode {num}" if num != 999 else (raw_text or "Episode 1"),
                            "num": num,
                            "thumbnail": ep_thumb or cover_url,
                            "upload_date": release_date,
                        }

        # If current URL was an episode and not yet captured, add it
        if ep_slug:
            m_curr = re.search(r"episode-(\d+)", ep_slug)
            curr_num = int(m_curr.group(1)) if m_curr else 1
            if curr_num not in episodes_map:
                episodes_map[curr_num] = {
                    "url": self.url.rstrip("/") + "/",
                    "title": f"Episode {curr_num}",
                    "num": curr_num,
                    "thumbnail": cover_url,
                    "upload_date": release_date,
                }

        # Natural sort episodes: Episode 1, Episode 2, ...
        sorted_eps = sorted(episodes_map.values(), key=lambda x: x["num"])
        if not sorted_eps:
            sorted_eps = [{
                "url": self.url,
                "title": "Episode 1",
                "num": 1,
                "thumbnail": cover_url,
                "upload_date": release_date,
            }]

        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags or "")

        metadata = {
            "Channel/Series": series_title,
            "Alternative Title": "",
            "Source": "HentaiHaven",
            "Total Videos": len(sorted_eps),
            "ID": series_slug,
            "Thumbnail": cover_url,
            "Avatar URL": cover_url,
            "Cover URL": cover_url,
            "Studio": studio,
            "Release Date": release_date,
            "Year": year,
            "Tags": tags_str,
            "Description": synopsis,
            "Quality": "1080p",
            "URL": self.url,
        }

        videos = []
        for idx, ep in enumerate(sorted_eps, 1):
            ep_num = str(ep["num"]) if ep["num"] != 999 else str(idx)
            videos.append({
                "url": ep["url"],
                "title": ep.get("title") or f"Episode {ep_num}",
                "id": ep_num,
                "uploader": studio or "HentaiHaven",
                "thumbnail": ep.get("thumbnail") or cover_url,
                "upload_date": ep.get("upload_date") or release_date,
                "description": synopsis,
                "tags": tags,
                "quality": "1080p",
            })

        info = {
            "title": series_title,
            "alt_title": "",
            "url": self.url,
            "id": series_slug,
            "uploader_id": studio or "HentaiHaven",
            "upload_date": release_date,
            "thumbnail": cover_url,
        }

        return metadata, videos, info
