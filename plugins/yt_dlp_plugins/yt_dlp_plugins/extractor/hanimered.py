import re
import json
import time
import base64
import hashlib

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import js_to_json

LANG_PATTERNS = [
    ('en', 'English', [r'english', r'\beng\b', r'\ben\b', r'_eng?\.', r'\.eng?\.', r'\[eng?\]']),
    ('es', 'Spanish', [r'spanish', r'espanol', r'español', r'\bspa\b', r'\bes\b', r'_spa?\.', r'\.spa?\.', r'\[spa?\]']),
    ('fr', 'French', [r'french', r'francais', r'français', r'\bfre\b', r'\bfr\b', r'\bfra\b']),
    ('de', 'German', [r'german', r'deutsch', r'\bger\b', r'\bdeu\b', r'\bde\b']),
    ('pt', 'Portuguese', [r'portuguese', r'portugues', r'português', r'\bpor\b', r'\bpt\b']),
    ('it', 'Italian', [r'italian', r'italiano', r'\bita\b', r'\bit\b']),
    ('ja', 'Japanese', [r'japanese', r'nihongo', r'\bjpn\b', r'\bja\b', r'\bjp\b']),
    ('zh', 'Chinese', [r'chinese', r'mandarin', r'\bchi\b', r'\bzho\b', r'\bzh\b']),
    ('ru', 'Russian', [r'russian', r'\brus\b', r'\bru\b']),
    ('ko', 'Korean', [r'korean', r'\bkor\b', r'\bko\b']),
    ('ar', 'Arabic', [r'arabic', r'\bara\b', r'\bar\b']),
    ('id', 'Indonesian', [r'indonesian', r'bahasa', r'\bind\b', r'\bid\b']),
]

def detect_subtitle_lang(text):
    t = text.lower()
    for code, name, patterns in LANG_PATTERNS:
        for p in patterns:
            if re.search(p, t):
                return code, name
    return 'und', 'Available'


class HanimeRedIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?hanime\.red/(?!serie(?:s)?/|tags-page/|hentai/|login-page/|register-page/)(?P<id>[0-9a-z\-]+)/?$'

    @staticmethod
    def _proof_of_work(s):
        def sha256(d: bytes):
            h = hashlib.sha256()
            h.update(d)
            return h.digest()

        for n in range(10000000):
            h = sha256(f'{s}{n:x}'.encode('utf-8'))
            if h[0] == 0 and h[1] == 0:
                return format(n, 'x')

    @staticmethod
    def _generate_fingerprint(ts):
        return base64.b64encode(json.dumps({
            't': ts, 'mm': [], 'tm': [], 'cl': [], 'kp': [], 'sc': [], 'i': 0, 'mc': 0, 'tc': 0, 'cc': 0, 'kc': 0,
            'b': {
                'sw': 1920, 'sh': 1080, 'aw': 1920, 'ah': 1080, 'cd': 24, 'pd': 24, 'tz': 0, 'hc': 8, 'dm': 8,
                'pl': '', 'lang': 'en', 'langs': 'en', 'dpr': 1, 'ww': 1920, 'wh': 1080, 'touch': False,
                'pdf': True, 'fonts': 1
            }
        }).encode('utf-8')).decode('ascii')

    def _real_extract(self, url):
        video_id = self._match_id(url)
        page = self._download_webpage(url, video_id)
        title = self._html_search_regex(
            (r'<h1[^>]*>([^<]+)</h1>', r'<title>([^<]+)</title>'),
            page, 'Video Title', default=video_id
        )
        player_url = self._search_regex(r'<iframe src="([^"]+)"', page, 'Player Wrapper URL')
        player_page = self._download_webpage(player_url, video_id)
        real_player_url = self._search_regex(r'li data-id="([^"]+)"', player_page, 'Player URL')
        real_player_page = self._download_webpage(f'https://nhplayer.com/{real_player_url}', video_id)
        pv = self._search_json(r'window._pV=', real_player_page, 'Player Parameters', video_id,
                                transform_source=js_to_json)
        player_script_url = self._search_regex(r'script src="(player-core[^"]+)"', real_player_page, 'Player Script URL')
        player_script = self._download_webpage(f'https://nhplayer.com/{player_script_url}', video_id)
        epoch_ts = time.monotonic_ns() // 1000000
        server_tokens = self._search_regex(
            r"//.+challenge token.+\n"
            r"?var \w+='([^']+)';\n"
            r"?var \w+='([^']+)';\n", player_script, 'Challenge Tokens')
        selectors = re.findall(r"d.getElementById\('(x[0-9a-f]+)'\)", player_script)
        patterns = (
            r'<span id="{}" data-[0-9a-f]{{4}}="([^"]+)"',
            r'<input type="hidden" id="{}" value="([^"]+)"',
            r'<div id="{}" data-[0-9a-f]{{4}}="([^"]+)"',
            r'<template id="{}"><p>([^<]+)',
            r'<span id="{}" data-[0-9a-f]{{4}}="([^"]+)"'
        )
        challenge_parts = [self._search_regex(p.format(s), real_player_page, f'Challenge Part #{i}')
            for i, (s, p) in enumerate(zip(selectors, patterns))]
        computed_pow = self._proof_of_work(''.join(challenge_parts))
        fp = self._generate_fingerprint(epoch_ts + 2100)
        response = self._download_json('https://nhplayer.com/get-video-url-v2.php', video_id,
            query={                             
                'vid': pv['vid'],
                'c': pv['ct'],
                'p1': challenge_parts[0],
                'p2': challenge_parts[1],
                'p3': challenge_parts[2],
                'p4': challenge_parts[3],
                't': challenge_parts[4],
                'sc': server_tokens[0],
                'rid': server_tokens[1],
                'fp': fp,
                'df': [],
                'pow': computed_pow,
                'pid': pv['pid'],
                'st': pv['st']
            },
            headers={'X-Requested-With': 'XMLHttpRequest'})

        # Extract all available subtitles, prioritizing English with fallback to any available language
        subtitles = {}
        seen_sub_urls = set()

        def add_sub_entry(candidate_url, label_hint=''):
            if not candidate_url or candidate_url in seen_sub_urls:
                return
            if not ('.srt' in candidate_url.lower() or '.vtt' in candidate_url.lower()):
                return
            seen_sub_urls.add(candidate_url)
            lang_code, lang_name = detect_subtitle_lang(f'{label_hint} {candidate_url}')
            ext = 'vtt' if '.vtt' in candidate_url.lower() else 'srt'
            subtitles.setdefault(lang_code, []).append({
                'url': candidate_url,
                'ext': ext,
                'name': lang_name,
            })

        s_match = re.search(r'[?&]s=([a-zA-Z0-9+/=]+)', real_player_url)
        if s_match:
            try:
                decoded = base64.b64decode(s_match.group(1)).decode('utf-8', errors='ignore')
                if decoded.startswith('http'):
                    add_sub_entry(decoded, 'Main Player')
            except Exception:
                pass

        for tm in re.finditer(r'\{[^{}]*file\s*:\s*"([^"]+\.(?:srt|vtt)[^"]*)"[^{}]*\}', real_player_page):
            block = tm.group(0)
            sub_f = tm.group(1).replace(r'\/', '/')
            lbl_m = re.search(r'label\s*:\s*"([^"]+)"', block)
            lbl = lbl_m.group(1) if lbl_m else ''
            add_sub_entry(sub_f, lbl)

        return {
            'id': video_id,
            'title': title,
            'url': response.get('url'),
            'ext': 'mp4',
            'subtitles': subtitles,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://nhplayer.com/',
                'Origin': 'https://nhplayer.com',
            }
        }
