"""
Instagram Reels Scraper (Dedicated Reels Tab)
Standalone module to extract and download all video reels from an Instagram profile Reels tab.
"""
import sys
import os
import argparse
from pathlib import Path
from scrapers.instagram.engine import InstagramEngine
from scrapers.instagram.scraper import InstagramScraper
from core.history import HistoryLayer
from core.storage import StorageLayer

def scrape_reels(profile_url: str, output_dir: str = None):
    """
    Extract and download all video reels from the profile Reels tab.
    """
    username = profile_url.strip('/').split('/')[-1].split('?')[0]
    target_url = f"https://www.instagram.com/{username}/?target=reels"

    print(f"[Instagram Reels Scraper] Extracting video reels from: {target_url}")
    engine = InstagramEngine()
    scraper = InstagramScraper(target_url)

    meta, pins = engine.get_board_pins(target_url)
    print(f"[Instagram Reels Scraper] Found {len(pins)} video reel(s).")

    if not pins:
        print("[Instagram Reels Scraper] No video reels found.")
        return []

    # Determine save folder
    if output_dir:
        save_folder = Path(output_dir)
    else:
        save_folder = Path("Downloads") / "Instagram" / username / "Reels Tab"

    save_folder.mkdir(parents=True, exist_ok=True)
    from core.paths import PathAuthority
    storage = StorageLayer()
    tracker = HistoryLayer(PathAuthority(), storage)

    downloaded = 0
    for idx, pin in enumerate(pins, 1):
        pin_id = pin["id"]
        pin_title = pin["title"]
        direct_url = pin.get("direct_url") or ""

        if not direct_url:
            continue

        ext = ".mp4"
        clean_title = "".join([c for c in pin_title if c.isalnum() or c in " .-_()"]).strip() or f"reel_{pin_id}"
        pin_path, is_downloaded = tracker.resolve_download_path(save_folder, str(pin_id), clean_title, ext)

        if is_downloaded:
            print(f" [{idx}/{len(pins)}] Exists: {pin_path.name}")
            continue

        print(f" [{idx}/{len(pins)}] Downloading reel: {pin_path.name}...")
        success = scraper.download_asset(direct_url, str(pin_path), is_video=True)
        if success:
            tracker.mark_downloaded(target_url, str(pin_id))
            downloaded += 1

    print(f"\n[Instagram Reels Scraper] Completed! Downloaded {downloaded} new video reel(s) into: {save_folder.resolve()}")
    return pins

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape all video reels from an Instagram profile Reels tab.")
    parser.add_argument("url", nargs="?", help="Instagram Profile URL (e.g. https://www.instagram.com/pujaa_singh47/)")
    parser.add_argument("-o", "--output", help="Custom output directory")
    args = parser.parse_args()

    url = args.url
    if not url:
        if __import__("sys").stdin.isatty():
            url = input("Enter Instagram Profile URL or @username: ").strip()
        else:
            print("[Error] No Instagram profile URL supplied. Pass it as the first argument.", file=sys.stderr)
            sys.exit(1)

    if url:
        scrape_reels(url, args.output)
