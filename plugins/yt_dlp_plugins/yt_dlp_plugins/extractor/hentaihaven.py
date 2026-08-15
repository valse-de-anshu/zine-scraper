import base64

from yt_dlp.extractor.common import InfoExtractor, ExtractorError
from yt_dlp.utils import multipart_encode

class HentaiHavenIE(InfoExtractor):
    _VALID_URL = r'https?://hentaihaven\.(?:com/video|xxx/watch)/(?P<id>[^?#]+)'
    _CIPHER_MAP = bytes.maketrans(b'NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm',
                                  b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')

    def _decipher_sec_token(self, s):
        b = s.encode('ascii')
        for _ in range(3):
            b = b.translate(self._CIPHER_MAP)
            b = base64.b64decode(b)
        return b.decode('ascii')

    def _real_extract(self, url):
        video_id = self._match_id(url)

        page = self._download_webpage(url, video_id)
        video_title = self._html_search_regex(r'<title>([^<]+)</title>', page, 'title')
        embed_url = self._search_regex(r'([^"]+/wp-content/plugins/player-logic/player\.php[^"]+)' , page, 'embed')

        real_page = self._download_webpage(embed_url, video_id)
        cipher_text = self._html_search_meta('x-secure-token', real_page).lstrip('sha512-')
        interim = self._parse_json(self._decipher_sec_token(cipher_text), video_id)
        raw_payload, mime = multipart_encode({
            'action': 'zarat_get_data_player_ajax',
            'a': interim['en'],
            'b': interim['iv']
        })
        
        result = self._download_json(f"{interim['uri']}/api.php", video_id,
                                     headers={'Content-Type': mime},
                                     data=raw_payload)

        if not result['status']:
            raise ExtractorError("Unable to extract JWPlayer data",
                                 video_id=video_id, ie=HentaiHavenIE.ie_key())

        # HLS manifest is expected to be present in the 'file', however in this case it's inside 'src' key.
        for src in result['data']['sources']:
            src['file'] = src.pop('src')

        result = self._parse_jwplayer_data(result['data'], video_id, require_title=False)
        result['title'] = video_title

        return result

