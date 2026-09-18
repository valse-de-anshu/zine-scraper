from typing import Optional
from core.domain_manager import DomainManager
from pathlib import Path

domain_manager = DomainManager(Path(__file__).parent.parent / "scrapers")

SITE_MAP = {
    # ── 1_SFW / ANIME ──
    "anikai.to": "1_SFW.ANIME.anikai",
    "anikoto.cz": "1_SFW.ANIME.anikoto",
    "anikototv.to": "1_SFW.ANIME.anikoto",
    "anikoto.me": "1_SFW.ANIME.anikoto",
    "anikoto.net": "1_SFW.ANIME.anikoto",
    "anikototv.se": "1_SFW.ANIME.anikoto",
    "anikoto.online": "1_SFW.ANIME.anikoto",
    "anineko.to": "1_SFW.ANIME.anineko",
    "anitaku.online": "1_SFW.ANIME.anitaku",
    "anitaku.to": "1_SFW.ANIME.anitaku",
    "anitaku.me": "1_SFW.ANIME.anitaku",
    "hianime.to": "1_SFW.ANIME.hianime",
    "hianime.sx": "1_SFW.ANIME.hianime",
    "hianime.mn": "1_SFW.ANIME.hianime",
    "hianime.nz": "1_SFW.ANIME.hianime",
    "hianime.ad": "1_SFW.ANIME.hianime",
    "hianime.re": "1_SFW.ANIME.hianime",
    "hianime.pm": "1_SFW.ANIME.hianime",
    "miruro.to": "1_SFW.ANIME.miruro",
    "miruro.ru": "1_SFW.ANIME.miruro",
    "miruro.tv": "1_SFW.ANIME.miruro",
    "miruro.bz": "1_SFW.ANIME.miruro",

    # ── 1_SFW / MANGA ──
    "mangadex.org": "1_SFW.MANGA.mangadex",

    # ── 1_SFW / MANHWA ──
    "asurascans.com": "1_SFW.MANHWA.asurascans",
    "asuracomic.net": "1_SFW.MANHWA.asurascans",
    "asuratoon.com": "1_SFW.MANHWA.asurascans",
    "projectsuki.com": "1_SFW.MANHWA.projectsuki",
    "manhuaplus.org": "1_SFW.MANHWA.manhuaplus",

    # ── 1_SFW / HYBRID_COMICS ──
    "kunmanga.co.uk": "1_SFW.HYBRID_COMICS.kunmanga",
    "kunmanga.com": "1_SFW.HYBRID_COMICS.kunmanga",
    "topmanhua.fan": "1_SFW.HYBRID_COMICS.topmanhua",
    "weebcentral.com": "1_SFW.HYBRID_COMICS.weebcentral",
    "fanfox.net": "1_SFW.HYBRID_COMICS.fanfox",
    "mangak.io": "1_SFW.HYBRID_COMICS.mangak",

    # ── 1_SFW / NOVELS ──
    "chikari.moe": "1_SFW.NOVELS.chikari",
    "novelarchive.cc": "1_SFW.NOVELS.novelarchive",
    "novelbuddy.me": "1_SFW.NOVELS.novelbuddy",
    "novelbuddy.com": "1_SFW.NOVELS.novelbuddy",
    "novelfire.net": "1_SFW.NOVELS.novelfire",
    "novelfire.docs": "1_SFW.NOVELS.novelfire",
    "novelphoenix.com": "1_SFW.NOVELS.novelphoenix",

    # ── 1_SFW / KNOWLEDGE_STUDY ──
    "archive.org": "1_SFW.KNOWLEDGE_STUDY.archive",
    "gutenberg.org": "1_SFW.KNOWLEDGE_STUDY.gutenberg",

    # ── 1_SFW / MUSIC ──
    "idagio.com": "1_SFW.MUSIC.idagio",
    "soundcloud.com": "1_SFW.MUSIC.soundcloud",
    "music.youtube.com": "1_SFW.MUSIC.yt_music",

    # ── 1_SFW / SOCIAL_MEDIA ──
    "facebook.com": "1_SFW.SOCIAL_MEDIA.facebook",
    "fb.watch": "1_SFW.SOCIAL_MEDIA.facebook",
    "instagram.com": "1_SFW.SOCIAL_MEDIA.instagram",
    "pinterest.com": "1_SFW.SOCIAL_MEDIA.pinterest",
    "pin.it": "1_SFW.SOCIAL_MEDIA.pinterest",
    "youtube.com": "1_SFW.SOCIAL_MEDIA.youtube",
    "youtu.be": "1_SFW.SOCIAL_MEDIA.youtube",

    # ── 2_NSFW_ADULT / ADULT_ANIME ──
    "hanime1.me": "2_NSFW_ADULT.ADULT_ANIME.hanime",
    "hanime.tv": "2_NSFW_ADULT.ADULT_ANIME.hanime",
    "hanime.red": "2_NSFW_ADULT.ADULT_ANIME.hanime_red",
    "hentaihaven.xxx": "2_NSFW_ADULT.ADULT_ANIME.hentaihaven",
    "hentaihaven.red": "2_NSFW_ADULT.ADULT_ANIME.hentaihaven",
    "hentaihaven.online": "2_NSFW_ADULT.ADULT_ANIME.hentaihaven",
    "hentaihaven.club": "2_NSFW_ADULT.ADULT_ANIME.hentaihaven",
    "hentaihaven.co": "2_NSFW_ADULT.ADULT_ANIME.hentaihaven_co",
    "hentaimama.io": "2_NSFW_ADULT.ADULT_ANIME.hentaimama",
    "hstream.moe": "2_NSFW_ADULT.ADULT_ANIME.hstream",
    "ohentai.org": "2_NSFW_ADULT.ADULT_ANIME.ohentai",
    "hentaicity.com": "2_NSFW_ADULT.ADULT_ANIME.hentaicity",
    "oppai.stream": "2_NSFW_ADULT.ADULT_ANIME.oppai_stream",

    # ── 2_NSFW_ADULT / ADULT_PORN ──
    "pornhub.com": "2_NSFW_ADULT.ADULT_PORN.pornhub",
    "phncdn.com": "2_NSFW_ADULT.ADULT_PORN.pornhub",

    # ── 2_NSFW_ADULT / Doujinshi ──
    "asmhentai.com": "2_NSFW_ADULT.Doujinshi.asmhentai",
    "nhentai.net": "2_NSFW_ADULT.Doujinshi.nhentai",

    # ── 2_NSFW_ADULT / ADULT_Webtoons ──
    "manhwaus.net": "2_NSFW_ADULT.ADULT_Webtoons.manhwaus",
    "omegascans.org": "2_NSFW_ADULT.ADULT_Webtoons.omegascans",
    "hentai20.io": "2_NSFW_ADULT.ADULT_Webtoons.hentai20",
    "manga18fx.com": "2_NSFW_ADULT.ADULT_Webtoons.manga18fx",
    "hentai18.net": "2_NSFW_ADULT.ADULT_Webtoons.hentai18",
    "read.oppai.stream": "2_NSFW_ADULT.ADULT_Webtoons.oppai_stream_toon",
}

# Dynamically add domains from scraper configs
SITE_MAP.update(domain_manager.get_dynamic_site_map())


def get_site_folder(url: str) -> Optional[str]:
    url_lower = url.lower()
    for domain in sorted(SITE_MAP.keys(), key=len, reverse=True):
        if domain in url_lower:
            return SITE_MAP[domain]
    return None
