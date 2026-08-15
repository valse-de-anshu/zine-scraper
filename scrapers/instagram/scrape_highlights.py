"""
Instagram Highlights Scraper (Story Highlights)
Standalone module to extract and download all story highlights from an Instagram profile.
"""
import sys
import os
import argparse
from pathlib import Path
from scrapers.instagram.engine import InstagramEngine
from scrapers.instagram.scraper import InstagramScraper
from core.history import HistoryLayer

def scrape_highlights(profile_url: str, output_dir: str = None):
    """
    Extract and download all story highlights across all highlight bubbles.
    """
    username = profile_url.strip('/').split('/')[-1].split('?')[0]
    target_url = f"https://www.instagram.com/{username}/?target=highlights"

    print(f"[Instagram Highlights Scraper] Extracting story highlights from: {target_url}")
    engine = InstagramEngine()
    scraper = InstagramScraper(target_url)

    meta, pins = engine.get_board_pins(target_url)
    print(f"[Instagram Highlights Scraper] Found {len(pins)} story highlight item(s).")

    if not pins:
        print("[Instagram Highlights Scraper] No story highlights found.")
        return []

    # Determine save folder
    if output_dir:
        save_folder = Path(output_dir)
    else:
        save_folder = Path("Downloads") / "Instagram" / username / "Story Highlights"

    save_folder.mkdir(parents=True, exist_ok=True)
    from core.paths import PathAuthority
    from core.storage import StorageLayer
    storage = StorageLayer()
    tracker = HistoryLayer(PathAuthority(), storage)

    downloaded = 0
    for idx, pin in enumerate(pins, 1):
        pin_id = pin["id"]
        pin_title = pin["title"]
        direct_url = pin.get("direct_url") or ""
        is_video = pin.get("is_video", False)

        if not direct_url:
            continue

        ext = ".mp4" if is_video else ".jpg"
        if not is_video:
            if ".png" in direct_url.lower():
                ext = ".png"
            elif ".webp" in direct_url.lower():
                ext = ".webp"

        clean_title = "".join([c for c in pin_title if c.isalnum() or c in " .-_()"]).strip() or f"story_{pin_id}"
        pin_path, is_downloaded = tracker.resolve_download_path(save_folder, str(pin_id), clean_title, ext)

        if is_downloaded:
            print(f" [{idx}/{len(pins)}] Exists: {pin_path.name}")
            continue

        print(f" [{idx}/{len(pins)}] Downloading story ({'video' if is_video else 'image'}): {pin_path.name}...")
        success = scraper.download_asset(direct_url, str(pin_path), is_video=is_video)
        if success:
            tracker.mark_downloaded(target_url, str(pin_id))
            downloaded += 1

    print(f"\n[Instagram Highlights Scraper] Completed! Downloaded {downloaded} new story item(s) into: {save_folder.resolve()}")
    return pins

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape all story highlights from an Instagram profile.")
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
        scrape_highlights(url, args.output)
