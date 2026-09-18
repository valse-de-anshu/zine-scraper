import re
import logging
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

logger = logging.getLogger("AsuraScans")

class AsuraScansScraper(BaseScraper):
    scraper_type = "toon"

    def __init__(self, url: str):
        super().__init__(url)
        self.series_url = None

    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])


    def get_title_and_chapters(self):
        import json
        original_url = self.url
        is_chapter = self.is_chapter_link()

        # If it's a chapter link, resolve to series URL first so we get authentic metadata
        fetch_url = original_url
        if is_chapter:
            m_series = re.search(r"(https?://[^/]+/comics/[^/]+)", original_url)
            if m_series:
                self.series_url = m_series.group(1)
            else:
                try:
                    temp_soup = self.get_soup(original_url)
                    comic_a = temp_soup.select_one("a[href*='/comics/']")
                    if comic_a:
                        self.series_url = urljoin("https://asurascans.com", comic_a["href"].split("/chapter/")[0])
                except Exception:
                    pass
            if self.series_url:
                fetch_url = self.series_url

        soup = self.get_soup(fetch_url)

        # 1. Parse JSON-LD structured schema
        json_ld_data = {}
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string)
                if isinstance(data, dict):
                    if data.get("@type") == "ComicSeries":
                        json_ld_data = data
                        break
                    elif not json_ld_data and data.get("@type") == "Article":
                        json_ld_data = data
            except Exception:
                pass

        # 2. Extract and sanitize Title
        h1 = soup.select_one("h1.entry-title, h1")
        raw_title = h1.get_text(strip=True) if h1 else (json_ld_data.get("name") or json_ld_data.get("headline") or "")
        if not raw_title or raw_title.lower() == "unknown":
            og_meta = soup.find("meta", {"property": "og:title"})
            raw_title = og_meta.get("content") if og_meta else (soup.title.get_text(strip=True) if soup.title else "")

        # Clean mojibake and normalize unicode punctuation
        clean_title = raw_title.replace("â€”", "—").replace("â€“", "–").replace("Â ", " ").replace("Â", "").strip()
        clean_title = re.sub(r"(?i)\s*[-—–]\s*(read|online|raw|eng|free|manga|manhua|manhwa).*", "", clean_title)
        clean_title = re.sub(r"\s+", " ", clean_title).strip()

        if not clean_title or clean_title.lower() == "unknown":
            slug = self.url.rstrip("/").split("/")[-1]
            slug = re.sub(r"-[0-9a-fA-F]{6,}$", "", slug)
            clean_title = slug.replace("-", " ").title()

        self.title = clean_title

        # 3. Extract Alternative Titles
        alt_titles = ""
        alt_el = soup.select_one("#alt-titles, .alt-titles")
        if alt_el:
            alt_titles = alt_el.get_text(strip=True)
        if not alt_titles:
            alt_titles = json_ld_data.get("alternateName") or json_ld_data.get("alternativeHeadline") or ""
        self.alt_title = alt_titles.replace("Â", "").strip()

        # 4. Extract Full Description (avoid truncated "...")
        desc = ""
        desc_el = soup.select_one("#description-text")
        if desc_el:
            desc = desc_el.get_text(separator=" ", strip=True)
        if not desc or desc.endswith("..."):
            for sel in ["#syn-target", "div.description-summary", "div.summary-content", "div.post-content", "div.manga-excerpt", "p.summary"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(separator=" ", strip=True)
                    if len(t) > len(desc):
                        desc = t
        if not desc or desc.endswith("..."):
            ld_desc = json_ld_data.get("description", "")
            if len(ld_desc) > len(desc):
                desc = ld_desc
        if not desc:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                if "read manga" not in c.lower() and "fastest and highest" not in c.lower():
                    desc = c
        self.description = re.sub(r"\s+", " ", desc).replace("Â", "").strip()

        # 5. Extract Author & Artist
        author = ""
        artist = ""
        if json_ld_data.get("author"):
            a = json_ld_data["author"]
            author = a.get("name", "") if isinstance(a, dict) else str(a)
        if json_ld_data.get("illustrator"):
            ill = json_ld_data["illustrator"]
            artist = ill.get("name", "") if isinstance(ill, dict) else str(ill)

        # Fallback from DOM info grid
        for div in soup.find_all(["div", "span", "p"]):
            txt = div.get_text(separator=" ", strip=True)
            if "Author" in txt and not author:
                m = re.search(r"Author\s+([A-Za-z0-9._\-\s]+?)(?:\s+(?:Artist|Status|Type|Rating|Chapters|Bookmarks)|$)", txt)
                if m:
                    author = m.group(1).strip()
            if "Artist" in txt and not artist:
                m = re.search(r"Artist\s+([A-Za-z0-9._\-\s]+?)(?:\s+(?:Author|Status|Type|Rating|Chapters|Bookmarks)|$)", txt)
                if m:
                    artist = m.group(1).strip()

        self.author = author.strip()
        self.artist = artist.strip()

        # 6. Status & Type
        status = ""
        m_type = "Manhwa"
        for div in soup.find_all(["div", "span", "p"]):
            txt = div.get_text(separator=" ", strip=True)
            if "Status" in txt and not status:
                m = re.search(r"Status\s+([A-Za-z]+)", txt, re.IGNORECASE)
                if m:
                    status = m.group(1).capitalize()
            if "Type" in txt and (m_type == "Manhwa" or not m_type):
                m = re.search(r"Type\s+([A-Za-z]+)", txt, re.IGNORECASE)
                if m:
                    m_type = m.group(1).capitalize()
        self.status = status or "Ongoing"
        self.type = m_type or "Manhwa"

        # 7. Rating
        rating = ""
        if json_ld_data.get("aggregateRating"):
            rating = str(json_ld_data["aggregateRating"].get("ratingValue", ""))
        if not rating:
            m_r = re.search(r"([\d.]+)\s*Rating", soup.get_text(separator=" ", strip=True))
            if m_r:
                rating = m_r.group(1)
        self.rating = rating

        # 8. Genres / Tags
        genres = []
        if json_ld_data.get("genre"):
            g = json_ld_data["genre"]
            genres = g if isinstance(g, list) else [g]
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text(strip=True).title()
            if not text or len(text) > 40:
                continue
            bad_parent = False
            for p in a.parents:
                if p.name in ["nav", "aside", "header", "footer"] or p.get("id") in ["sidebar", "menu"] or "sidebar" in p.get("class", []):
                    bad_parent = True
                    break
            if bad_parent:
                continue
            if "genre" in href and text not in genres:
                genres.append(text)
            elif "tag" in href and text not in genres:
                genres.append(text)
        self.genres = genres
        self.tags = genres

        # 9. Cover Image URL (high-res from JSON-LD or DOM)
        cover_url = ""
        if json_ld_data.get("image"):
            img = json_ld_data["image"]
            cover_url = img.get("url", "") if isinstance(img, dict) else str(img)
        if not cover_url:
            cover_img = soup.select_one("img[src*='/asura-images/covers/']")
            if cover_img:
                cover_url = cover_img.get("src") or cover_img.get("data-src") or ""
        self.cover_url = cover_url

        # If original URL was a single chapter, return only that chapter
        if is_chapter:
            m = re.search(r"/chapter/([\d.]+)", original_url.lower())
            num = m.group(1) if m else "1"
            return clean_title, [(num, original_url)]

        chapters = []
        links = soup.find_all("a", href=True)
        for a in links:
            href = a["href"].lower()
            if "/chapter/" in href:
                m = re.search(r"/chapter/([\d.]+)", href)
                if m:
                    num_str = m.group(1)
                    full_url = urljoin("https://asurascans.com", a["href"])
                    chapters.append((float(num_str), num_str, full_url))

        if not chapters and not (hasattr(self, 'is_chapter_link') and self.is_chapter_link()):
            logger.warning(f"No chapters discovered for {self.url}. Structure might have changed.")

        seen_urls = set()
        seen_nums = set()
        final_chapters = []

        # Sort by number oldest to newest
        chapters.sort(key=lambda x: x[0])

        for float_num, str_num, link in chapters:
            if link not in seen_urls and str_num not in seen_nums:
                final_chapters.append((str_num, link))
                seen_urls.add(link)
                seen_nums.add(str_num)

        return clean_title, final_chapters

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        
        # Asura Scans often embeds images in a JSON object for Astro
        # or uses standard <img> tags.
        img_urls = []
        
        # Method 1: Look for images in the HTML
        imgs = soup.find_all("img")
        for img in imgs:
            src = (img.get("data-src") or img.get("src") or img.get("data-lazy-src") or "").strip()
            if src and "asura-images/chapters" in src and not src.startswith("data:"):
                clean_src = src.split('?')[0]
                full_src = urljoin(ch_url, clean_src)
                if full_src.startswith("http"):
                    img_urls.append(full_src)
        
        # Method 2: Extract from JSON structure if available (fallback)
        if not img_urls:
            # pages&quot;:[1,[[0,{&quot;url&quot;:[0,&quot;https://...&quot;]
            json_matches = re.findall(r'&quot;url&quot;:\[\d+,&quot;(https?://[^&]+)&quot;\]', str(soup))
            for match in json_matches:
                if "asura-images/chapters" in match:
                    cleaned_u = match.replace("\\/", "/")
                    if cleaned_u.startswith("http"):
                        img_urls.append(cleaned_u)

        img_urls = list(dict.fromkeys(img_urls))
        if not img_urls:
            logger.warning(f"No images found for ch {ch_num} at {ch_url}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
