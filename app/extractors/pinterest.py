import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from .base import BaseExtractor

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'


class PinterestExtractor(BaseExtractor):
    name = "Pinterest"
    platform_id = "pinterest"

    @classmethod
    def can_handle(cls, url: str) -> bool:
        u = url.lower()
        return 'pinterest.' in u or 'pin.it' in u

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {
            'User-Agent': BROWSER_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }

    def fetch_metadata(self, url: str) -> dict:
        logger.info(f"[Pinterest] Разрешение ссылки {url}...")
        resp = self.session.get(url, headers=self.headers, allow_redirects=True, timeout=10)
        final_url = resp.url
        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')

        # Заголовок
        title_el = soup.select_one('meta[property="og:title"], title')
        title = title_el.get('content') if title_el and title_el.name == 'meta' else (title_el.text if title_el else "Pinterest Video")
        title = re.sub(r'[\r\n\t]+', ' ', title).strip()
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title)

        # Превью
        poster_el = soup.select_one('meta[property="og:image"], meta[name="og:image"]')
        poster_url = poster_el.get('content') if poster_el else None

        # Прямое видео (og:video) или v.pinimg.com
        video_url = None
        video_el = soup.select_one('meta[property="og:video"], meta[name="og:video:secure_url"]')
        if video_el:
            video_url = video_el.get('content')

        if not video_url:
            # Поиск в JSON-LD
            for script in soup.select('script[type="application/ld+json"]'):
                try:
                    data = json.loads(script.text)
                    if isinstance(data, dict):
                        content_url = data.get('contentUrl') or data.get('embedUrl')
                        if content_url and ('.mp4' in content_url or '.m3u8' in content_url):
                            video_url = content_url
                            break
                except Exception:
                    pass

        if not video_url:
            # Regex поиск по v.pinimg.com
            m = re.search(r'(https?://v\.pinimg\.com/videos/[^\s"\'<>]+\.mp4)', html)
            if m:
                video_url = m.group(1)

        quality = "1080p" if video_url and "720p" not in video_url else "720p"

        return {
            'url': final_url,
            'safe_anime_title': safe_title,
            'poster_url': poster_url,
            'direct_url': video_url,
            'quality': quality,
            'is_movie': True,
            'seasons': [{'name': '1', 'id': '1'}],
            'voiceovers': [{'name': 'Оригинал', 'id': 'default'}],
            'episodes': [{'name': safe_title, 'id': '1', 'season_id': '1'}]
        }

    def resolve_stream(self, episode_data: dict, quality: str = "1080p") -> tuple[str, str]:
        direct = episode_data.get('direct_url')
        return direct or episode_data.get('url'), quality
