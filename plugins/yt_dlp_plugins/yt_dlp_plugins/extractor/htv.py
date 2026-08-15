import json
import subprocess

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import str_or_none, int_or_none, ExtractorError
# TODO Allow any runtime not just Deno.
from yt_dlp.utils._jsruntime import DenoJsRuntime

class HanimeTVIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?hanime\.tv/(videos/hentai|hentai/video)/(?P<id>[a-z0-9\-]+)'
    _JS_PREAMBLE = '''
    delete globalThis.process;

    var window = new Proxy({
        top: { location: { origin: "https://hanime.tv" } },
        addEventListener: (e, cb) => {},
        dispatchEvent: () => {}
    }, {
        set(o, k, v) {
            if (k == "ssignature" || k == "stime")
                console.log(k, v);
            
            o[k] = v;
            return true;
        }
    });

    globalThis.window = window;
    '''
    
    # TODO add _TESTS

    def __init__(self):
        self._runtime = DenoJsRuntime()

        if not self._runtime.info:
            raise ExtractorError("DenoJS is required for hanime.tv extractor")
        
        self._script = None

    def _cache_credential_generator(self, url, video_id):
        self._script = self._JS_PREAMBLE
        self._script += self._download_webpage(url, video_id,
            headers={'Referer': 'https://hanime.tv/'}, note='Caching generator script')

    def _generate_credentials(self):
        output = subprocess.run([self._runtime.info.path, 'run', '-'],
            input=self._script, encoding='utf-8', text=True, capture_output=True)

        if output.returncode == 0:
            creds = dict(line.split(' ', 1)
                for line in output.stdout.split('\n', 1))

            return creds.get('ssignature'), creds.get('stime')
        else:
            raise ExtractorError("Signature and timestamp generation failed")

    def _js_to_json(self, meta):
        output = subprocess.run([self._runtime.info.path, 'run', '-'],
                                input=f"console.log(JSON.stringify({meta}.state.data.video.hentai_video))",
                                encoding='utf-8', text=True, capture_output=True)

        if output.returncode == 0:
            return json.loads(output.stdout)
        else:
            raise ExtractorError("Metadata extraction failed")

    def _real_extract(self, url):
        video_id = self._match_id(url)
        page = self._download_webpage(url, video_id)

        # Extract video ID from Astro props instead of Nuxt state
        if not self._script:
            script_url = self._search_regex( 
                r'<script.*src="(https://hanime-cdn\.com/js/vendor\.[^"]+)', page, "signature generator"
            )
            self._cache_credential_generator(script_url, video_id)

        # Astro (new)
        astro_props = self._search_regex(r'props="({.*?&quot;video_id&quot;:.*?})"', page, "astro props")
        import html
        import json
        astro_props = html.unescape(astro_props)
        # The props are in a custom JSON-like format where values are [type, value] arrays
        props_json = self._parse_json(astro_props, video_id)
        real_video_id = props_json.get('video_id', [0, None])[1]
        video_name = props_json.get('video_name', [0, None])[1]

        ssignature, stime = self._generate_credentials()
        # self.to_screen(f'Signature: {ssignature}')

        manifest = self._download_json(
            f"https://h.freeanimehentai.net/api/v8/guest/videos/{real_video_id}/manifest",
            video_id, headers={
                'Accept': 'application/json',
                'Origin': 'https://hanime.tv',
                'Referer': 'https://hanime.tv/',
                'X-Signature': ssignature,
                'X-Time': stime,
                'X-Signature-Version': 'web2'
            }
        )

        formats = []

        for server in manifest['videos_manifest']['servers']:
            for stream in server['streams']:
                formats.append({
                    'url': stream['url'],
                    'ext': 'mp4',
                    'format_id': str_or_none(stream['id']),
                    'width': int_or_none(stream.get('width')),
                    'height': int_or_none(stream.get('height')),
                    'filesize_approx': int_or_none(stream.get('filesize_mbs'), invscale=1000000),
                })
        
        return {
            'id': video_id,
            'title': video_name,
            'formats': formats
        }
