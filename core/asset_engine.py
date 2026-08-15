import requests
import time
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

class AssetBaseScraper:
    """Base class for scrapers that download discrete files (assets) rather than chapters/pages."""
    
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.scraper_type = "asset"
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def download_file(self, url: str, path: Path, stats_callback=None) -> bool:
        """Downloads a file with a progress callback, retries, and size validation."""
        max_retries = 3
        timeout = 60
        
        for attempt in range(max_retries):
            try:
                # Use stream=True to handle large files
                with self.session.get(url, stream=True, timeout=timeout) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    
                    if stats_callback:
                        stats_callback({"total_bytes": total_size, "downloaded_bytes": 0})
                        
                    with open(path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024*1024): # 1MB chunks for performance
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if stats_callback:
                                    stats_callback({"total_bytes": total_size, "downloaded_bytes": downloaded})
                    
                    # Verify download completeness if Content-Length was provided
                    if total_size > 0 and downloaded < total_size:
                        raise Exception(f"Download incomplete: {downloaded}/{total_size} bytes")
                        
                    return True
            except Exception as e:
                # If an error occurs, clean up partial file before retry
                if path.exists():
                    path.unlink()
                    
                if attempt == max_retries - 1:
                    return False
                time.sleep(2) # Wait before retry
        return False
