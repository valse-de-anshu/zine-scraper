import sys
import json
import logging
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth

logging.basicConfig(level=logging.ERROR)

def extract_ssr(url: str):
    ssr_data = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            stealth(page)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            try:
                # Add a tiny delay to ensure scripts populate the window object
                page.wait_for_timeout(2000)
                ssr_data = page.evaluate("window.__SSR_DATA__")
            except Exception as e:
                pass
            browser.close()
    except Exception as e:
        pass
    
    if ssr_data:
        print("JSON_RESULT:" + json.dumps(ssr_data))
    else:
        print("FAILED:{}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    extract_ssr(sys.argv[1])
