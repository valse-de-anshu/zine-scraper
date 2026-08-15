import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .engine import BaseScraper

class GutenbergScraper(BaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        # Extract book ID from url (e.g. https://www.gutenberg.org/ebooks/11)
        match = re.search(r'/ebooks/(\d+)', self.url)
        if match:
            self.book_id = match.group(1)
        else:
            self.book_id = None
            
        self.is_playlist = True

    def get_metadata_and_assets(self):
        if not self.book_id:
            raise ValueError("Invalid Project Gutenberg URL")

        # Parse directly from Project Gutenberg's official website HTML
        resp = self.session.get(self.url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')

        # Parse bibliographic metadata from the official Gutenberg table
        title = ""
        author = "Unknown"
        language = "Unknown"
        subjects = []

        table = soup.select_one('table.bibrec')
        if table:
            for tr in table.select('tr'):
                th = tr.select_one('th')
                td = tr.select_one('td')
                if th and td:
                    key = th.text.strip().lower()
                    val = td.text.strip()
                    if "title" in key:
                        title = val
                    elif "author" in key:
                        author = val
                    elif "language" in key:
                        language = val
                    elif "subject" in key:
                        subjects.append(val)

        if not title:
            title_el = soup.select_one('h1')
            title = title_el.text.strip() if title_el else "Unknown Title"

        # Clean title suffix if present
        title = title.split(" | ")[0].strip()

        # Extract Cover image URL
        cover_url = ""
        cover_el = soup.select_one('img.cover-art, img[src*="cover"]')
        if cover_el:
            cover_url = urljoin(self.url, cover_el.get('src', ''))

        metadata = {
            "Title": title,
            "Source": "gutenberg.org",
            "Author": author,
            "Language": language,
            "Ebook ID": self.book_id,
            "Subjects": ", ".join(subjects[:3]) + ("..." if len(subjects) > 3 else "") if subjects else "None",
            "Cover URL": cover_url
        }

        # Parse book formats and files
        assets = []

        def parse_size_text(txt):
            if not txt: return 0
            txt = txt.replace('\xa0', ' ').replace(',', '').strip()
            m = re.search(r'([\d.]+)\s*([a-zA-Z]*)', txt)
            if m:
                try:
                    val = float(m.group(1))
                    unit = m.group(2).lower()
                    if 'kb' in unit or 'k' in unit:
                        return int(val * 1024)
                    elif 'mb' in unit or 'm' in unit:
                        return int(val * 1024 * 1024)
                    return int(val)
                except: pass
            return 0

        # 1. Parse Featured formats (Recommended downloads)
        for row in soup.select('div.featured-format-row'):
            link_el = row.select_one('a.featured-format-link')
            if not link_el: continue
            
            link = urljoin(self.url, link_el.get('href', ''))
            name_el = link_el.select_one('.featured-format-name')
            name = name_el.text.strip() if name_el else "EPUB"
            
            size_el = row.select_one('.featured-format-size')
            size_text = size_el.text.strip() if size_el else ""
            size = parse_size_text(size_text)
            
            filename = link.split("/")[-1].split("?")[0]
            
            # Clean up broken extensions from Gutenberg links
            if filename.endswith(".utf-8"):
                filename = filename[:-6]
            elif ".epub" in filename:
                if "noimages" in filename:
                    filename = filename.replace(".epub.noimages", "-no-images.epub").replace(".epub3.noimages", "-no-images.epub")
                elif "images" in filename:
                    filename = filename.replace(".epub.images", ".epub").replace(".epub3.images", ".epub")
            
            assets.append({
                "id": filename,
                "name": name,
                "desc": "E-reader [Recommended]" if "epub" in name.lower() else "File",
                "filename": filename,
                "url": link,
                "size_bytes": size,
            })

        # 2. Parse Other formats list
        for row in soup.select('div.other-format-row'):
            link_el = row.select_one('a.other-format-link')
            if not link_el: continue
            
            link = urljoin(self.url, link_el.get('href', ''))
            name = link_el.text.strip()
            mime = link_el.get('type') or link_el.get('content') or ""
            
            size_el = row.select_one('.other-format-size')
            size_text = size_el.text.strip() if size_el else ""
            size = parse_size_text(size_text)
            
            filename = link.split("/")[-1].split("?")[0]
            
            # Clean up broken extensions from Gutenberg links
            if filename.endswith(".utf-8"):
                filename = filename[:-6]
            elif ".epub" in filename:
                if "noimages" in filename:
                    filename = filename.replace(".epub.noimages", "-no-images.epub").replace(".epub3.noimages", "-no-images.epub")
                elif "images" in filename:
                    filename = filename.replace(".epub.images", ".epub").replace(".epub3.images", ".epub")
            
            format_map = {
                "epub": "EPUB",
                "kindle": "Kindle",
                "html": "HTML",
                "txt": "TXT",
                "text": "TXT",
                "zip": "ZIP",
                "rdf": "RDF"
            }
            format_name = "Unknown"
            for k, v in format_map.items():
                if k in name.lower() or k in mime.lower():
                    format_name = v
                    break
                    
            assets.append({
                "id": filename,
                "name": format_name if format_name != "Unknown" else name,
                "desc": name,
                "filename": filename,
                "url": link,
                "size_bytes": size,
            })

        return metadata, assets
