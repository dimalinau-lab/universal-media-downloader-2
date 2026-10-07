import re
import json
import base64
import logging
import requests
from bs4 import BeautifulSoup

from .base import BaseExtractor

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'


def rot18_decode(text: str) -> str:
    """
    Деобфускация ссылок плеера Kodik (ROT-18 + Base64 с авто-паддингом).
    """
    def rot18_char(c):
        if 'a' <= c <= 'z':
            val = ord(c) + 18
            return chr(val if val <= 122 else val - 26)
        elif 'A' <= c <= 'Z':
            val = ord(c) + 18
            return chr(val if val <= 90 else val - 26)
        return c

    shifted = ''.join(rot18_char(c) for c in text)
    shifted += '=' * ((4 - len(shifted) % 4) % 4)
    try:
        return base64.b64decode(shifted).decode('utf-8', errors='ignore')
    except Exception:
        return ""


class AnimeGoExtractor(BaseExtractor):
    name = "AnimeGo & Kodik"
    platform_id = "animego"

    @classmethod
    def can_handle(cls, url: str) -> bool:
        u = url.lower()
        return any(d in u for d in ['animego.', 'aniboom.', 'kodik.info', 'kodik.biz', 'kodik.cc', 'kodikplayer.'])

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {
            'User-Agent': BROWSER_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        }

    def fetch_metadata(self, url: str) -> dict:
        """
        Парсит страницу AnimeGo или плеер Kodik / AniBoom.
        """
        logger.info(f"[AnimeGo] Запрос метаданных для {url}...")
        resp = self.session.get(url, headers=self.headers, timeout=12)
        if resp.status_code != 200:
            raise RuntimeError(f"Сайт AnimeGo вернул HTTP {resp.status_code}")

        resp.encoding = 'utf-8'
        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')

        # 1. Название аниме
        meta_title = soup.select_one('meta[property="og:title"]')
        raw_title = meta_title.get('content', '') if meta_title else ''
        if not raw_title:
            h1 = soup.select_one('h1')
            raw_title = h1.text.strip() if h1 else "Аниме"

        title = re.sub(r'\s*смотреть онлайн.*', '', raw_title, flags=re.I).strip()
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip() or "Anime"

        # 2. Постер
        poster_url = None
        poster_el = soup.select_one('meta[property="og:image"], .anime-poster img')
        if poster_el:
            poster_url = poster_el.get('content') if poster_el.name == 'meta' else poster_el.get('src')
            if poster_url and poster_url.startswith('//'):
                poster_url = f"https:{poster_url}"

        # 3. ID аниме
        anime_id_m = re.search(r'-(\d+)(?:[/?#]|$)', url)
        anime_id = anime_id_m.group(1) if anime_id_m else None

        voiceovers = []
        episodes = []
        seasons = [{'name': '1 Сезон', 'id': '1'}]

        if anime_id:
            # Получение озвучек и плееров через внутренний AJAX API AnimeGo
            try:
                p_url = f"https://animego.me/player/{anime_id}"
                p_resp = self.session.get(
                    p_url,
                    headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': url},
                    timeout=10
                )
                if p_resp.status_code == 200:
                    p_data = p_resp.json()
                    p_content = p_data.get('data', {}).get('content', '')
                    p_soup = BeautifulSoup(p_content, 'html.parser')

                    for b in p_soup.select('button[data-player]'):
                        v_name = b.get('data-translation-title') or b.text.strip()
                        v_id = b.get('data-translation-id') or b.get('data-ptranslation') or v_name
                        p_link = b.get('data-player', '')
                        if p_link.startswith('//'):
                            p_link = 'https:' + p_link
                        provider = b.get('data-provider-slug', '')
                        if not provider:
                            provider = 'kodik' if 'kodik' in p_link else ('aniboom' if 'aniboom' in p_link else 'direct')

                        existing = next((v for v in voiceovers if v['id'] == str(v_id) or v['name'] == v_name), None)
                        if existing:
                            if 'alt_players' not in existing:
                                existing['alt_players'] = [{'player_url': existing['player_url'], 'provider': existing.get('provider', '')}]
                            if not any(a['player_url'] == p_link for a in existing['alt_players']):
                                existing['alt_players'].append({'player_url': p_link, 'provider': provider})
                        elif v_name:
                            voiceovers.append({
                                'name': v_name,
                                'id': str(v_id),
                                'player_url': p_link,
                                'provider': provider,
                                'alt_players': [{'player_url': p_link, 'provider': provider}]
                            })
            except Exception as e:
                logger.warning(f"[AnimeGo] Не удалось получить плееры через API: {e}")

            # Получение списка серий
            try:
                ep_url = f"https://animego.me/player/{anime_id}/episodes"
                ep_resp = self.session.get(
                    ep_url,
                    headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': url},
                    timeout=10
                )
                if ep_resp.status_code == 200:
                    ep_data = ep_resp.json()
                    ep_content = ep_data.get('data', {}).get('content', '')
                    ep_soup = BeautifulSoup(ep_content, 'html.parser')

                    for el in ep_soup.select('.player-video-bar__item'):
                        ep_num = el.get('data-episode-number')
                        ep_id = el.get('data-episode')
                        if ep_num:
                            episodes.append({
                                'name': f'Серия {ep_num}',
                                'id': str(ep_id or ep_num),
                                'season_id': '1',
                                'episode_number': int(ep_num)
                            })
            except Exception as e:
                logger.warning(f"[AnimeGo] Не удалось получить серии через API: {e}")

        # Fallback озвучки
        if not voiceovers:
            voiceovers = [{'name': 'Оригинал / Стандартная', 'id': 'default', 'player_url': url, 'provider': 'direct'}]

        if not episodes:
            episodes = [{'name': 'Серия 1', 'id': '1', 'season_id': '1', 'episode_number': 1}]

        available_qualities = ["1080p", "720p", "480p", "360p"]

        return {
            'url': url,
            'anime_id': anime_id,
            'safe_anime_title': safe_title,
            'poster_url': poster_url,
            'voiceovers': voiceovers,
            'seasons': seasons,
            'episodes': episodes,
            'is_movie': len(episodes) <= 1 and len(voiceovers) <= 1,
            'available_qualities': available_qualities,
            'referer': 'https://aniboom.one/',
        }

    def _resolve_kodik(self, kodik_url: str, requested_quality: str = "720p") -> tuple[str, str]:
        """
        Извлекает прямую ссылку из плеера Kodik (solodcdn.com MP4 или HLS).
        """
        try:
            r = self.session.get(kodik_url, headers={'Referer': 'https://animego.me/'}, timeout=10)
            html = r.text

            def get_var(name):
                m = re.search(r'var\s+' + name + r'\s*=\s*["\']([^"\']+)["\']', html)
                return m.group(1) if m else ''

            domain = get_var('domain') or 'animego.me'
            d_sign = get_var('d_sign')
            pd = get_var('pd') or 'kodikplayer.com'
            pd_sign = get_var('pd_sign')
            ref = get_var('ref') or 'https://animego.me/'
            ref_sign = get_var('ref_sign')

            u_match = re.search(r'/(serial|seria|video)/(\d+)/([a-f0-9]+)/', kodik_url)
            if not u_match:
                return "", requested_quality
            v_type, v_id, v_hash = u_match.group(1), u_match.group(2), u_match.group(3)

            post_data = {
                'd': domain,
                'd_sign': d_sign,
                'pd': pd,
                'pd_sign': pd_sign,
                'ref': ref,
                'ref_sign': ref_sign,
                'bad_user': 'false',
                'cdn_is_working': 'true',
                'type': v_type,
                'hash': v_hash,
                'id': v_id
            }

            post_headers = {
                'User-Agent': self.headers['User-Agent'],
                'Referer': kodik_url,
                'Origin': 'https://kodikplayer.com',
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01'
            }

            ftor_r = self.session.post('https://kodikplayer.com/ftor', data=post_data, headers=post_headers, timeout=10)
            if ftor_r.status_code != 200:
                logger.warning(f"[Kodik] Ответ /ftor вернул статус {ftor_r.status_code}")
                return "", requested_quality

            res = ftor_r.json()
            links = res.get('links', {})
            if not links:
                return "", requested_quality

            target_num = 720
            q_m = re.search(r'(\d+)', requested_quality)
            if q_m:
                target_num = int(q_m.group(1))

            avail = []
            for k in links:
                try:
                    avail.append((int(k), k))
                except Exception:
                    pass
            avail.sort(key=lambda x: x[0], reverse=True)

            chosen_key = str(avail[0][0]) if avail else list(links.keys())[0]
            for num, k in avail:
                if num <= target_num:
                    chosen_key = k
                    break

            items = links[chosen_key]
            raw_src = items[0].get('src', '')
            if raw_src.startswith('//'):
                real_url = 'https:' + raw_src
            else:
                real_url = rot18_decode(raw_src)
                if real_url.startswith('//'):
                    real_url = 'https:' + real_url

            # В Kodik за :hls:manifest.m3u8 всегда лежит прямой оригинальный MP4 файл (solodcdn.com/useruploads/.../720.mp4)
            # Прямой MP4 скачивается намного быстрее и без сборки фрагментов
            if ':hls:manifest.m3u8' in real_url:
                direct_mp4 = real_url.replace(':hls:manifest.m3u8', '')
                try:
                    head_check = self.session.head(direct_mp4, headers={'Referer': 'https://kodikplayer.com/'}, timeout=3)
                    if head_check.status_code == 200:
                        real_url = direct_mp4
                except Exception:
                    pass

            logger.info(f"[Kodik] [+] Успешно получен поток Kodik ({chosen_key}p): {real_url}")
            return real_url, f"{chosen_key}p"
        except Exception as e:
            logger.error(f"[Kodik] Сбой извлечения видеопотока: {e}")
            return "", requested_quality

    def resolve_stream(self, episode_data: dict, quality: str = "1080p") -> tuple[str, str]:
        """
        Извлекает прямую ссылку на видеопоток для серии и озвучки.
        Поддерживает оба типа плееров:
          1. Kodik (solodcdn.com: прямой MP4 или HLS манифест)
          2. AniBoom (ya-ligh123.site / poppy / sophia master.m3u8 с m4s чанками)
        """
        selected_v = episode_data.get('selected_voiceover')
        player_url = None
        provider = ""
        if selected_v and isinstance(selected_v, dict):
            player_url = selected_v.get('player_url')
            provider = selected_v.get('provider', '')

        ep_num = episode_data.get('episode_number', 1)
        ep_id = episode_data.get('id')
        anime_page_url = episode_data.get('url', 'https://animego.me/')

        # 1. Если указан ID серии (data-episode), запрашиваем актуальные плееры для этой серии через /player/videos/{ep_id}
        if ep_id and str(ep_id).isdigit():
            try:
                ep_video_url = f"https://animego.me/player/videos/{ep_id}"
                ep_resp = self.session.get(
                    ep_video_url,
                    headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': anime_page_url},
                    timeout=8
                )
                if ep_resp.status_code == 200:
                    ep_content = ep_resp.json().get('data', {}).get('content', '')
                    ep_soup = BeautifulSoup(ep_content, 'html.parser')
                    buttons = ep_soup.select('button[data-player]')
                    if buttons:
                        matched_btn = None
                        if selected_v:
                            sv_name = (selected_v.get('name') or '').lower()
                            sv_id = str(selected_v.get('id') or '')
                            for b in buttons:
                                b_title = (b.get('data-translation-title') or b.text.strip()).lower()
                                b_tr_id = str(b.get('data-translation-id') or b.get('data-ptranslation') or '')
                                if (sv_id and b_tr_id == sv_id) or (sv_name and (sv_name in b_title or b_title in sv_name)):
                                    matched_btn = b
                                    break
                        if not matched_btn:
                            matched_btn = buttons[0]

                        p_link = matched_btn.get('data-player', '')
                        if p_link.startswith('//'):
                            p_link = 'https:' + p_link
                        p_provider = matched_btn.get('data-provider-slug', '')
                        if p_link:
                            player_url = p_link
                            provider = p_provider or ('kodik' if 'kodik' in p_link else 'aniboom')
            except Exception as e:
                logger.debug(f"[AnimeGo] Не удалось запросить плееры для серии {ep_id}: {e}")

        if not player_url:
            voiceovers = episode_data.get('voiceovers', [])
            for v in voiceovers:
                if v.get('provider') == 'aniboom' or 'aniboom' in v.get('player_url', ''):
                    player_url = v.get('player_url')
                    provider = 'aniboom'
                    break
            if not player_url and voiceovers:
                player_url = voiceovers[0].get('player_url')
                provider = voiceovers[0].get('provider', '')

        if not player_url:
            player_url = episode_data.get('url', '')

        # Собираем список кандидатов для выбранной озвучки (и AniBoom, и Kodik)
        candidates = []
        if player_url:
            candidates.append({'url': player_url, 'provider': provider})

        if selected_v and isinstance(selected_v, dict):
            for alt in selected_v.get('alt_players', []):
                a_url = alt.get('player_url')
                a_prov = alt.get('provider', '')
                if a_url and not any(c['url'] == a_url for c in candidates):
                    candidates.append({'url': a_url, 'provider': a_prov})

        for cand in candidates:
            c_url = cand['url']
            c_prov = cand.get('provider', '')

            # 1. Попытка через Kodik
            if 'kodik' in c_url or c_prov == 'kodik':
                logger.info(f"[AnimeGo] Запрос потока Kodik: {c_url}...")
                stream_url, q_badge = self._resolve_kodik(c_url, quality)
                if stream_url:
                    return stream_url, q_badge

            # 2. Попытка через AniBoom
            if 'aniboom.one' in c_url or c_prov == 'aniboom':
                target_url = re.sub(r'episode=\d+', f'episode={ep_num}', c_url)
                logger.info(f"[AnimeGo] Запрос потока AniBoom: {target_url}...")
                try:
                    resp = self.session.get(target_url, headers={'Referer': 'https://animego.me/'}, timeout=10)
                    if resp.status_code == 200:
                        param_m = re.search(r'data-parameters=[\'"]([^\'"]+)[\'"]', resp.text)
                        if param_m:
                            raw_p = param_m.group(1).replace('&quot;', '"')
                            p_json = json.loads(raw_p)
                            hls_raw = p_json.get('hls') or p_json.get('fallbackHls')
                            hls_obj = json.loads(hls_raw) if isinstance(hls_raw, str) else (hls_raw or {})
                            stream_url = hls_obj.get('src')
                            if stream_url:
                                logger.info(f"[AnimeGo] [+] Успешно получен HLS поток AniBoom: {stream_url}")
                                return stream_url, quality
                    elif resp.status_code == 404:
                        logger.warning(f"[AnimeGo] Плеер AniBoom вернул 404 (Серия {ep_num} еще не загружена в AniBoom для этой озвучки)")
                except Exception as e:
                    logger.warning(f"[AnimeGo] Ошибка парсинга параметров AniBoom: {e}")

        # 3. Резервный поиск по другим доступным плеерам
        for v in episode_data.get('voiceovers', []):
            for alt in v.get('alt_players', [{'player_url': v.get('player_url'), 'provider': v.get('provider')}]) :
                a_url = alt.get('player_url', '')
                a_prov = alt.get('provider', '')
                if 'kodik' in a_url or a_prov == 'kodik':
                    s_url, q_b = self._resolve_kodik(a_url, quality)
                    if s_url:
                        logger.info(f"[AnimeGo] [+] Найден резервный поток Kodik ({v.get('name')}): {s_url}")
                        return s_url, q_b
                elif 'aniboom.one' in a_url or a_prov == 'aniboom':
                    alt_target = re.sub(r'episode=\d+', f'episode={ep_num}', a_url)
                    try:
                        resp = self.session.get(alt_target, headers={'Referer': 'https://animego.me/'}, timeout=10)
                        if resp.status_code == 200:
                            param_m = re.search(r'data-parameters=[\'"]([^\'"]+)[\'"]', resp.text)
                            if param_m:
                                raw_p = param_m.group(1).replace('&quot;', '"')
                                p_json = json.loads(raw_p)
                                hls_raw = p_json.get('hls') or p_json.get('fallbackHls')
                                hls_obj = json.loads(hls_raw) if isinstance(hls_raw, str) else (hls_raw or {})
                                s_url = hls_obj.get('src')
                                if s_url:
                                    logger.info(f"[AnimeGo] [+] Резервный поток AniBoom ({v.get('name')}): {s_url}")
                                    return s_url, quality
                    except Exception:
                        pass

        v_label = selected_v.get('name') if selected_v else 'выбранной'
        logger.warning(f"[AnimeGo] Серия {ep_num} в озвучке '{v_label}' недоступна. Попробуйте выбрать другую озвучку (например, AniStar или AniDUB).")
        return "", quality
