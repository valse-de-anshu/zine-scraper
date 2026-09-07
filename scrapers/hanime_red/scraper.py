import logging
import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Dict, Any, List, Tuple
from core.base_scraper import UnifiedBaseScraper
from .engine import HanimeRedEngine

logger = logging.getLogger(__name__)

class HanimeRedScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        self.engine = HanimeRedEngine()
        self.is_playlist = True
        self.title = "Unknown"
        self._folder_name = "Unknown"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        })

    def get_link_type(self) -> str:
        return "series"

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        # Check if URL is a /serie/ or /series/ catalog page vs episode page
        is_serie_url = bool(re.search(r'/serie(?:s)?/', self.url))

        # Slug extraction
        slug_match = re.search(r'/([^/]+)/?$', self.url)
        slug = slug_match.group(1) if slug_match else ""
        base_slug = slug
        if "-episode-" in slug:
            base_slug = slug.split("-episode-")[0]

        res = self.session.get(self.url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')

        series_title = ""
        cover_url = ""
        studio = ""
        summary = ""
        tags_str = ""
        html_date = ""
        ep_urls = []

        if is_serie_url:
            h1 = soup.find('h1')
            if h1 and h1.text.strip():
                series_title = h1.text.strip()
            else:
                title_tag = soup.find('title')
                if title_tag:
                    series_title = title_tag.text.split('-')[0].strip()
            if not series_title:
                series_title = base_slug.replace('-', ' ').title()

            # Find all episode links on this series page
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://hanime.red" + href
                if any(x in href for x in ["/serie/", "/series/", "/tags", "/login", "/register", "/hentai/", "/ai-hentai"]):
                    continue
                if href.rstrip("/") == "https://hanime.red":
                    continue
                # Match episode cards (contain img child, have episode keyword, or contain base slug)
                if a.find("img") or "episode" in href.lower() or (base_slug and f"/{base_slug}" in href):
                    if href not in ep_urls:
                        ep_urls.append(href)

            # Sort episodes naturally (Episode 1, Episode 2, ...)
            def extract_ep_num(u):
                m = re.search(r'-episode-(\d+)', u)
                return int(m.group(1)) if m else 999
            ep_urls.sort(key=extract_ep_num)

            # Cover from wp-post-image or og:image
            post_img = soup.find('img', class_='wp-post-image')
            if post_img and post_img.get('src'):
                cover_url = post_img['src']
            else:
                og_img = soup.find('meta', property='og:image')
                if og_img and og_img.get('content'):
                    cover_url = og_img['content']

            # Enrich series metadata by querying Episode 1 if episodes were found
            if ep_urls:
                try:
                    ep1_res = self.session.get(ep_urls[0], timeout=15)
                    ep1_soup = BeautifulSoup(ep1_res.text, 'html.parser')
                    for label in ep1_soup.find_all(string=lambda text: text and "Brand" in text and "Uploads" not in text):
                        if label.parent and label.parent.find_next_sibling():
                            studio = label.parent.find_next_sibling().text.strip()
                            break
                    for label in ep1_soup.find_all(string=lambda text: text and "Release Date" in text):
                        if label.parent and label.parent.find_next_sibling():
                            html_date = label.parent.find_next_sibling().text.strip()
                            break
                    for p in ep1_soup.find_all('p'):
                        text = p.text.strip()
                        if len(text) > 50:
                            summary = text
                            break
                    tag_links = ep1_soup.find_all('a', href=lambda h: h and '/tag/' in h.lower())
                    tags_list = [t.text.strip() for t in tag_links if t.text.strip()]
                    tags_str = ", ".join(dict.fromkeys(tags_list))
                    if not cover_url:
                        ep1_img = ep1_soup.find('img', class_='wp-post-image')
                        if ep1_img and ep1_img.get('src'):
                            cover_url = ep1_img['src']
                except Exception as e:
                    logger.debug(f"Failed to enrich metadata from episode 1: {e}")
        else:
            # Episode URL or standalone video page
            # Check if page links to a parent /serie/
            serie_a = soup.find("a", href=lambda h: h and "/serie/" in h)
            if serie_a:
                series_title = serie_a.text.strip()
                serie_href = serie_a["href"]
                try:
                    s_res = self.session.get(serie_href, timeout=15)
                    s_soup = BeautifulSoup(s_res.text, 'html.parser')
                    for a in s_soup.find_all("a", href=True):
                        href = a["href"]
                        if not href.startswith("http"):
                            href = "https://hanime.red" + href
                        if any(x in href for x in ["/serie/", "/series/", "/tags", "/login", "/register", "/hentai/", "/ai-hentai"]):
                            continue
                        if href.rstrip("/") == "https://hanime.red":
                            continue
                        if a.find("img") or "episode" in href.lower() or (base_slug and f"/{base_slug}" in href):
                            if href not in ep_urls:
                                ep_urls.append(href)
                except Exception as e:
                    logger.debug(f"Failed to fetch series page {serie_href}: {e}")

            h1 = soup.find('h1')
            ep_title = h1.text.strip() if h1 else ""

            if not series_title:
                series_title = re.sub(r'(?i)\s*-?\s*episode\s*\d+.*', '', ep_title).strip()
            if not series_title:
                series_title = base_slug.replace('-', ' ').title()

            # Ensure current episode is in ep_urls
            if self.url not in ep_urls:
                ep_urls.append(self.url)

            # Sort episodes naturally
            def extract_ep_num(u):
                m = re.search(r'-episode-(\d+)', u)
                return int(m.group(1)) if m else 999
            ep_urls.sort(key=extract_ep_num)

            # Extract metadata from current page
            for label in soup.find_all(string=lambda text: text and "Brand" in text and "Uploads" not in text):
                if label.parent and label.parent.find_next_sibling():
                    studio = label.parent.find_next_sibling().text.strip()
                    break
            for label in soup.find_all(string=lambda text: text and "Release Date" in text):
                if label.parent and label.parent.find_next_sibling():
                    html_date = label.parent.find_next_sibling().text.strip()
                    break
            for p in soup.find_all('p'):
                text = p.text.strip()
                if len(text) > 50:
                    summary = text
                    break
            tag_links = soup.find_all('a', href=lambda h: h and '/tag/' in h.lower())
            tags_list = [t.text.strip() for t in tag_links if t.text.strip()]
            tags_str = ", ".join(dict.fromkeys(tags_list))

            post_img = soup.find('img', class_='wp-post-image')
            if post_img and post_img.get('src'):
                cover_url = post_img['src']
            else:
                og_img = soup.find('meta', property='og:image')
                if og_img and og_img.get('content'):
                    cover_url = og_img['content']

        self.title = series_title
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()

        metadata = {
            "Channel/Series": series_title,
            "Source": "HanimeRed",
            "Total Videos": len(ep_urls),
            "ID": base_slug or slug or "unknown",
            "Thumbnail": cover_url,
            "Avatar URL": cover_url,
            "Studio": studio,
            "Tags": tags_str,
            "Description": summary,
            "URL": self.url
        }

        videos = []
        for idx, u in enumerate(ep_urls, 1):
            m = re.search(r'-episode-(\d+)', u)
            if m:
                ep_num = m.group(1)
                vid_title = f"Episode {ep_num}"
                vid_id = str(ep_num)
            else:
                vid_id = str(idx)
                vid_title = series_title if len(ep_urls) == 1 else f"Episode {idx}"

            videos.append({
                "url": u,
                "title": vid_title,
                "id": vid_id,
                "uploader": studio or "HanimeRed",
                "thumbnail": cover_url,
                "upload_date": html_date
            })

        info = {
            "title": series_title,
            "url": self.url,
            "id": base_slug or slug or "unknown",
            "uploader_id": studio or "HanimeRed",
            "upload_date": html_date,
            "thumbnail": cover_url
        }

        return metadata, videos, info
