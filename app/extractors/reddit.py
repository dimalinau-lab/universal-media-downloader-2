import re
import json
import logging
import requests
from .base import BaseExtractor

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'


class RedditExtractor(BaseExtractor):
    name = "Reddit Video"
    platform_id = "reddit"

    @classmethod
    def can_handle(cls, url: str) -> bool:
        u = url.lower()
        return 'reddit.com' in u or 'v.redd.it' in u

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) UniversalDownloader/3.2',
            'Accept': 'application/json, text/html',
        }

    def fetch_metadata(self, url: str) -> dict:
        logger.info(f"[Reddit] Запрос метаданных для {url}...")
        clean_url = url.split('?')[0].rstrip('/')
        json_url = f"{clean_url}.json"

        resp = self.session.get(json_url, headers=self.headers, timeout=10)
        data = resp.json()

        post_data = data[0]['data']['children'][0]['data']
        title = post_data.get('title', 'Reddit Video')
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
        thumbnail = post_data.get('thumbnail')
        if thumbnail and not thumbnail.startswith('http'):
            thumbnail = None

        media = post_data.get('secure_media') or post_data.get('media') or {}
        reddit_video = media.get('reddit_video') or {}

        # HLS плейлист содержит объединенное видео и аудиодорожку без рассинхрона
        hls_url = reddit_video.get('hls_url')
        fallback_url = reddit_video.get('fallback_url')
        height = reddit_video.get('height', 720)
        quality = f"{height}p"

        best_stream = hls_url or fallback_url or url

        return {
            'url': url,
            'safe_anime_title': safe_title,
            'poster_url': thumbnail,
            'direct_url': best_stream,
            'quality': quality,
            'is_movie': True,
            'seasons': [{'name': '1', 'id': '1'}],
            'voiceovers': [{'name': 'Оригинал', 'id': 'default'}],
            'episodes': [{'name': safe_title, 'id': '1', 'season_id': '1'}]
        }

    def resolve_stream(self, episode_data: dict, quality: str = "720p") -> tuple[str, str]:
        direct = episode_data.get('direct_url')
        return direct or episode_data.get('url'), quality
