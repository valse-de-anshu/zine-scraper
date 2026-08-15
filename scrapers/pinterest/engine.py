import os
import re
import json
import logging
import subprocess
import requests
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger(__name__)

class PinterestEngine:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

    def get_profile_boards(self, profile_url: str) -> List[Dict[str, str]]:
        """
        Extracts ALL board links and pin counts from a Pinterest profile by checking
        multiple subpages and aggressively parsing embedded JSON payloads.
        """
        import urllib.parse
        
        # Normalize profile URL to base
        base_url = profile_url.rstrip('/')
        if '/_saved' in base_url: base_url = base_url.replace('/_saved', '')
        if '/_created' in base_url: base_url = base_url.replace('/_created', '')
        
        # Target pages to check for board data
        targets = [base_url, f"{base_url}/_saved/"]
        
        boards_map = {} # board_id -> board_dict
        session = requests.Session()
        
        # Extract username for filtering
        user_match = re.search(r"pinterest\.[a-z\.]+/([^/?#]+)", base_url)
        if not user_match: return []
        username = user_match.group(1).lower()

        for target in targets:
            try:
                r = session.get(target, headers=self.headers, timeout=10)
                if r.status_code != 200: continue
                
                # Find all JSON blocks in script tags
                json_blocks = re.findall(r'<script id="(?:__PWS_DATA__|__PWS_INITIAL_PROPS__)" type="application/json">(.*?)</script>', r.text)
                
                for block in json_blocks:
                    try:
                        data = json.loads(block)
                        
                        def extract_boards(obj):
                            if isinstance(obj, dict):
                                if obj.get('type') == 'board' and 'url' in obj and 'name' in obj:
                                    b_url = obj['url']
                                    owner = obj.get('owner', {}).get('username', '').lower()
                                    # Belongs to user?
                                    if f"/{username}/" in b_url.lower() or owner == username:
                                        bid = str(obj.get('id'))
                                        if bid not in boards_map:
                                            boards_map[bid] = {
                                                "url": f"https://www.pinterest.com{b_url}",
                                                "title": obj['name'],
                                                "id": bid,
                                                "pin_count": str(obj.get('pin_count', 'Unknown'))
                                            }
                                for v in obj.values(): extract_boards(v)
                            elif isinstance(obj, list):
                                for item in obj: extract_boards(item)
                        
                        extract_boards(data)
                    except: continue
            except: continue

        # Final list sorted by title
        result = list(boards_map.values())
        
        # Fallback to broad regex if still too few boards
        if len(result) < 5:
             # Very broad regex to catch anything that looks like a user board link
             # \"url\":\"/username/slug/\"
             slug_matches = re.findall(rf'\"url\":\"/{username}/([^/]+)/\"', r.text, re.IGNORECASE)
             for slug in set(slug_matches):
                 if slug.lower() not in ['_saved', '_created', 'pins']:
                     # We don't have the ID here, so we skip if it's already in boards_map
                     # or we could attempt to add it.
                     pass

        result = sorted(result, key=lambda x: x['title'])
        result.insert(0, {
            "title": "Profile Picture Only",
            "url": f"{base_url}/_pfp/",
            "id": "pfp",
            "pin_count": "1"
        })
        return result

    def get_profile_pins(self, profile_url: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Concat pins from all boards of a profile.
        """
        boards = self.get_profile_boards(profile_url)
        all_pins = []
        metadata = {"Title": "Pinterest Profile", "Source": "Pinterest"}
        
        # Extract username for metadata
        user_match = re.search(r"pinterest\.[a-z\.]+/([^/?#]+)", profile_url)
        if user_match:
            metadata["Title"] = f"Pinterest: {user_match.group(1)}"
            metadata["Username"] = user_match.group(1)

        for board in boards:
            b_meta, pins = self.get_board_pins(board["url"])
            if "profile_picture" in b_meta and "profile_picture" not in metadata:
                metadata["profile_picture"] = b_meta["profile_picture"]
            # Add board name to pin title for context
            for pin in pins:
                pin["title"] = f"[{board['title']}] {pin['title']}"
            all_pins.extend(pins)
            
        # De-duplicate
        seen_ids = set()
        unique_pins = []
        for pin in all_pins:
            if pin["id"] not in seen_ids:
                unique_pins.append(pin)
                seen_ids.add(pin["id"])
        
        metadata["Total Pins"] = len(unique_pins)
        metadata["Total Boards"] = len(boards)
        return metadata, unique_pins

    def get_board_pins(self, board_url: str, scroll_limit: int = 60) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Extract all pins from a Pinterest board using Playwright network interception, 
        and use aiohttp to concurrently enrich video metadata using the unauth_react_main_pin API.
        """
        metadata = {"Channel/Series": "Unknown Board", "Source": "Pinterest"}

        try:
            result = asyncio.run(
                self._playwright_scrape_board(board_url, scroll_limit)
            )
            board_meta, raw_pins = result
            metadata.update(board_meta)
            
            # Batch enrich with aiohttp
            if raw_pins:
                logger.info("Batch enriching pins to find videos...")
                raw_pins = asyncio.run(self._batch_enrich_pins(raw_pins))
                
        except Exception as e:
            logger.warning(f"Playwright board scrape failed ({e})")
            return metadata, []

        # Normalize + de-duplicate
        seen = set()
        pins = []
        for raw in raw_pins:
            pin = self._extract_pin_data(raw)
            if pin and pin["id"] not in seen:
                seen.add(pin["id"])
                pins.append(pin)

        logger.info(f"Board '{metadata.get('Channel/Series')}': {len(pins)} pins extracted")
        return metadata, pins

    async def _batch_enrich_pins(self, raw_pins: List[Dict]) -> List[Dict]:
        import aiohttp
        
        async def fetch_pin(session, pin):
            pin_id = pin["id"]
            url = "https://www.pinterest.com/resource/PinResource/get/"
            params = {
                "source_url": f"/pin/{pin_id}/",
                "data": json.dumps({"options": {"id": pin_id, "field_set_key": "unauth_react_main_pin"}})
            }
            headers = {
                "User-Agent": self.headers["User-Agent"], 
                "X-Pinterest-PWS-Handler": "www/[username].js"
            }
            try:
                async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        enrichment = data.get('resource_response', {}).get('data', {})
                        if isinstance(enrichment, dict):
                            for field in ("videos", "video_list", "v_hlsv4_video_list", "is_video", "story_pin_data"):
                                if enrichment.get(field) and not pin.get(field):
                                    pin[field] = enrichment[field]
            except Exception:
                pass
            return pin
            
        async with aiohttp.ClientSession() as session:
            tasks = [fetch_pin(session, p) for p in raw_pins]
            return await asyncio.gather(*tasks)

    def _extract_pin_data(self, pin: Dict) -> Optional[Dict]:
        if not isinstance(pin, dict):
            return None
        pin_id = str(pin.get("id", ""))
        if not pin_id:
            return None

        title = (
            pin.get("grid_title")
            or pin.get("title")
            or pin.get("alt_text")
            or pin.get("description", "")
            or f"Pin {pin_id}"
        ).strip()

        is_video = bool(pin.get("is_video"))

        image_url = None
        images = pin.get("images", {})
        if isinstance(images, dict):
            for size in ("orig", "736x", "474x", "236x"):
                if size in images and isinstance(images[size], dict) and images[size].get("url"):
                    image_url = images[size]["url"]
                    break

        video_url = None
        videos = pin.get("videos")
        if videos and isinstance(videos, dict) and "video_list" in videos:
            try:
                v_list = videos["video_list"]
                if isinstance(v_list, dict):
                    sorted_keys = sorted(v_list.keys(), reverse=True)
                    if sorted_keys:
                        video_url = v_list[sorted_keys[0]]["url"]
                        is_video = True
            except Exception: pass
                
        if not video_url and pin.get("v_hlsv4_video_list"):
            try:
                v_list = pin["v_hlsv4_video_list"]
                if isinstance(v_list, dict):
                    for vk in sorted(v_list.keys(), reverse=True):
                        if isinstance(v_list[vk], dict) and v_list[vk].get("url"):
                            video_url = v_list[vk]["url"]
                            is_video = True
                            break
            except Exception: pass
            
        if not video_url and "story_pin_data" in pin:
            try:
                spd = pin["story_pin_data"]
                if isinstance(spd, dict):
                    pages = spd.get("pages_preview", []) or spd.get("pages", [])
                    for page in pages:
                        if not isinstance(page, dict): continue
                        for block in page.get("blocks", []):
                            if not isinstance(block, dict): continue
                            if block.get("video") and isinstance(block["video"], dict) and block["video"].get("video_list"):
                                v_list = block["video"]["video_list"]
                                if isinstance(v_list, dict):
                                    for vk in sorted(v_list.keys(), reverse=True):
                                        if isinstance(v_list[vk], dict) and v_list[vk].get("url"):
                                            video_url = v_list[vk]["url"]
                                            is_video = True
                                            break
                            if video_url: break
                        if video_url: break
            except Exception: pass

        direct_url = video_url or image_url
        if not direct_url:
            return None

        return {
            "id": pin_id,
            "title": title,
            "url": f"https://www.pinterest.com/pin/{pin_id}/",
            "direct_url": direct_url,
            "thumbnail": image_url,
            "is_video": is_video,
            "upload_date": pin.get("created_at", "UnknownDate"),
        }

    async def _playwright_scrape_board(
        self, board_url: str, scroll_limit: int
    ) -> Tuple[Dict, List]:
        from playwright.async_api import async_playwright

        all_raw_pins: List[Dict] = []
        board_meta: Dict = {}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.headers["User-Agent"],
                locale="en-US",
            )
            page = await context.new_page()
            
            try:
                from playwright_stealth import Stealth
                stealth = Stealth()
                await stealth.apply_stealth_async(page)
            except Exception as e:
                logger.warning(f"Failed to apply stealth: {e}")

            async def on_response(response):
                if "/resource/" not in response.url:
                    return
                if response.status != 200:
                    return
                try:
                    board_resources = ["BoardFeedResource", "UserPinsResource", "UserSavedRecipesResource", "UserActivityPinsResource"]
                    is_board_feed = any(res in response.url for res in board_resources)

                    if not is_board_feed:
                        return

                    body = await response.json()
                    rr = body.get("resource_response", {})
                    data = rr.get("data", [])

                    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "id" in data[0]:
                        all_raw_pins.extend(data)
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                await page.goto(board_url, timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning(f"Page load partial timeout: {e}")
                
            try:
                content = await page.content()
                
                # Extract profile picture
                pfp_match = re.search(r'"image_xlarge_url":"([^"]+)"', content)
                if pfp_match:
                    board_meta["profile_picture"] = pfp_match.group(1)
                else:
                    # Fallback for _created pages which lack the image in raw HTML
                    try:
                        import requests
                        user_match = re.search(r"pinterest\.[a-z\.]+/([^/?#]+)", board_url)
                        if user_match:
                            base_url = f"https://www.pinterest.com/{user_match.group(1)}/"
                            r = requests.get(base_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                            pfp_match = re.search(r'"image_xlarge_url":"([^"]+)"', r.text)
                            if pfp_match:
                                board_meta["profile_picture"] = pfp_match.group(1)
                    except Exception:
                        pass
                    
                blocks = re.findall(
                    r'<script id="(?:__PWS_DATA__|__PWS_INITIAL_PROPS__)" type="application/json">(.*?)</script>',
                    content,
                )
                for block in blocks:
                    try:
                        data = json.loads(block)
                        redux = data.get("initialReduxState", {})
                        if not redux: continue
                        
                        board_resources = redux.get("resources", {}).get("BoardResource", {})
                        for _, v in board_resources.items():
                            bdata = v.get("data") or {}
                            if isinstance(bdata, dict) and bdata.get("name"):
                                board_meta["Channel/Series"] = bdata["name"]
                                board_meta["ID"] = str(bdata.get("id", ""))
                                board_meta["pin_count"] = bdata.get("pin_count", 0)
                                break
                                
                        pins_map = redux.get("pins", {})
                        for pid, pin in pins_map.items():
                            all_raw_pins.append(pin)
                        break
                    except Exception:
                        continue
            except Exception:
                pass

            if "/_pfp/" in board_url:
                await browser.close()
                return board_meta, []

            scroll_count = 0
            prev_count = 0
            stale_scrolls = 0
            while scroll_count < scroll_limit:
                await page.keyboard.press("PageDown")
                await page.wait_for_timeout(500)
                await page.keyboard.press("PageDown")
                await page.wait_for_timeout(1500)
                scroll_count += 1

                if len(all_raw_pins) == prev_count:
                    stale_scrolls += 1
                    if stale_scrolls >= 5:
                        break
                else:
                    stale_scrolls = 0
                    prev_count = len(all_raw_pins)

            await browser.close()
            
        if not board_meta.get("Channel/Series"):
            if "_created" in board_url.lower():
                board_meta["Channel/Series"] = "Created Pins"
            elif "_saved" in board_url.lower():
                board_meta["Channel/Series"] = "Saved Pins"

        # Remove duplicate raw pins
        seen_raw = set()
        unique_raw = []
        for rp in all_raw_pins:
            if rp["id"] not in seen_raw:
                seen_raw.add(rp["id"])
                unique_raw.append(rp)

        return board_meta, unique_raw

    def get_pin_info(self, pin_url: str) -> Dict[str, Any]:
        """
        Extracts high-res image or video from a single pin URL.
        """
        import json
        pin_id = pin_url.rstrip("/").split("/")[-1]
        if not pin_id:
            return {}
            
        url = "https://www.pinterest.com/resource/PinResource/get/"
        params = {
            "source_url": f"/pin/{pin_id}/",
            "data": json.dumps({"options": {"id": pin_id, "field_set_key": "unauth_react_main_pin"}})
        }
        headers = {
            "User-Agent": self.headers.get("User-Agent", "Mozilla/5.0"), 
            "X-Pinterest-PWS-Handler": "www/[username].js"
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                raw_pin = data.get("resource_response", {}).get("data", {})
                if isinstance(raw_pin, dict):
                    pin_info = self._extract_pin_data(raw_pin)
                    if pin_info:
                        return pin_info
        except Exception as e:
            logger.error(f"Error extracting single pin {pin_id}: {e}")
            
        return {}
