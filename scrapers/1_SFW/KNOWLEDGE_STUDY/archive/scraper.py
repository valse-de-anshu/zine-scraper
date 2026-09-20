import re
from .engine import BaseScraper

class ArchiveScraper(BaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        # Extract identifier from details or metadata URL
        match = re.search(r'/(?:details|metadata)/([^/]+)', self.url)
        if match:
            self.identifier = match.group(1).split("?")[0]
        else:
            self.identifier = None

    def get_metadata_and_assets(self):
        if not self.identifier:
            raise ValueError("Invalid Internet Archive URL")

        # Official IA Metadata API
        resp = self.session.get(f"https://archive.org/metadata/{self.identifier}")
        resp.raise_for_status()
        data = resp.json()

        if not data.get("metadata"):
            raise ValueError("Item not found or empty metadata")

        meta = data["metadata"]
        
        # Format collections
        collections = meta.get("collection", [])
        if isinstance(collections, str):
            collections = [collections]

        metadata = {
            "Title": meta.get("title", "Unknown").strip(),
            "Source": "archive.org",
            "Identifier": self.identifier,
            "Type": meta.get("mediatype", "Unknown").capitalize(),
            "Creator": meta.get("creator", "Unknown"),
            "Collection": ", ".join(collections) if collections else "Unknown",
        }

        # Handle list vs string for creator
        if isinstance(metadata["Creator"], list):
            metadata["Creator"] = ", ".join(metadata["Creator"])

        assets = []
        files = data.get("files", [])
        
        # Filter files to primary content
        # Skip metadata, thumbnails, and optionally derivations if requested
        for f in files:
            name = f.get("name", "")
            if not name:
                continue
                
            fmt = f.get("format", "Unknown")
            source = f.get("source", "original")
            
            # Skip IA system files
            if fmt == "Metadata" or name.endswith("_files.xml") or name.endswith("_meta.xml") or name.endswith("_meta.sqlite") or name.endswith("_archive.torrent"):
                continue

            # Prioritize original files over derivative (OCR, etc) unless it's a specific format
            if source == "derivative" and fmt in ["Abbyy GZ", "Djvu XML", "Page Numbers JSON", "Scandata"]:
                continue

            size_str = f.get("size", "0")
            size_bytes = int(size_str) if size_str.isdigit() else 0

            download_url = f"https://archive.org/download/{self.identifier}/{name}"

            assets.append({
                "id": name,
                "name": name,
                "desc": fmt,
                "filename": name.split("/")[-1],
                "url": download_url,
                "size_bytes": size_bytes
            })

        # Sort assets by size descending as a generic heuristic
        assets.sort(key=lambda x: x["size_bytes"], reverse=True)

        return metadata, assets
