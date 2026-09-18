import sys
import importlib

# Provide module aliases for 3_SYSTEM system extractors
try:
    _pw = importlib.import_module("scrapers.3_SYSTEM.playwright_extractor")
    sys.modules["scrapers.playwright_extractor"] = _pw
except Exception:
    pass

try:
    _hls = importlib.import_module("scrapers.3_SYSTEM.hls_extractor")
    sys.modules["scrapers.hls_extractor"] = _hls
except Exception:
    pass
