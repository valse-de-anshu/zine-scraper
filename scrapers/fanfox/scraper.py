import re
import logging
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

logger = logging.getLogger("FanFox")

class FanFoxScraper(BaseScraper):
    def is_chapter_link(self) -> bool:
        return bool(re.search(r"/c[\d.]+/", self.url.lower())) or any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])

    def __init__(self, url):
        super().__init__(url)
        # Ensure we have the mature cookie for FanFox
        self.session.cookies.set("is_mature", "1", domain="fanfox.net", path="/")
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Mobile/15E148 Safari/604.1"
        })

    def get_title_and_chapters(self):
        # Extract info (will need soup)
        soup = getattr(self, "soup", None) or self.get_soup(self.url)
        self.description = ""
        for selector in [".fullcontent", ".detail-info-right-content", "#syn-target", "div.description-summary", "div.summary-content", "div.post-content", "div.manga-excerpt", "p.summary"]:
            el = soup.select_one(selector)
            if el:
                self.description = el.get_text(strip=True)
                break
        if not self.description:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                if "read manga" not in c.lower() and "fastest and highest" not in c.lower():
                    self.description = c
                    
        self.genres = []
        for a in soup.find_all("a", href=True):
            if "/directory/" in a["href"].lower():
                t = a.get_text(strip=True).title()
                if t and t != "Browse":
                    self.genres.append(t)
        
        self.author = ""
        author_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if "/authors/" in href or "/author/" in href or "/artist/" in href or "/artists/" in href:
                t = a.get_text(strip=True)
                if t and t.lower() not in ["author", "artist", "authors", "artists"]:
                    author_links.append(t)
        if author_links:
            self.author = ", ".join(list(dict.fromkeys(author_links)))
        # Convert mobile link to desktop to ensure all chapters are visible
        if "m.fanfox.net" in self.url:
            self.url = self.url.replace("m.fanfox.net", "fanfox.net")
        # 1. Detect if it's a chapter link
        if (bool(re.search(r"/c[\d.]+/", self.url)) or "/c/" in self.url) and ".html" in self.url:
            soup = self.get_soup(self.url)
            # Try to find the "Main Info" link to get the series page
            series_a = soup.select_one("div.reader-header-title a, a.reader-header-title-2")
            if series_a:
                title_text = series_a.get_text(strip=True)
                title = re.sub(r"[^\w\s-]", "", title_text).strip().title()
                
                # Extract chapter number
                m = re.search(r"/c([\d.]+)/", self.url)
                num_str = m.group(1) if m else "1"
                try:
                    val = float(num_str)
                    num_str = str(int(val)) if val.is_integer() else str(val)
                except ValueError:
                    pass
                
                # Convert to mobile roll view
                mobile_url = self.url.replace("fanfox.net", "m.fanfox.net").replace("/manga/", "/roll_manga/").replace("/1.html", "/")
                self.title = title
                return title, [(num_str, mobile_url)]
            
            # Fallback if no specific link found
            title_tag = soup.select_one(".reader-header-title")
            if title_tag:
                # If we only have the div, try to get just the first text node (the title)
                title_text = title_tag.contents[0].strip() if title_tag.contents else "Unknown"
                title = re.sub(r"[^\w\s-]", "", title_text).strip().title()
                
                m = re.search(r"/c([\d.]+)/", self.url)
                num_str = m.group(1) if m else "1"
                try:
                    val = float(num_str)
                    num_str = str(int(val)) if val.is_integer() else str(val)
                except ValueError:
                    pass
                mobile_url = self.url.replace("fanfox.net", "m.fanfox.net").replace("/manga/", "/roll_manga/").replace("/1.html", "/")
                self.title = title
                return title, [(num_str, mobile_url)]

        # 2. Default Series Page Logic
        soup = self.get_soup(self.url)
        title_tag = soup.select_one("span.detail-info-right-title-font")
        title = title_tag.get_text(strip=True) if title_tag else "Unknown"
        title = re.sub(r"[^\w\s-]", "", title).strip().title()
        
        chapters = []
        # FanFox list items
        items = soup.select("ul.detail-main-list li a")
        for a in items:
            href = a["href"]
            title_text = a.get("title", "").strip() or a.get_text(strip=True)
            
            # Extract chapter number from title or href
            # Pattern: Ch.001 or c001
            m = re.search(r"[Cc]h\.?\s*([\d.]+)", title_text)
            if not m:
                m = re.search(r"/c([\d.]+)/", href)
            
            if m:
                num_str = m.group(1)
                try:
                    val = float(num_str)
                    num_str = str(int(val)) if val.is_integer() else str(val)
                except ValueError:
                    pass
                # Convert to mobile roll view URL
                mobile_href = href.replace("/manga/", "/roll_manga/").replace("/1.html", "/")
                full_url = urljoin("https://m.fanfox.net", mobile_href)
                chapters.append((float(num_str), num_str, full_url))
        
        # Deduplicate and sort
        seen_urls = set()
        final_chapters = []
        chapters.sort(key=lambda x: x[0])
        
        for float_num, str_num, link in chapters:
            if link not in seen_urls:
                final_chapters.append((str_num, link))
                seen_urls.add(link)
                
        self.title = title
        return title, final_chapters

    def unpack_js(self, js_code):
        import re
        match = re.search(r"}\('(.*?)',(\d+),(\d+),'([^']+)'\.split\('\|'\)", js_code, re.DOTALL)
        if not match: return ""
        p, a, c, k = match.groups()
        a, c = int(a), int(c)
        k = k.split('|')
        def e(c_val):
            res = ''
            if c_val >= a:
                res = e(c_val // a)
            rem = c_val % a
            res += chr(rem + 29) if rem > 35 else (str(rem) if rem < 10 else chr(rem + 87))
            return res
        for i in range(c - 1, -1, -1):
            if k[i]:
                p = re.sub(r'\b' + e(i) + r'\b', k[i], p)
        return p

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        import re
        
        # In case it's a roll_manga url, try fetching the desktop version 1.html for the eval block
        fetch_url = ch_url
        if "/roll_manga/" in fetch_url:
            fetch_url = fetch_url.replace("/roll_manga/", "/manga/").rstrip("/") + "/1.html"
            fetch_url = fetch_url.replace("m.fanfox", "fanfox").replace("m.mangafox", "mangafox")
            
        soup = self.get_soup(fetch_url)
        html_str = str(soup)
        
        img_urls = []
        
        def extract_urls(unpacked_js):
            res = []
            pix_m = re.search(r'var\s+pix\s*=\s*[\"\']([^\"\']+)[\"\']', unpacked_js)
            pval_m = re.search(r'var\s+pvalue\s*=\s*\[(.*?)\]', unpacked_js, re.DOTALL)
            if pix_m and pval_m:
                pix = pix_m.group(1)
                paths = re.findall(r'[\"\']([^\"\']+)[\"\']', pval_m.group(1))
                for path in paths:
                    u = path if path.startswith("//") else pix + path
                    if u.startswith("//"): u = "https:" + u
                    res.append(u)
            else:
                urls = re.findall(r'\"(//[^\"]+\.(?:jpg|png|webp)[^\"]*)\"', unpacked_js) or \
                       re.findall(r'\'(//[^\']+\.(?:jpg|png|webp)[^\']*)\'', unpacked_js)
                for u in urls:
                    if u.startswith("//"): u = "https:" + u
                    res.append(u)
            return res
        
        # 1. Try unpacking JS eval block
        eval_match = re.search(r'eval\(function\(p,a,c,k,e,d.*?.split\(\'\|\'\).*?\)\)', html_str, re.DOTALL)
        if eval_match:
            try:
                unpacked = self.unpack_js(eval_match.group(0))
                img_urls.extend(extract_urls(unpacked))
            except Exception as e:
                logger.error(f"Failed to unpack JS: {e}")
                
        # 2. Try fetching from chapterfun.ashx if chapterid exists
        if not img_urls:
            m_cid = re.search(r'chapterid\s*=\s*(\d+)', html_str, re.IGNORECASE)
            if m_cid:
                cid = m_cid.group(1)
                base = fetch_url.split("/manga/")[0]
                ashx_url = f"{base}/chapterfun.ashx?cid={cid}&page=1"
                try:
                    resp = self.session.get(ashx_url)
                    eval_match2 = re.search(r'eval\(function\(p,a,c,k,e,d.*?.split\(\'\|\'\).*?\)\)', resp.text, re.DOTALL)
                    if eval_match2:
                        unpacked2 = self.unpack_js(eval_match2.group(0))
                        img_urls.extend(extract_urls(unpacked2))
                except Exception:
                    pass

        # 3. Fallback to old img.reader-page
        if not img_urls:
            imgs = soup.select("img.reader-page")
            for img in imgs:
                src = (img.get("data-original") or img.get("src") or "").strip()
                if src and "zjcdn" in src:
                    if src.startswith("//"): src = "https:" + src
                    img_urls.append(src)
        
        img_urls = list(dict.fromkeys(img_urls))
        if not img_urls:
            logger.warning(f"No images found for ch {ch_num} at {ch_url}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        # FanFox often checks Referer for image downloads
        return self.process_chapter_multi(img_urls, folder, ch_num, fetch_url, live=live, stats_callback=stats_callback)
