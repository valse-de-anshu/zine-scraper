import requests
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from bs4 import BeautifulSoup
from core.base_scraper import UnifiedBaseScraper

class HentaiHavenCoScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        from .engine import HentaiHavenCoEngine
        self.engine = HentaiHavenCoEngine()
        self.is_playlist = True
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        self.title = "Unknown"
        self._folder_name = "Unknown"

    def get_link_type(self) -> str:
        return "model"

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        def fetch(url):
            res = self.session.get(url, timeout=15)
            res.raise_for_status()
            return res.text

        slug_match = re.search(r'/watch/([^/]+)', self.url)
        if not slug_match:
            slug_match = re.search(r'/series/([^/]+)', self.url)

        slug = slug_match.group(1) if slug_match else "unknown"

        ep_match = re.search(r'episode-(\d+)', slug)
        current_ep_num = int(ep_match.group(1)) if ep_match else None

        # Remove -episode-X to get series slug
        series_slug = re.sub(r'-episode-\d+.*', '', slug).strip('-')
        fallback_title = series_slug.replace('-', ' ').title()

        is_series_page = "/series/" in self.url

        try:
            current_html = self.retry(lambda: fetch(self.url))
            soup = BeautifulSoup(current_html, "html.parser")
        except Exception as e:
            logger.error(f"[HentaiHavenCo] Failed to fetch {self.url}: {e}")
            soup = BeautifulSoup("", "html.parser")

        # ── 1. Series Title ──────────────────────────────────────────────
        series_title = None
        if is_series_page:
            h1 = soup.find("h1")
            if h1:
                series_title = re.sub(r'^Series:\s*', '', h1.text.strip(), flags=re.I)
        else:
            mfs_title = soup.select_one(".more_from_series .mfs_title strong")
            if mfs_title and mfs_title.text.strip():
                series_title = mfs_title.text.strip()
            else:
                for item in soup.select(".info_bottom .r_item"):
                    span = item.find("span")
                    if span and "series" in span.text.lower():
                        sub_a = item.select_one(".sub_r a")
                        if sub_a and sub_a.text.strip():
                            series_title = sub_a.text.strip()
                            break

        if not series_title:
            series_title = fallback_title

        self.title = series_title
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()

        # ── 2. Series Cover Poster ───────────────────────────────────────
        cover_url = None
        cover_img = soup.select_one(".info_bottom .cover img, .cover img")
        if cover_img:
            cover_src = cover_img.get("data-src") or cover_img.get("src")
            if cover_src and not cover_src.startswith("data:"):
                cover_url = f"https://hentaihaven.co{cover_src}" if cover_src.startswith("/") else cover_src

        if not cover_url:
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                cover_url = og_img["content"]

        # ── 3. Episodes Discovery ────────────────────────────────────────
        ep_map = {}

        if is_series_page:
            for a in soup.select("a.a_item"):
                href = a.get("href", "")
                if "/watch/" in href:
                    full_href = f"https://hentaihaven.co{href}" if href.startswith("/") else href
                    ep_m = re.search(r'episode-(\d+)', href)
                    ep_no = int(ep_m.group(1)) if ep_m else 0
                    title_el = a.select_one(".video_title")
                    v_title = title_el.text.strip() if title_el else f"Episode {ep_no}"
                    img_el = a.select_one("img.lazy, img")
                    img_src = img_el.get("data-src") or img_el.get("src") if img_el else None
                    if img_src and not img_src.startswith("data:") and img_src.startswith("/"):
                        img_src = f"https://hentaihaven.co{img_src}"
                    ep_map[full_href] = {
                        "href": full_href,
                        "ep_num": ep_no,
                        "title": v_title,
                        "img": img_src,
                    }
        else:
            # Check more_from_series on watch page
            for item in soup.select(".more_from_series .mfs_item"):
                a_el = item.select_one(".title a") or item.select_one(".poster a")
                if not a_el or not a_el.get("href"):
                    continue
                href = a_el["href"]
                full_href = f"https://hentaihaven.co{href}" if href.startswith("/") else href
                ep_m = re.search(r'episode-(\d+)', href)
                ep_no = int(ep_m.group(1)) if ep_m else 0
                title_el = item.select_one(".title a")
                v_title = title_el.text.strip() if title_el else f"Episode {ep_no}"
                img_el = item.select_one(".poster img, img")
                img_src = img_el.get("data-src") or img_el.get("src") if img_el else None
                if img_src and not img_src.startswith("data:") and img_src.startswith("/"):
                    img_src = f"https://hentaihaven.co{img_src}"
                ep_map[full_href] = {
                    "href": full_href,
                    "ep_num": ep_no,
                    "title": v_title,
                    "img": img_src,
                }

            # If only 0 or 1 found, try catalog /series/{series_slug}/
            if len(ep_map) <= 1:
                series_page_url = f"https://hentaihaven.co/series/{series_slug}/"
                try:
                    s_html = fetch(series_page_url)
                    s_soup = BeautifulSoup(s_html, "html.parser")
                    for a in s_soup.select("a.a_item"):
                        href = a.get("href", "")
                        if "/watch/" in href:
                            full_href = f"https://hentaihaven.co{href}" if href.startswith("/") else href
                            ep_m = re.search(r'episode-(\d+)', href)
                            ep_no = int(ep_m.group(1)) if ep_m else 0
                            title_el = a.select_one(".video_title")
                            v_title = title_el.text.strip() if title_el else f"Episode {ep_no}"
                            img_el = a.select_one("img.lazy, img")
                            img_src = img_el.get("data-src") or img_el.get("src") if img_el else None
                            if img_src and not img_src.startswith("data:") and img_src.startswith("/"):
                                img_src = f"https://hentaihaven.co{img_src}"
                            ep_map[full_href] = {
                                "href": full_href,
                                "ep_num": ep_no,
                                "title": v_title,
                                "img": img_src,
                            }
                except Exception:
                    pass

        # Fallback if no episodes found
        if not ep_map:
            ep_no = current_ep_num or 1
            ep_map[self.url] = {
                "href": self.url,
                "ep_num": ep_no,
                "title": f"Episode {ep_no}",
                "img": cover_url,
            }

        ep_nodes = sorted(ep_map.values(), key=lambda x: x["ep_num"])

        # Fallback cover from first episode if still missing
        if not cover_url and ep_nodes and ep_nodes[0]["img"]:
            cover_url = ep_nodes[0]["img"]

        # ── 4. Metadata (Studio, Tags, Description) ──────────────────────
        studio = ""
        tags_list = []
        summary = ""

        for item in soup.select(".info_bottom .r_item"):
            span = item.find("span")
            if span and "brand" in span.text.lower():
                brand_a = item.select_one(".sub_r a")
                if brand_a:
                    studio = brand_a.text.strip()

        for a in soup.find_all("a", href=True):
            if "/tag/" in a["href"] or "/genre/" in a["href"] or "/studio/" in a["href"]:
                t = a.text.strip()
                if t and t not in tags_list:
                    tags_list.append(t)

        desc_el = soup.select_one(".description, .video_desc, .desc")
        if desc_el and desc_el.text.strip():
            summary = desc_el.text.strip()
        else:
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                summary = og_desc["content"]

        metadata = {
            "Channel/Series": series_title,
            "Source": "HentaiHavenCo",
            "Total Videos": len(ep_nodes),
            "ID": series_slug,
            "Thumbnail": cover_url,
            "Avatar URL": cover_url,
            "Studio": studio,
            "Tags": ", ".join(tags_list),
            "Description": summary,
            "URL": self.url,
        }

        videos = []
        for idx, node in enumerate(ep_nodes, 1):
            ep_num = node["ep_num"] or idx
            videos.append({
                "url": node["href"],
                "title": f"Episode {ep_num}",
                "id": str(ep_num),
                "uploader": "HentaiHavenCo",
                "thumbnail": node["img"] or cover_url,
                "upload_date": "",
            })

        return metadata, videos, {"title": series_title, "url": self.url}
