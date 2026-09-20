import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from core.base_scraper import UnifiedBaseScraper
from .engine import HanimeRedEngine

logger = logging.getLogger(__name__)

class HanimeRedScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        self.engine = HanimeRedEngine()
        self.is_playlist = bool(re.search(r'/serie(?:s)?/', url))
        self.title = "Unknown"
        self._folder_name = "Unknown"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def get_link_type(self) -> str:
        return "series" if bool(re.search(r'/serie(?:s)?/', self.url)) else "episode"

    @staticmethod
    def _extract_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Finds and parses all application/ld+json blocks in the page."""
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        results.append(data)
                    elif isinstance(data, list):
                        results.extend([x for x in data if isinstance(x, dict)])
                except Exception:
                    pass
        return results

    @staticmethod
    def _extract_poster(soup: BeautifulSoup) -> str:
        """Finds high quality poster webp image from page."""
        # 1. Look for explicit /media/posters/ img src
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "/media/posters/" in src:
                return src if src.startswith("http") else f"https://hanime.red{src}"

        # 2. Look for poster by aspect-[2/3] class
        for img in soup.find_all("img"):
            cls_list = img.get("class", [])
            if any("aspect-[2/3]" in c for c in cls_list):
                src = img.get("src", "")
                if src:
                    return src if src.startswith("http") else f"https://hanime.red{src}"

        # 3. Fallback to OpenGraph image (often backdrop)
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            return og_img["content"]

        return ""

    @staticmethod
    def _extract_tags(soup: BeautifulSoup, extra_genres: Optional[List[str]] = None) -> List[str]:
        """Collects genres from JSON-LD and HTML tag links without duplicates."""
        tags = []
        if extra_genres:
            for g in extra_genres:
                g_clean = str(g).strip()
                if g_clean and g_clean.lower() not in [t.lower() for t in tags]:
                    tags.append(g_clean)

        for a in soup.find_all("a", href=lambda h: h and "/tag/" in h.lower()):
            t_clean = a.text.strip()
            if t_clean and t_clean.lower() not in [t.lower() for t in tags]:
                tags.append(t_clean)

        return tags

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        is_serie_url = bool(re.search(r'/serie(?:s)?/', self.url))

        # Extract slug
        slug_match = re.search(r'/([^/]+)/?$', self.url)
        slug = slug_match.group(1) if slug_match else ""
        base_slug = slug.split("-episode-")[0] if "-episode-" in slug else slug

        res = self.session.get(self.url, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        ld_objects = self._extract_json_ld(soup)

        series_title = ""
        alt_title = ""
        cover_url = self._extract_poster(soup)
        studio = ""
        summary = ""
        tags: List[str] = []
        html_date = ""
        views = ""
        likes = ""
        ep_data_map: Dict[str, Dict[str, Any]] = {}

        def parse_video_ld(ld: Dict[str, Any], ep_soup: Optional[BeautifulSoup] = None):
            nonlocal series_title, alt_title, studio, summary, html_date, views, likes, tags, cover_url
            if not series_title:
                part_of = ld.get("partOfSeries", {})
                if isinstance(part_of, dict) and part_of.get("name"):
                    series_title = part_of.get("name", "").strip()

            alt_names = ld.get("alternateName", [])
            if alt_names and isinstance(alt_names, list) and not alt_title:
                alt_title = alt_names[0]

            if not studio:
                prod = ld.get("productionCompany", {})
                if isinstance(prod, dict) and prod.get("name"):
                    studio = prod.get("name", "").strip()

            if not summary:
                desc = ld.get("description", "").strip()
                if desc:
                    summary = desc

            if not html_date:
                raw_date = ld.get("uploadDate") or ld.get("datePublished") or ""
                if raw_date:
                    html_date = raw_date.split("T")[0]

            for stat in ld.get("interactionStatistic", []):
                if isinstance(stat, dict):
                    itype = stat.get("interactionType", {}).get("@type", "")
                    count = stat.get("userInteractionCount")
                    if itype == "WatchAction" and count is not None and not views:
                        views = f"{count:,}"
                    elif itype == "LikeAction" and count is not None and not likes:
                        likes = f"{count:,}"

            genre_list = ld.get("genre", [])
            if ep_soup:
                tags = self._extract_tags(ep_soup, genre_list)
            elif genre_list:
                for g in genre_list:
                    if g not in tags:
                        tags.append(g)

        if is_serie_url:
            coll_ld = next((x for x in ld_objects if x.get("@type") == "CollectionPage"), None)
            if coll_ld and coll_ld.get("name"):
                series_title = coll_ld.get("name", "").strip()
            elif soup.find("h1"):
                series_title = soup.find("h1").text.strip()
            else:
                title_tag = soup.find("title")
                if title_tag:
                    series_title = title_tag.text.split("—")[0].split("-")[0].strip()

            if not series_title:
                series_title = base_slug.replace("-", " ").title()

            # 1. Extract episode URLs from JSON-LD itemListElement
            if coll_ld:
                items = coll_ld.get("mainEntity", {}).get("itemListElement", [])
                for it in items:
                    ep_u = it.get("url", "")
                    if ep_u:
                        ep_data_map[ep_u] = {
                            "url": ep_u,
                            "title": it.get("name", ""),
                        }

            # 2. Extract any episode links from HTML directly
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("http"):
                    href = f"https://hanime.red{href}"
                if any(x in href for x in ["/serie/", "/series/", "/tags", "/login", "/register", "/hentai/", "/ai-hentai"]):
                    continue
                if href.rstrip("/") == "https://hanime.red":
                    continue
                if (base_slug and f"/{base_slug}" in href) or "-episode-" in href:
                    if href not in ep_data_map:
                        ep_data_map[href] = {
                            "url": href,
                            "title": a.text.strip(),
                        }

            # Enrich series metadata by querying Episode 1 (or first available)
            first_ep_url = next(iter(ep_data_map.keys()), None)
            if first_ep_url:
                try:
                    ep1_res = self.session.get(first_ep_url, timeout=15)
                    ep1_soup = BeautifulSoup(ep1_res.text, "html.parser")
                    ep1_lds = self._extract_json_ld(ep1_soup)
                    vid_ld = next((x for x in ep1_lds if x.get("@type") == "VideoObject"), None)
                    if vid_ld:
                        parse_video_ld(vid_ld, ep1_soup)
                    else:
                        tags = self._extract_tags(ep1_soup)

                    if not cover_url:
                        cover_url = self._extract_poster(ep1_soup)
                except Exception as e:
                    logger.debug(f"Failed to enrich metadata from first episode: {e}")

        else:
            # Episode URL
            vid_ld = next((x for x in ld_objects if x.get("@type") == "VideoObject"), None)
            serie_page_url = ""
            if vid_ld:
                parse_video_ld(vid_ld, soup)
                part_of = vid_ld.get("partOfSeries", {})
                if isinstance(part_of, dict) and part_of.get("url"):
                    serie_page_url = part_of.get("url")

            if not series_title:
                serie_a = soup.find("a", href=lambda h: h and "/serie/" in h)
                if serie_a:
                    series_title = serie_a.text.strip()
                    serie_page_url = serie_a["href"]
                    if not serie_page_url.startswith("http"):
                        serie_page_url = f"https://hanime.red{serie_page_url}"

            if not series_title:
                h1 = soup.find("h1")
                ep_title = h1.text.strip() if h1 else ""
                series_title = re.sub(r'(?i)\s*-?\s*episode\s*\d+.*', '', ep_title).strip()
            if not series_title:
                series_title = base_slug.replace("-", " ").title()

            # Ensure current episode is recorded
            ep_data_map[self.url] = {
                "url": self.url,
                "title": vid_ld.get("name", "") if vid_ld else series_title,
                "description": summary,
                "upload_date": html_date,
                "views": views,
                "likes": likes,
                "alt_title": alt_title,
            }

            # Discover sibling episodes in franchise if series page exists
            if serie_page_url:
                try:
                    s_res = self.session.get(serie_page_url, timeout=15)
                    s_soup = BeautifulSoup(s_res.text, "html.parser")
                    s_lds = self._extract_json_ld(s_soup)
                    s_coll = next((x for x in s_lds if x.get("@type") == "CollectionPage"), None)
                    if s_coll:
                        items = s_coll.get("mainEntity", {}).get("itemListElement", [])
                        for it in items:
                            u = it.get("url", "")
                            if u and u not in ep_data_map:
                                ep_data_map[u] = {
                                    "url": u,
                                    "title": it.get("name", ""),
                                }
                    if not cover_url:
                        cover_url = self._extract_poster(s_soup)
                except Exception as e:
                    logger.debug(f"Failed to query series page {serie_page_url}: {e}")

        # Natural sort episodes: Episode 1, Episode 3, Episode 4...
        def extract_ep_num(u):
            m = re.search(r'-episode-(\d+)', u)
            return int(m.group(1)) if m else 999

        sorted_ep_urls = sorted(ep_data_map.keys(), key=extract_ep_num)

        self.title = series_title
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()

        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags or "")

        metadata = {
            "Channel/Series": series_title,
            "Alternative Title": alt_title,
            "Source": "HanimeRed",
            "Total Videos": len(sorted_ep_urls),
            "ID": base_slug or slug or "unknown",
            "Thumbnail": cover_url,
            "Avatar URL": cover_url,
            "Cover URL": cover_url,
            "Studio": studio or "Unknown",
            "Release Date": html_date,
            "Views": views,
            "Likes": likes,
            "Tags": tags_str,
            "Description": summary,
            "URL": self.url,
        }

        videos = []
        for idx, u in enumerate(sorted_ep_urls, 1):
            m = re.search(r'-episode-(\d+)', u)
            ep_num = m.group(1) if m else str(idx)
            vid_title = f"Episode {ep_num}"
            ep_meta = ep_data_map.get(u, {})

            videos.append({
                "url": u,
                "title": vid_title,
                "id": str(ep_num),
                "uploader": studio or "HanimeRed",
                "thumbnail": cover_url,
                "upload_date": ep_meta.get("upload_date") or html_date,
                "description": ep_meta.get("description") or summary,
                "views": ep_meta.get("views") or views,
                "likes": ep_meta.get("likes") or likes,
                "alt_title": ep_meta.get("alt_title") or alt_title,
                "tags": tags,
            })

        info = {
            "title": series_title,
            "alt_title": alt_title,
            "url": self.url,
            "id": base_slug or slug or "unknown",
            "uploader_id": studio or "HanimeRed",
            "upload_date": html_date,
            "thumbnail": cover_url,
            "views": views,
            "likes": likes,
        }

        return metadata, videos, info
