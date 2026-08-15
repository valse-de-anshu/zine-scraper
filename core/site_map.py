from typing import Optional
from core.domain_manager import DomainManager
from pathlib import Path

domain_manager = DomainManager(Path(__file__).parent.parent / "scrapers")

SITE_MAP = {
    "anikoto.cz": "anikoto",
    "anikototv.to": "anikoto",
    "anikoto.me": "anikoto",
    "anikoto.net": "anikoto",
    "anikototv.se": "anikoto",
    "miruro.to": "miruro",
    "miruro.ru": "miruro",
    "miruro.tv": "miruro",
    "miruro.bz": "miruro",
    "manhuaplus.org": "manhuaplus",
    "manhwaus.net": "manhwaus",
    "hentai18.net": "hentai18",
    "hentai20.io": "hentai20",
    "asurascans.com": "asurascans",
    "asuracomic.net": "asurascans",
    "asuratoon.com": "asurascans",
    "omegascans.org": "omegascans",
    "kunmanga.co.uk": "kunmanga",
    "fanfox.net": "fanfox",
    "nhentai.net": "nhentai",
    "weebcentral.com": "weebcentral",
    "mangak.io": "mangak",
    "projectsuki.com": "projectsuki",
    "gutenberg.org": "gutenberg",
    "archive.org": "archive",
    "music.youtube.com": "youtube.yt_music",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "pornhub.com": "pornhub",
    "phncdn.com": "pornhub",
    "pinterest.com": "pinterest",
    "pin.it": "pinterest",
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "fb.watch": "facebook",
    "soundcloud.com": "soundcloud",

    "idagio.com": "idagio",
    "anitaku.online": "anitaku",
    "anitaku.to": "anitaku",
    "anitaku.me": "anitaku",
    "hianime.to": "hianime",
    "hianime.sx": "hianime",
    "hianime.mn": "hianime",
    "hianime.nz": "hianime",
    "hianime.ad": "hianime",
    "hianime.re": "hianime",
    "hianime.pm": "hianime",
    "anineko.to": "anineko",
    "hentaicity.com": "hentaicity",
    "hstream.moe": "hstream",
    "read.oppai.stream": "oppai_stream.oppai_stream_toon",
    "oppai.stream": "oppai_stream",
    "hentaimama.io": "hentaimama",
    "ohentai.org": "ohentai",
    "asmhentai.com": "asmhentai",
    "lightnovelworld.org": "light_novel.lightnovelworld",
    "novelarchive.cc": "light_novel.novelarchive",
    "chikari.moe": "light_novel.chikari",
    "novelphoenix.com": "light_novel.novelphoenix",
    "novelfire.net": "light_novel.novelfire",
    "novelfire.docs": "light_novel.novelfire",
    "novelbuddy.me": "light_novel.novelbuddy",
    "novelbuddy.com": "light_novel.novelbuddy",
}

# Dynamically add domains from scraper configs
SITE_MAP.update(domain_manager.get_dynamic_site_map())


def get_site_folder(url: str) -> Optional[str]:
    url_lower = url.lower()
    return next((folder for domain, folder in SITE_MAP.items() if domain in url_lower), None)
