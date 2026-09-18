import re
import json
import subprocess
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from .engine import OhentaiEngine
import logging

logger = logging.getLogger(__name__)


class OhentaiScraper:
    def __init__(self, url: str):
        self.url = url
        self.engine = OhentaiEngine()
        self.session = cffi_requests.Session(impersonate="chrome124")
        self.title = "Ohentai Video"
        self.metadata = {}

    def _fetch_html(self, url: str) -> str:
        """Fetches page HTML with fast curl_cffi impersonation, falling back to Playwright if challenged."""
        try:
            r = self.session.get(url, impersonate="chrome124", timeout=15)
            if r.status_code == 200 and "Just a moment" not in r.text and "<html" in r.text.lower():
                return r.text
        except Exception as e:
            logger.debug(f"[Ohentai] curl_cffi request failed for {url}: {e}")

        # Fallback to headless Playwright extractor
        try:
            script_path = Path(__file__).parent.parent / "playwright_extractor.py"
            cmd = ["python3", str(script_path), url]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            out_str = result.stdout
            json_str = out_str.split("JSON_RESULT:")[-1]
            data = json.loads(json_str)
            return data.get("html", "")
        except Exception as e:
            logger.error(f"[Ohentai] playwright_extractor fallback failed for {url}: {e}")
            return ""

    def get_metadata_and_videos(self):
        videos = []
        meta = {
            "Channel/Series": "Ohentai Video",
            "Total Videos": 1,
            "Thumbnail": "",
            "Avatar URL": "",
            "Tags": "",
            "Description": "",
            "URL": self.url,
        }

        try:
            html = self._fetch_html(self.url)
            if not html:
                raise RuntimeError(f"Could not load HTML for {self.url}")

            soup = BeautifulSoup(html, "lxml")
            is_series = "sery_video.php" in self.url

            # If this is a detail.php episode page, locate the series overview page link
            sery_url = None
            if not is_series:
                for a in soup.find_all("a", href=True):
                    if "sery_video.php?seryid=" in a["href"]:
                        sery_url = urllib.parse.urljoin("https://ohentai.org/", a["href"])
                        break

            # Fetch sery_video page if we started on detail.php and found sery_url
            sery_soup = soup if is_series else None
            if sery_url and not is_series:
                try:
                    s_html = self._fetch_html(sery_url)
                    if s_html:
                        sery_soup = BeautifulSoup(s_html, "lxml")
                except Exception as e:
                    logger.debug(f"[Ohentai] Failed to fetch series overview {sery_url}: {e}")

            # 1. Clean Series Title
            series_name = ""
            if sery_soup and sery_soup.find("h1"):
                series_name = sery_soup.find("h1").text.strip()
            elif soup.find("h1"):
                h1_t = soup.find("h1").text.strip()
                series_name = h1_t.split(" - ")[0].strip() if " - " in h1_t else h1_t
            elif soup.title:
                t = soup.title.text.strip()
                t = re.sub(r"^Watch\s+", "", t, flags=re.I)
                t = re.sub(r"\s+Hentai Video.*", "", t, flags=re.I)
                t = re.sub(r"\s*–\s*Ohentai\.org.*", "", t, flags=re.I)
                series_name = t.split(" - ")[0].strip() if " - " in t else t

            series_name = series_name or "Ohentai Video"
            meta["Channel/Series"] = series_name

            # 2. Cover / Thumbnail
            thumbnail = ""
            target_soups = [sery_soup, soup] if sery_soup else [soup]
            for s in target_soups:
                for img in s.find_all("img"):
                    src = img.get("src", "")
                    if "cover" in src.lower():
                        thumbnail = urllib.parse.urljoin("https://ohentai.org/", src)
                        break
                if thumbnail:
                    break
            if not thumbnail:
                for s in target_soups:
                    for img in s.find_all("img"):
                        src = img.get("src", "")
                        if "video_data" in src.lower() and not src.lower().endswith((".svg", ".gif")):
                            thumbnail = urllib.parse.urljoin("https://ohentai.org/", src)
                            break
                    if thumbnail:
                        break

            meta["Thumbnail"] = thumbnail
            meta["Avatar URL"] = thumbnail

            # 3. Tags
            tags = []
            for s in target_soups:
                for a in s.find_all("a", href=True):
                    if "tagsearch.php?tag=" in a["href"]:
                        t = a.text.strip()
                        if t and not t.isdigit() and t not in tags:
                            tags.append(t)
            meta["Tags"] = ", ".join(tags)

            # 4. Description
            desc = ""
            for s in [soup, sery_soup] if sery_soup else [soup]:
                for elem in s.find_all(string=lambda x: x and "Description:" in x):
                    desc_text = elem.parent.parent.text.replace("Description:", "").strip()
                    if desc_text:
                        desc = desc_text
                        break
                if desc:
                    break

            # 5. Episodes Extraction
            ep_nodes = []
            seen_hrefs = set()

            if sery_soup:
                # On sery_video.php, franchise episodes link to detail.php?vid=...
                for a in sery_soup.find_all("a", href=True):
                    href = a["href"]
                    if "detail.php?vid=" in href:
                        text = a.text.strip()
                        if text.lower() in ("random hentai", "subbed", "dubbed", ""):
                            continue
                        full_href = urllib.parse.urljoin("https://ohentai.org/", href)
                        if full_href not in seen_hrefs:
                            seen_hrefs.add(full_href)
                            ep_m = re.search(r"Episode\s*(\d+)", text, re.I)
                            ep_num = int(ep_m.group(1)) if ep_m else (len(ep_nodes) + 1)
                            ep_nodes.append({
                                "ep_num": ep_num,
                                "title": f"Episode {ep_num}",
                                "url": full_href,
                            })
            else:
                # On detail.php without sery page, look for direct series Episode buttons
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "detail.php?vid=" in href:
                        text = a.text.strip()
                        if re.match(r"^Episode\s*\d+$", text, re.I):
                            full_href = urllib.parse.urljoin("https://ohentai.org/", href)
                            if full_href not in seen_hrefs:
                                seen_hrefs.add(full_href)
                                ep_m = re.search(r"Episode\s*(\d+)", text, re.I)
                                ep_num = int(ep_m.group(1)) if ep_m else (len(ep_nodes) + 1)
                                ep_nodes.append({
                                    "ep_num": ep_num,
                                    "title": f"Episode {ep_num}",
                                    "url": full_href,
                                })

            # If current URL was detail.php and wasn't in ep_nodes, add it
            if "detail.php" in self.url and not any(e["url"] == self.url for e in ep_nodes):
                ep_m = re.search(r"Episode\s*(\d+)", soup.title.text if soup.title else "", re.I)
                ep_num = int(ep_m.group(1)) if ep_m else (len(ep_nodes) + 1)
                ep_nodes.append({
                    "ep_num": ep_num,
                    "title": f"Episode {ep_num}",
                    "url": self.url,
                })

            ep_nodes.sort(key=lambda x: x["ep_num"])

            # If started from sery_video and no desc found, pull from first episode page
            if not desc and ep_nodes:
                try:
                    ep1_html = self._fetch_html(ep_nodes[0]["url"])
                    if ep1_html:
                        ep1_soup = BeautifulSoup(ep1_html, "lxml")
                        for elem in ep1_soup.find_all(string=lambda x: x and "Description:" in x):
                            desc_text = elem.parent.parent.text.replace("Description:", "").strip()
                            if desc_text:
                                desc = desc_text
                                break
                except Exception:
                    pass

            meta["Description"] = desc

            for ep in ep_nodes:
                videos.append({
                    "id": str(ep["ep_num"]),
                    "title": ep["title"],
                    "url": ep["url"],
                })

        except Exception as e:
            logger.error(f"[Ohentai] Failed to extract metadata: {e}")
            if not videos:
                videos.append({
                    "id": "1",
                    "title": "Episode 1",
                    "url": self.url,
                })

        meta["Total Videos"] = len(videos)
        info = {"Total Videos": len(videos)}
        self.title = meta["Channel/Series"]
        self.metadata = meta
        return meta, videos, info
