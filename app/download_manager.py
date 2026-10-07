import os
import sys
import json
import base64
import logging
import re
import time
import subprocess
import requests
import tempfile
import zipfile
import urllib.parse
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from PyQt6.QtCore import QObject, pyqtSignal, Qt, QRunnable
from PyQt6.QtWidgets import QApplication, QMessageBox

from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By

import threading
from .threads import InfoWorker, DownloadWorker, ThumbnailWorker
from .download_task import DownloadTask
from .episode_dialog import EpisodeSelectionDialog
from .kinopub_dialog import KinoPubScanDialog, KinoPubSeriesProgressDialog, format_kinopub_error
from .extractors import find_extractor_for_url

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'



def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def purge_profile_proxies(profile_dir: str):
    """
    Проверяет и очищает конфигурацию профиля браузера от ранее сохраненных прокси-расширений
    и настроек прокси, чтобы предотвратить появление ERR_SOCKS_CONNECTION_FAILED.
    """
    if not profile_dir or not os.path.isdir(profile_dir):
        return
    import json
    for pref_filename in ['Secure Preferences', 'Preferences']:
        pref_path = os.path.join(profile_dir, 'Default', pref_filename)
        if not os.path.isfile(pref_path):
            continue
        try:
            with open(pref_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
            modified = False
            exts = data.get('extensions', {}).get('settings', {})
            if isinstance(exts, dict):
                to_delete = []
                for ext_id, ext_info in exts.items():
                    info_str = json.dumps(ext_info)
                    if 'socks' in info_str.lower() or 'proxy' in info_str.lower():
                        to_delete.append(ext_id)
                for ext_id in to_delete:
                    del exts[ext_id]
                    modified = True
                    logger.info(f"Удалено устаревшее прокси-расширение '{ext_id}' из {pref_filename}")
            if modified:
                with open(pref_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"Не удалось проверить/очистить {pref_filename}: {e}")


def configure_selenium_direct(options):
    """
    Принудительно настраивает прямой режим соединения для Selenium Edge / Chrome без использования прокси.
    """
    options.add_argument('--disable-extensions')
    options.add_argument('--no-proxy-server')
    options.add_argument('--proxy-server=direct://')
    options.add_argument('--proxy-bypass-list=*')


def create_browser_driver(headless: bool = True, user_agent: str = BROWSER_USER_AGENT, use_profile: bool = True):
    """
    Создает экземпляр WebDriver с интеллектуальным fallback:
    1. Microsoft Edge (с профилем или без)
    2. Google Chrome (с профилем или без)
    """
    profile_dir = os.path.join(get_base_dir(), 'browser_profile')
    if use_profile:
        os.makedirs(profile_dir, exist_ok=True)
        purge_profile_proxies(profile_dir)

    # 1. Попытка запустить Microsoft Edge
    try:
        edge_service = EdgeService()
        edge_service.creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        edge_options = EdgeOptions()
        if headless:
            edge_options.add_argument('--headless=new')
        edge_options.add_argument('--disable-gpu')
        edge_options.add_argument('--log-level=3')
        edge_options.add_argument(f'user-agent={user_agent}')
        configure_selenium_direct(edge_options)
        if use_profile:
            edge_options.add_argument(f"user-data-dir={profile_dir}")

        try:
            driver = webdriver.Edge(service=edge_service, options=edge_options)
            logger.info("[Browser] Успешно запущен Microsoft Edge WebDriver")
            return driver
        except Exception as edge_profile_err:
            if use_profile:
                logger.warning(f"[Browser] Сбой запуска Edge с профилем ({edge_profile_err}). Пробуем без профиля...")
                edge_options_np = EdgeOptions()
                if headless:
                    edge_options_np.add_argument('--headless=new')
                edge_options_np.add_argument('--disable-gpu')
                edge_options_np.add_argument('--log-level=3')
                edge_options_np.add_argument(f'user-agent={user_agent}')
                configure_selenium_direct(edge_options_np)
                driver = webdriver.Edge(service=edge_service, options=edge_options_np)
                logger.info("[Browser] Успешно запущен Microsoft Edge (без профиля)")
                return driver
            raise edge_profile_err
    except Exception as edge_err:
        logger.warning(f"[Browser] Microsoft Edge недоступен ({edge_err}). Пробуем Google Chrome...")

    # 2. Попытка запустить Google Chrome
    try:
        chrome_service = ChromeService()
        chrome_service.creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        chrome_options = ChromeOptions()
        if headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--log-level=3')
        chrome_options.add_argument(f'user-agent={user_agent}')
        configure_selenium_direct(chrome_options)
        if use_profile:
            chrome_options.add_argument(f"user-data-dir={profile_dir}")

        try:
            driver = webdriver.Chrome(service=chrome_service, options=chrome_options)
            logger.info("[Browser] Успешно запущен Google Chrome WebDriver")
            return driver
        except Exception as chrome_profile_err:
            if use_profile:
                logger.warning(f"[Browser] Сбой запуска Chrome с профилем ({chrome_profile_err}). Пробуем без профиля...")
                chrome_options_np = ChromeOptions()
                if headless:
                    chrome_options_np.add_argument('--headless=new')
                chrome_options_np.add_argument('--disable-gpu')
                chrome_options_np.add_argument('--log-level=3')
                chrome_options_np.add_argument(f'user-agent={user_agent}')
                configure_selenium_direct(chrome_options_np)
                driver = webdriver.Chrome(service=chrome_service, options=chrome_options_np)
                logger.info("[Browser] Успешно запущен Google Chrome (без профиля)")
                return driver
            raise chrome_profile_err
    except Exception as chrome_err:
        logger.error(f"[Browser] Google Chrome также недоступен: {chrome_err}")

    raise RuntimeError(
        "Не удалось инициализировать браузер для обхода защиты сайта.\n"
        "Убедитесь, что в системе установлен Microsoft Edge или Google Chrome."
    )


def try_direct_http_fetch(url: str, timeout: int = 8):
    """
    Быстрая попытка получить страницу кинотеатра напрямую через HTTP без запуска браузера.
    Если защита Cloudflare не блокирует прямой доступ, данные будут получены за 0.5-1 секунды.
    """
    try:
        session = requests.Session()
        session.trust_env = False
        headers = {
            'User-Agent': BROWSER_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Sec-Ch-Ua': '"Chromium";v="130", "Not?A_Brand";v="99"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        }
        resp = session.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            html = resp.text
            if ('translators-list' in html or 'ctrl_favs' in html or 'b-post__title' in html or 'post_id' in html) and len(html) > 1000:
                cookies = [{'name': c.name, 'value': c.value} for c in session.cookies]
                favs_m = re.search(r'id=["\']ctrl_favs["\'][^>]*value=["\']([^"\']+)["\']', html) or \
                         re.search(r'value=["\']([^"\']+)["\'][^>]*id=["\']ctrl_favs["\']', html)
                favs = favs_m.group(1) if favs_m else ""
                logger.info(f"[KinoPub] Успешный прямой HTTP запрос к {url} ({len(html)} байт, favs: {'есть' if favs else 'нет'})")
                return html, cookies, favs
    except Exception as e:
        logger.debug(f"[KinoPub] Прямой HTTP запрос не удался ({e}), переход к запуску браузера...")
    return None, None, None




AD_AND_SPAM_PATTERNS = [
    r'adfox\.',
    r'adriver\.',
    r'an\.yandex\.',
    r'mc\.yandex\.',
    r'doubleclick\.',
    r'googlesyndication\.',
    r'google-analytics\.',
    r'mail\.ru',
    r'top100\.',
    r'1xbet\.',
    r'melbet\.',
    r'fonbet\.',
    r'vavada\.',
    r'casino',
    r'pin-up\.',
    r'betwinner\.',
    r'mostbet\.',
    r'popunder',
    r'clickunder',
    r'teaser',
    r'banner',
    r'prem\.svg',
    r'pjs-prem',
    r'promo_30s',
    r'qr_promo',
    r'advert',
    r'tracker',
    r'pixel',
    r'counter',
    r'beacon',
]

NON_VIDEO_EXTENSIONS = (
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico',
    '.css', '.js', '.json', '.html', '.php', '.txt', '.xml'
)

TRASH_TOKENS = [
    "//_//", "#@#", "@#@", "!#!", "$$$", "$$", "&&&", "|||",
    "^^", "%%", "@@", "##", "_//_", "--", "==", "__"
]


def extract_raw_stream_from_json(res_json) -> tuple[str, str]:
    """
    Безопасно извлекает строку со ссылками или ошибку из ответа сервера.
    Гарантирует отсутствие крашей на 'bool' object has no attribute 'replace' или None.
    """
    if not isinstance(res_json, dict):
        return "", f"Ответ сервера не является JSON-объектом ({type(res_json).__name__})"

    if res_json.get('success') is False or res_json.get('status') == 'error':
        msg = res_json.get('message') or res_json.get('error') or "Сервер сообщил: success=false"
        return "", str(msg)

    for key in ('url', 'stream', 'streams', 'link', 'links', 'file', 'video', 'playlist'):
        val = res_json.get(key)
        if isinstance(val, str) and val.strip():
            return val.replace(r'\/', '/').strip(), ""
        elif isinstance(val, (list, dict)):
            try:
                return json.dumps(val), ""
            except Exception:
                pass

    if res_json.get('url') is False:
        msg = res_json.get('message') or "Сервер не предоставил ссылку на видео (url: false, возможно видео изъято или заблокировано)."
        return "", str(msg)

    msg = res_json.get('message') or "В ответе сервера отсутствует ссылка на видеопоток."
    return "", str(msg)


def decode_obfuscated_stream(raw: str) -> str:
    """
    Расшифровывает мусорные токены и base64-обфускацию PlayerJS / HDRezka.
    """
    if not isinstance(raw, str) or not raw:
        return ""

    raw = raw.strip()
    if re.search(r'\[\d+p?[^\]]*\]https?://', raw):
        return raw

    cleaned = raw
    if cleaned.startswith(("#h", "#0", "#1", "#2", "#3", "#")):
        cleaned = re.sub(r'^#[a-zA-Z0-9]?', '', cleaned)

    for token in TRASH_TOKENS:
        cleaned = cleaned.replace(token, "")

    cleaned = cleaned.strip()
    try:
        rem = len(cleaned) % 4
        if rem:
            cleaned += '=' * (4 - rem)
        decoded = base64.b64decode(cleaned).decode('utf-8', errors='ignore')
        if "http" in decoded or "[" in decoded:
            logger.info("[StreamDecoder] Успешно расшифрован обфусцированный поток (base64/trash).")
            return decoded
    except Exception:
        pass

    return raw


def clean_stream_url(stream_url: str) -> str:
    """
    Очищает ссылку потока от HLS сегментов, параметров плеера PlayerJS и мусорных суффиксов.
    """
    if not isinstance(stream_url, str):
        return ""
    u = stream_url.strip('; "\'')
    if ":hls:seg-" in u:
        u = re.sub(r':hls:seg-[^/]+\.ts.*', '', u)
    elif ".ts" in u and "seg-" in u:
        u = re.sub(r':?seg-[^/]+\.ts.*', '', u)
    elif ".m4s" in u:
        u = re.sub(r'/[^/]+(?:\.m4s).*$', '/master.m3u8', u)
    u = u.replace(':hls:manifest.m3u8', '')
    return u.strip('; "\'')


def score_stream_url(url: str, tag: str = "") -> tuple[float, str]:
    """
    Анализирует пригодность ссылки и фильтрует спам, рекламу и фейковые ссылки.
    Возвращает (score, reason). Если score <= 0, ссылка отбрасывается как спам.
    """
    if not url or not isinstance(url, str):
        return 0.0, "empty"

    u_lower = url.lower().strip()
    tag_lower = tag.lower().strip()

    if not u_lower.startswith(('http://', 'https://')):
        return 0.0, "invalid_scheme"

    for pattern in AD_AND_SPAM_PATTERNS:
        if re.search(pattern, u_lower) or re.search(pattern, tag_lower):
            return 0.0, f"ad_or_spam:{pattern}"

    clean_path = u_lower.split('?')[0].split('#')[0]
    for ext in NON_VIDEO_EXTENSIONS:
        if clean_path.endswith(ext):
            return 0.0, f"non_video_ext:{ext}"

    score = 10.0
    if '.m3u8' in u_lower or ':hls:' in u_lower:
        score += 60.0
        if 'manifest' in u_lower or 'master' in u_lower or 'index' in u_lower:
            score += 20.0
    elif any(clean_path.endswith(ve) for ve in ('.mp4', '.mkv', '.webm', '.m4v')):
        score += 40.0

    for kw in ('voidboost', 'stream', 'cdn', 'media', 'play', 'vod', 'video', 'hls'):
        if kw in u_lower:
            score += 15.0
            break

    if re.search(r'\d{3,4}p?', tag_lower):
        score += 10.0

    for susp in ('sample', 'test', 'fake', 'dummy'):
        if susp in u_lower:
            score -= 30.0

    return max(score, 0.0), "valid"


def parse_voidboost_streams(streams_raw):
    """
    Разбирает строку потоков Voidboost/HDRezka, расшифровывает обфускацию,
    отсеивает спам и рекламные вставки.
    """
    if not streams_raw:
        return []

    decoded_raw = decode_obfuscated_stream(streams_raw)
    pattern = r'\[([^\]]+)\](https?://[^\[\]]+)'
    matches = re.findall(pattern, decoded_raw)
    parsed = []

    for tag_raw, urls_part in matches:
        clean_tag = re.sub(r'<[^>]+>', '', tag_raw).strip()
        is_ultra = 'ultra' in clean_tag.lower()
        is_prem = (
            'prem' in tag_raw.lower() or
            'pjs-prem' in tag_raw.lower() or
            'prem.svg' in tag_raw.lower() or
            'prem.svg' in urls_part.lower() or
            is_ultra
        )

        res_m = re.search(r'(\d+)', clean_tag)
        res_num = int(res_m.group(1)) if res_m else 720

        raw_candidates = re.findall(r'https?://[^\s,;]+', urls_part)
        valid_candidates = []

        for candidate in raw_candidates:
            clean_c = clean_stream_url(candidate)
            score, reason = score_stream_url(clean_c, tag=clean_tag)
            if score > 0:
                valid_candidates.append({
                    'url': clean_c,
                    'score': score
                })

        if not valid_candidates:
            continue

        valid_candidates.sort(key=lambda x: x['score'], reverse=True)
        best_candidate = valid_candidates[0]

        key = f"{res_num}_ultra" if is_ultra else str(res_num)
        label = f"{res_num}p Ultra" if is_ultra else f"{res_num}p"
        sort_score = res_num * 10 + (5 if is_ultra else 0)

        parsed.append({
            'key': key,
            'res_num': res_num,
            'is_ultra': is_ultra,
            'is_prem': is_prem,
            'label': label,
            'sort_score': sort_score,
            'best_url': best_candidate['url']
        })

    free_streams = [s for s in parsed if not s['is_prem']]
    if free_streams:
        parsed = free_streams

    parsed.sort(key=lambda x: x['sort_score'], reverse=True)
    return parsed


def extract_best_link(streams_raw, target_res=1080):
    if not streams_raw:
        return None, None

    streams = parse_voidboost_streams(streams_raw)
    if not streams:
        decoded = decode_obfuscated_stream(streams_raw)
        urls = re.findall(r'(https?://[^\s,;\[\]"\'<>]+)', decoded)
        valid_fallback = []
        for u in urls:
            clean_u = clean_stream_url(u.split(' or ')[0].strip())
            score, _ = score_stream_url(clean_u)
            if score > 0:
                valid_fallback.append((score, clean_u))
        if valid_fallback:
            valid_fallback.sort(key=lambda x: x[0], reverse=True)
            chosen_url = valid_fallback[0][1]
            q_match = re.search(r'[/_](\d{3,4})p?[\._/]', chosen_url)
            q_str = f"{q_match.group(1)}p" if q_match else None
            return chosen_url, q_str
        return None, None

    target_str = str(target_res).lower().strip()
    target_num_match = re.search(r'(\d+)', target_str)
    target_num = int(target_num_match.group(1)) if target_num_match else 1080
    wants_ultra = 'ultra' in target_str

    # 1. Exact match if user specifically requested ultra
    if wants_ultra:
        for s in streams:
            if s['is_ultra']:
                return s['best_url'], s['label']

    # 2. Exact match by res_num (non-ultra preferred if not explicitly ultra)
    for s in streams:
        if s['res_num'] == target_num and not s['is_ultra']:
            return s['best_url'], s['label']

    # If 1080 was requested and ultra is the only 1080 available, take it
    if target_num >= 1080:
        for s in streams:
            if s['res_num'] == 1080 and s['is_ultra']:
                return s['best_url'], s['label']

    # 3. Closest quality <= target_num
    lower_or_equal = [s for s in streams if s['res_num'] <= target_num]
    if lower_or_equal:
        chosen = lower_or_equal[0]
        return chosen['best_url'], chosen['label']

    # 4. Otherwise closest overall (the lowest available stream)
    chosen = streams[-1]
    return chosen['best_url'], chosen['label']


class LampaWorkerSignals(QObject):
    finished = pyqtSignal(list)
    status = pyqtSignal(str)


class LampaScannerWorker(QRunnable):
    def __init__(self, url, settings=None):
        super().__init__()
        self.url = url
        self.settings = settings
        self.signals = LampaWorkerSignals()

    def run(self):
        driver = None
        try:
            driver = create_browser_driver(headless=False, user_agent=BROWSER_USER_AGENT, use_profile=True)
            driver.maximize_window()
            driver.get(self.url)

            stream_url = None
            custom_title = "Lampa Video"
            quality_str = ""
            poster_url = None

            for _ in range(300):
                try:
                    if not driver.window_handles:
                        break

                    video_tags = driver.find_elements(By.CSS_SELECTOR, "video.player-video__video, video")
                    for tag in video_tags:
                        src = tag.get_attribute("src")
                        if src and src.startswith("http"):
                            stream_url = src
                            try:
                                title_el = driver.find_element(By.CSS_SELECTOR, ".player-info__name, .full-start__title")
                                if title_el and title_el.text:
                                    custom_title = title_el.text
                            except Exception:
                                pass

                            try:
                                vh = driver.execute_script("return arguments[0].videoHeight;", tag)
                                if vh and int(vh) > 0:
                                    quality_str = f"{vh}p"
                            except Exception:
                                pass

                            try:
                                poster_el = driver.find_element(By.CSS_SELECTOR, ".player-info img, .full-start__poster img, img.card__img")
                                if poster_el:
                                    poster_url = poster_el.get_attribute("src")
                            except Exception:
                                pass
                            break

                    if stream_url:
                        break
                except Exception:
                    break

                time.sleep(0.4)

            try:
                driver.quit()
            except Exception:
                pass

            if stream_url:
                if not quality_str:
                    q_match = re.search(r'[/_](\d{3,4})p?[\._/]', stream_url)
                    if q_match:
                        quality_str = f"{q_match.group(1)}p"

                safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title).strip()
                self.signals.finished.emit([{
                    'url': stream_url,
                    'title': safe_title,
                    'quality': quality_str,
                    'poster_url': poster_url
                }])
                return

        except Exception as e:
            logger.error(f"Ошибка Lampa сканера: {e}")
            try:
                if driver: driver.quit()
            except Exception:
                pass

        self.signals.finished.emit([])


class KinoPubFetchSignals(QObject):
    progress = pyqtSignal(int, str, str)  # percent, step_key, message
    ready = pyqtSignal(dict)
    error = pyqtSignal(str)


class KinoPubFetchWorker(QRunnable):
    def __init__(self, url, settings=None):
        super().__init__()
        self.url = url
        self.settings = settings
        self.signals = KinoPubFetchSignals()
        self._cancel_requested = threading.Event()
        self.driver = None

    def cancel(self):
        self._cancel_requested.set()
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass

    def run(self):
        driver = None
        try:
            if self._cancel_requested.is_set():
                return

            self.signals.progress.emit(10, 'browser', 'Быстрая проверка страницы...')
            page_source, cookies_list, favs = try_direct_http_fetch(self.url, timeout=6)

            if not page_source:
                self.signals.progress.emit(25, 'browser', 'Запуск браузера для обхода защиты...')
                try:
                    driver = create_browser_driver(headless=True, user_agent=BROWSER_USER_AGENT, use_profile=True)
                except Exception as browser_init_err:
                    logger.warning(f"[KinoPub] Сбой запуска браузера с профилем: {browser_init_err}. Пробуем без профиля...")
                    driver = create_browser_driver(headless=True, user_agent=BROWSER_USER_AGENT, use_profile=False)

                self.driver = driver

                if self._cancel_requested.is_set():
                    if driver: driver.quit()
                    return

                self.signals.progress.emit(40, 'connect', 'Подключение к сайту и обход защиты...')
                try:
                    driver.get(self.url)
                except Exception as get_err:
                    err_str = str(get_err)
                    if 'ERR_SOCKS' in err_str or 'ERR_PROXY' in err_str:
                        logger.warning(f"[KinoPub] Обнаружена ошибка прокси профиля ({get_err}). Перезапуск без профиля...")
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = create_browser_driver(headless=True, user_agent=BROWSER_USER_AGENT, use_profile=False)
                        self.driver = driver
                        driver.get(self.url)
                    else:
                        raise

                for _ in range(20):
                    if self._cancel_requested.is_set():
                        if driver: driver.quit()
                        return
                    time.sleep(0.5)
                    src = driver.page_source or ""
                    if 'translators-list' in src or 'ctrl_favs' in src or 'b-post__title' in src:
                        break

                favs = ""
                try:
                    favs = driver.execute_script(
                        "return (typeof $ !== 'undefined' && $('#ctrl_favs').length) ? $('#ctrl_favs').val() : (document.getElementById('ctrl_favs') ? document.getElementById('ctrl_favs').value : '');"
                    ) or ""
                except Exception as e:
                    logger.debug(f"Could not read favs from JS: {e}")

                page_source = driver.page_source
                cookies_list = driver.get_cookies()

                try:
                    driver.quit()
                    self.driver = None
                    driver = None
                except Exception:
                    pass

                if not favs and page_source:
                    favs_m = re.search(r'id=["\']ctrl_favs["\'][^>]*value=["\']([^"\']+)["\']', page_source) or \
                             re.search(r'value=["\']([^"\']+)["\'][^>]*id=["\']ctrl_favs["\']', page_source)
                    if favs_m:
                        favs = favs_m.group(1)

            if self._cancel_requested.is_set():
                return

            self.signals.progress.emit(65, 'parse', 'Парсинг озвучек, сезонов и серий...')
            soup = BeautifulSoup(page_source, 'html.parser')
            title_el = soup.select_one('.b-post__title h1')
            anime_title = title_el.text.strip() if title_el else "Видео"
            safe_anime_title = re.sub(r'[\\/*?:"<>|]', "", anime_title)

            post_id_el = soup.select_one('#post_id')
            post_id = post_id_el.get('value') if post_id_el else None
            if not post_id:
                post_id_match = re.search(r'data-id="(\d+)"', page_source)
                post_id = post_id_match.group(1) if post_id_match else None

            if not post_id:
                if 'ERR_' in page_source or 'ERR_NO_SUPPORTED_PROXIES' in page_source:
                    raise RuntimeError("Ошибка подключения через прокси (ERR_PROXY). Проверьте адрес и логин/пароль прокси.")
                elif 'О, привет!' in page_source or 'within.website' in page_source or 'cf-browser-verification' in page_source:
                    raise RuntimeError("Сайт KinoPub заблокировал этот IP/прокси защитой Cloudflare. Отключите прокси или используйте VPN.")
                elif not page_source or len(page_source) < 1000:
                    raise RuntimeError("Не удалось загрузить страницу KinoPub (пустой ответ).")

            voiceovers = [{'name': el.text.strip(), 'id': el.get('data-translator_id')} for el in
                          soup.select('#translators-list li.b-translator__item')]
            seasons = [{'name': el.text.strip(), 'id': el.get('data-tab_id')} for el in
                       soup.select('#simple-seasons-tabs li.b-simple_season__item')]
            episodes = [
                {'name': el.text.strip(), 'id': el.get('data-episode_id'), 'season_id': el.get('data-season_id')} for el
                in soup.select('.b-simple_episodes__list li.b-simple_episode__item')]

            is_movie = len(episodes) == 0

            default_tr_id = ''
            tr_match = re.search(r'sof\.tv\.initCDN(?:Series|Movies)Events\s*\(\s*\d+\s*,\s*(\d+)', page_source)
            if tr_match:
                default_tr_id = tr_match.group(1)

            if not voiceovers:
                fallback_id = default_tr_id or '59'
                voiceovers = [{'name': 'Оригинал / По умолчанию', 'id': fallback_id}]
            if not seasons: seasons = [{'name': '1 Сезон', 'id': '1'}]
            if not episodes: episodes = [{'name': 'Полный фильм', 'id': '1', 'season_id': '1'}]

            logger.info(f"[KinoPub] Страница распарсена: '{safe_anime_title}' (post_id: {post_id}). Озвучек: {len(voiceovers)}, Сезонов: {len(seasons)}, Серий: {len(episodes)}")

            available_qualities = ["1080p", "720p", "480p", "360p"]
            sample_streams_raw = None
            voice_qualities = {}

            self.signals.progress.emit(85, 'streams', 'Проверка доступных качеств видео...')
            session = requests.Session()
            session.proxies = {}
            session.trust_env = False
            for cookie in cookies_list:
                session.cookies.set(cookie['name'], cookie['value'])

            if self.settings and self.settings.value('use_cookies', False, type=bool):
                source_type = self.settings.value('cookie_source_type', 'file')
                if source_type == 'file':
                    cookie_file = self.settings.value('cookies_path', '')
                    if cookie_file and os.path.exists(cookie_file):
                        try:
                            import http.cookiejar
                            cj = http.cookiejar.MozillaCookieJar(cookie_file)
                            cj.load(ignore_discard=True, ignore_expires=True)
                            session.cookies.update(cj)
                        except Exception as ce:
                            logger.debug(f"Could not load cookie file into session: {ce}")
                else:
                    browser = self.settings.value('cookie_browser', self.settings.value('cookie_source', 'none'))
                    if browser and browser != 'none':
                        try:
                            import yt_dlp.cookies
                            cj = yt_dlp.cookies.extract_cookies_from_browser(browser)
                            if cj:
                                session.cookies.update(cj)
                        except Exception as ce:
                            logger.debug(f"Could not load browser cookies into session: {ce}")

            if post_id:
                sample_voice = voiceovers[0]['id'] if voiceovers else ''
                parsed = urlparse(self.url)
                headers = {
                    'User-Agent': BROWSER_USER_AGENT,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': self.url,
                    'Origin': f"{parsed.scheme}://{parsed.netloc}",
                    'Accept': 'application/json, text/javascript, */*; q=0.01'
                }

                def fetch_translator_stream(v_id):
                    t = int(time.time() * 1000)
                    ajax_url = f"{parsed.scheme}://{parsed.netloc}/ajax/get_cdn_series/?t={t}"
                    d = {'id': post_id, 'translator_id': v_id}
                    if favs:
                        d['favs'] = favs
                    if is_movie:
                        d['action'] = 'get_movie'
                    else:
                        d['action'] = 'get_stream'
                        d['season'] = seasons[0]['id'] if seasons else '1'
                        d['episode'] = episodes[0]['id'] if episodes else '1'
                    try:
                        r = session.post(ajax_url, headers=headers, data=d, timeout=8)
                        if r.status_code == 200:
                            raw_u, _ = extract_raw_stream_from_json(r.json())
                            if not raw_u:
                                # Fallback action
                                d['action'] = 'get_cdn_series' if not is_movie else 'get_stream'
                                r2 = session.post(ajax_url, headers=headers, data=d, timeout=8)
                                if r2.status_code == 200:
                                    raw_u, _ = extract_raw_stream_from_json(r2.json())
                            return raw_u
                    except Exception as e:
                        logger.debug(f"Failed to fetch sample stream for voice {v_id}: {e}")
                    return ''

                sample_streams_raw = fetch_translator_stream(sample_voice)
                if sample_streams_raw:
                    parsed_sample = parse_voidboost_streams(sample_streams_raw)
                    if parsed_sample:
                        v_key = str(sample_voice) if sample_voice else 'default'
                        voice_qualities[v_key] = [s['label'] for s in parsed_sample]
                        available_qualities = [s['label'] for s in parsed_sample]

                for v in voiceovers[1:5]:
                    if self._cancel_requested.is_set():
                        break
                    v_id = v.get('id', '')
                    v_streams = fetch_translator_stream(v_id)
                    if v_streams:
                        parsed_v = parse_voidboost_streams(v_streams)
                        if parsed_v:
                            voice_qualities[str(v_id)] = [s['label'] for s in parsed_v]

            if not sample_streams_raw:
                streams_match = re.search(r'"streams"\s*:\s*"([^"]+)"', page_source)
                if streams_match:
                    raw_s = streams_match.group(1).replace(r'\/', '/')
                    sample_streams_raw = decode_obfuscated_stream(raw_s)
                    parsed_st = parse_voidboost_streams(sample_streams_raw)
                    if parsed_st:
                        available_qualities = [s['label'] for s in parsed_st]

            poster_url = None
            poster_el = soup.select_one('.b-sidecover img, .b-post__infotable_left img, meta[property="og:image"]')
            if poster_el:
                if poster_el.name == 'meta':
                    poster_url = poster_el.get('content')
                else:
                    poster_url = poster_el.get('src')

            direct_url = None
            direct_quality = None
            if not post_id and sample_streams_raw:
                direct_url, direct_quality = extract_best_link(sample_streams_raw)

            if self._cancel_requested.is_set():
                return

            self.signals.progress.emit(100, 'streams', 'Данные успешно получены!')
            self.signals.ready.emit({
                'url': self.url,
                'post_id': post_id,
                'safe_anime_title': safe_anime_title,
                'voiceovers': voiceovers,
                'seasons': seasons,
                'episodes': episodes,
                'is_movie': is_movie,
                'available_qualities': available_qualities,
                'voice_qualities': voice_qualities,
                'favs': favs,
                'cookies': cookies_list,
                'direct_url': direct_url,
                'direct_quality': direct_quality,
                'poster_url': poster_url
            })
            return

        except Exception as e:
            if not self._cancel_requested.is_set():
                logger.error(f"Глобальная ошибка сканера KinoPub: {e}")
                self.signals.error.emit(str(e))
        finally:
            try:
                if driver: driver.quit()
            except Exception:
                pass


class KinoPubSeriesSignals(QObject):
    status = pyqtSignal(str)
    progress = pyqtSignal(int, str)  # current_index, episode_name
    finished = pyqtSignal(list)
    error = pyqtSignal(str)


class KinoPubSeriesWorker(QRunnable):
    def __init__(self, url, post_id, selected_voice, selected_season, selected_quality,
                 safe_anime_title, safe_v_name, safe_s_name, is_movie, targets, cookies, favs='', settings=None):
        super().__init__()
        self.url = url
        self.post_id = post_id
        self.selected_voice = selected_voice
        self.selected_season = selected_season
        self.selected_quality = selected_quality
        self.safe_anime_title = safe_anime_title
        self.safe_v_name = safe_v_name
        self.safe_s_name = safe_s_name
        self.is_movie = is_movie
        self.targets = targets
        self.cookies = cookies
        self.favs = favs
        self.settings = settings
        self.signals = KinoPubSeriesSignals()
        self._cancel_requested = threading.Event()

    def cancel(self):
        self._cancel_requested.set()

    def run(self):
        results = []
        driver = None
        try:
            session = requests.Session()
            session.proxies = {}
            session.trust_env = False
            for cookie in self.cookies:
                session.cookies.set(cookie['name'], cookie['value'])

            parsed_uri = urlparse(self.url)
            base_origin = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
            headers = {
                'User-Agent': BROWSER_USER_AGENT,
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': self.url,
                'Origin': base_origin,
                'Accept': 'application/json, text/javascript, */*; q=0.01'
            }

            v_id = str(self.selected_voice).strip() if self.selected_voice else '59'
            logger.info(f"[KinoPubSeries] Старт сбора ссылок: серий={len(self.targets)}, голос='{v_id}', сезон='{self.selected_season}', качество='{self.selected_quality}'")

            last_error_detail = None
            use_browser_for_ajax = False

            def execute_ajax_post(post_data):
                nonlocal driver, use_browser_for_ajax
                t = int(time.time() * 1000)
                ajax_url = f"{base_origin}/ajax/get_cdn_series/?t={t}"

                # 1. Попытка через requests, если браузер еще не потребовался
                if not use_browser_for_ajax:
                    try:
                        req = session.post(ajax_url, headers=headers, data=post_data, timeout=12)
                        if req.status_code == 200:
                            txt = req.text
                            # Проверяем, не страница ли это проверки антибота
                            if 'within.website' not in txt and 'О, привет!' not in txt and 'cf-browser-verification' not in txt:
                                try:
                                    j = req.json()
                                    streams_s, err_s = extract_raw_stream_from_json(j)
                                    if streams_s:
                                        return streams_s, ""
                                    if err_s:
                                        return "", err_s
                                except Exception:
                                    pass
                    except Exception as req_err:
                        logger.debug(f"[KinoPubSeries] Прямой HTTP запрос не удался ({req_err}), пробуем браузер...")

                # 2. Fallback: Выполнение через браузер в контексте открытой страницы
                try:
                    if driver is None:
                        logger.info("[KinoPubSeries] Активация браузера для обхода защиты при получении серий...")
                        self.signals.status.emit("Подключение браузера для обхода защиты...")
                        driver = create_browser_driver(headless=True, user_agent=BROWSER_USER_AGENT, use_profile=True)
                        driver.set_script_timeout(15)
                        driver.get(self.url)
                        time.sleep(1.0)
                        use_browser_for_ajax = True

                    js_code = """
                    var callback = arguments[arguments.length - 1];
                    var data = arguments[0];
                    var ajaxUrl = arguments[1];

                    if (typeof $ !== 'undefined' && $.ajax) {
                        $.ajax({
                            url: ajaxUrl,
                            type: 'POST',
                            data: data,
                            dataType: 'json',
                            timeout: 12000,
                            success: function(res) { callback({status: 200, json: res}); },
                            error: function(xhr, status, err) { 
                                var parsed = null;
                                try { parsed = JSON.parse(xhr.responseText); } catch(e) {}
                                callback({status: xhr.status || 500, json: parsed, text: xhr.responseText || '', error: err || status}); 
                            }
                        });
                    } else {
                        var params = new URLSearchParams();
                        for (var k in data) {
                            params.append(k, data[k]);
                        }
                        fetch(ajaxUrl, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                                'X-Requested-With': 'XMLHttpRequest'
                            },
                            body: params.toString()
                        })
                        .then(function(r) { return r.json(); })
                        .then(function(j) { callback({status: 200, json: j}); })
                        .catch(function(e) { callback({status: 500, error: e.toString()}); });
                    }
                    """
                    b_res = driver.execute_async_script(js_code, post_data, ajax_url)
                    if isinstance(b_res, dict) and b_res.get('status') == 200:
                        j = b_res.get('json')
                        streams_s, err_s = extract_raw_stream_from_json(j)
                        return streams_s, err_s
                except Exception as b_err:
                    logger.debug(f"[KinoPubSeries] Ошибка запроса через браузер: {b_err}")

                return "", "Не удалось получить ответ сервера"

            for idx, ep in enumerate(self.targets):
                if self._cancel_requested.is_set():
                    logger.info("[KinoPubSeries] Получен сигнал отмены сбора серий.")
                    break

                ep_name = ep.get('name', f"Серия {idx + 1}")
                self.signals.progress.emit(idx + 1, ep_name)
                self.signals.status.emit(f"Получаю ссылки: {idx + 1} из {len(self.targets)}...")
                logger.info(f"[KinoPubSeries] [{idx + 1}/{len(self.targets)}] Запрос ссылки для '{ep_name}' (ID: {ep.get('id')})...")

                primary_action = 'get_movie' if self.is_movie else 'get_stream'
                actions_to_try = [primary_action]
                if self.is_movie:
                    actions_to_try.extend(['get_stream', 'get_cdn_series'])
                else:
                    actions_to_try.extend(['get_cdn_series', 'get_movie'])

                streams_raw = ""
                for act in actions_to_try:
                    data = {
                        'id': self.post_id,
                        'translator_id': v_id,
                        'action': act
                    }
                    if self.favs:
                        data['favs'] = self.favs
                    if act != 'get_movie':
                        data['season'] = self.selected_season
                        data['episode'] = ep['id']

                    raw_res, err_res = execute_ajax_post(data)
                    if raw_res:
                        streams_raw = raw_res
                        break
                    elif err_res and not last_error_detail:
                        last_error_detail = err_res

                # Если с translator_id не найдено, пробуем резервный запрос без translator_id
                if not streams_raw and v_id == '59':
                    for act in actions_to_try:
                        data = {
                            'id': self.post_id,
                            'action': act
                        }
                        if self.favs:
                            data['favs'] = self.favs
                        if act != 'get_movie':
                            data['season'] = self.selected_season
                            data['episode'] = ep['id']
                        raw_res, _ = execute_ajax_post(data)
                        if raw_res:
                            streams_raw = raw_res
                            break

                if streams_raw:
                    best_link, actual_qual = extract_best_link(streams_raw, target_res=self.selected_quality)
                    if best_link:
                        safe_e_name = re.sub(r'[\\/*?:"<>|]', "", ep_name)
                        if self.is_movie:
                            custom_title = f"{self.safe_anime_title} ({self.safe_v_name})"
                        else:
                            custom_title = f"{self.safe_anime_title} - {self.safe_s_name} {safe_e_name} ({self.safe_v_name})"
                        q_badge = actual_qual or str(self.selected_quality)
                        if not q_badge.endswith('p') and 'ultra' not in q_badge.lower():
                            q_badge = f"{q_badge}p"
                        results.append({
                            'url': best_link,
                            'title': custom_title,
                            'quality': q_badge,
                            'referer': self.url
                        })
                        logger.info(f"[KinoPubSeries] [+] Ссылка получена: '{custom_title}' [{q_badge}] -> {best_link[:80]}...")
                    else:
                        last_error_detail = "Не удалось отфильтровать рабочий видеопоток из ответа"
                        logger.warning(f"[KinoPubSeries] [-] Не удалось отфильтровать видеопоток для '{ep_name}'")
                else:
                    if not last_error_detail:
                        last_error_detail = "Сервер не вернул ссылку на видеопоток"
                    logger.warning(f"[KinoPubSeries] Сервер не вернул поток для '{ep_name}': {last_error_detail}")

                time.sleep(0.2)

            logger.info(f"[KinoPubSeries] Завершен опрос серий. Успешно получено {len(results)} из {len(self.targets)}.")
            if not results and last_error_detail:
                logger.error(f"[KinoPubSeries] Ни одна ссылка не получена! Причина: {last_error_detail}")
                self.signals.error.emit(last_error_detail)
                return

        except Exception as e:
            logger.error(f"Ошибка получения серий KinoPub: {e}")
            self.signals.error.emit(str(e))
            return
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass

        self.signals.finished.emit(results)



class CustomExtractorSignals(QObject):
    ready = pyqtSignal(dict, object)
    error = pyqtSignal(str)


class CustomExtractorFetchWorker(QRunnable):
    def __init__(self, url, extractor):
        super().__init__()
        self.url = url
        self.extractor = extractor
        self.signals = CustomExtractorSignals()

    def run(self):
        try:
            meta = self.extractor.fetch_metadata(self.url)
            self.signals.ready.emit(meta, self.extractor)
        except Exception as e:
            logger.error(f"[CustomExtractor] Ошибка извлечения {self.url}: {e}", exc_info=True)
            self.signals.error.emit(str(e))


# ==================================

class DownloadManager(QObject):
    task_added = pyqtSignal(DownloadTask)
    download_started = pyqtSignal()
    all_downloads_finished = pyqtSignal()
    status_updated = pyqtSignal(str)
    summary_updated = pyqtSignal(str)
    active_threads_changed = pyqtSignal(int, int)

    def __init__(self, settings, ffmpeg_path, thread_pool, translator, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.settings = settings
        self.ffmpeg_path = ffmpeg_path
        self.thread_pool = thread_pool
        self.translator = translator
        self.tasks = []
        self.active_downloads = 0
        self.is_downloading_active = False
        self._workers = {}
        self._active_series_workers = []
        self._active_series_dialog = None
        self.max_thumbnail_workers = 5
        self.active_thumbnail_workers = 0
        self.thumbnail_queue = []

    def _update_summary(self):
        total = len(self.tasks)
        done = len([t for t in self.tasks if t.status == DownloadTask.Status.COMPLETED])
        errs = len([t for t in self.tasks if t.status == DownloadTask.Status.ERROR])
        if total > 0:
            completed_str = self.translator.translate('summary_completed', 'завершено')
            if errs > 0:
                errors_str = self.translator.translate('summary_errors', 'с ошибкой')
                summary_text = f"{done}/{total} {completed_str} • {errs} {errors_str}"
            else:
                summary_text = f"{done}/{total} {completed_str}"
        else:
            summary_text = ""
        self.summary_updated.emit(summary_text)
        self.active_threads_changed.emit(self.active_downloads, int(self.settings.value('parallel_downloads', 2)))

    def _clean_stream_url(self, stream_url: str) -> str:
        return clean_stream_url(stream_url)

    def _normalize_url(self, url: str) -> str:
        u = url.strip()
        if ":hls:seg-" in u or (".ts" in u and "seg-" in u) or ".m4s" in u:
            return self._clean_stream_url(u)
        m = re.search(r"https?://(?:www\.)?kick\.com/[^/]+/videos/([0-9a-fA-F-]{6,})", u)
        if m: return f"https://kick.com/video/{m.group(1)}"
        return u

    def add_urls(self, urls, quality_override=None, is_from_bot=False):
        for url in urls:
            url = self._normalize_url(url)

            if "vi3000" in url or "cub" in url or "lampa" in url:
                self._start_lampa_scan(url)
                continue

            elif "kinopub" in url or "kino.pub" in url or "rezka" in url:
                self._start_kinopub_scan(url, is_from_bot=is_from_bot)
                continue

            extractor = find_extractor_for_url(url)
            if extractor:
                self._start_custom_extractor_scan(url, extractor, is_from_bot=is_from_bot)
                continue

            # Предотвращаем дублирование активных или ожидающих задач
            if any(t.url == url and t.status in (DownloadTask.Status.DOWNLOADING, DownloadTask.Status.PENDING, DownloadTask.Status.FETCHING_INFO) for t in self.tasks):
                logger.info(f"[DownloadManager] Пропуск дубликата ссылки: {url}")
                continue

            task = DownloadTask(url)
            task.is_from_bot = is_from_bot
            if quality_override:
                task.quality_override = quality_override
                if quality_override in ('audio_only', 'audio_mp3'):
                    task.audio_only = True
                    task.quality_badge = "MP3" if quality_override == 'audio_mp3' else "AUDIO"
                elif quality_override in ('1080p', '720p', '480p'):
                    task.quality_badge = quality_override

            task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
            self.tasks.append(task)
            self.task_added.emit(task)
            self.fetch_video_info(task)

        self._update_summary()

    def queue_thumbnail_load(self, url, task):
        self.thumbnail_queue.append((url, task))
        self.process_thumbnail_queue()

    def process_thumbnail_queue(self):
        while self.thumbnail_queue and self.active_thumbnail_workers < self.max_thumbnail_workers:
            url, task = self.thumbnail_queue.pop(0)
            self.load_thumbnail(url, task)

    def load_thumbnail(self, url, task):
        self.active_thumbnail_workers += 1
        worker = ThumbnailWorker(url, task)
        worker.signals.thumbnail_loaded.connect(lambda pixmap: self.on_thumbnail_loaded(task, pixmap))
        self.thread_pool.start(worker)

    def on_thumbnail_loaded(self, task, pixmap):
        task.set_thumbnail(pixmap)
        self.active_thumbnail_workers -= 1
        self.process_thumbnail_queue()

    def fetch_video_info(self, task):
        worker = InfoWorker(task.url, self.settings)
        worker.signals.info_fetched.connect(lambda info, t=task: self.on_info_fetched(t, info))
        worker.signals.error.connect(lambda error, t=task: self.on_info_error(t, error))
        self.thread_pool.start(worker)

    def on_info_fetched(self, task, info):
        if hasattr(task, 'custom_title') and task.custom_title:
            info['title'] = task.custom_title
        if hasattr(task, 'custom_quality') and task.custom_quality:
            info['quality_badge'] = task.custom_quality
        task.update_info(info)
        self._update_summary()

    def on_info_error(self, task, error):
        task.set_error(self.translator.translate('error_getting_info'))
        logger.error(f"Error fetching info for {task.url}: {error}")
        self._update_summary()

    def start_all(self):
        if self.is_downloading_active: return
        tasks_to_start = [t for t in self.tasks if t.status == DownloadTask.Status.PENDING]
        if not tasks_to_start:
            self.status_updated.emit(self.translator.translate('no_links_to_download'))
            return
        self.is_downloading_active = True
        self.download_started.emit()
        self.status_updated.emit(self.translator.translate('starting_download'))
        for task in tasks_to_start:
            self.start_task(task)
        self._update_summary()

    def _task_display_name(self, task):
        return getattr(task, 'custom_title', None) or (task.title if getattr(task, 'title', None) and task.title != "..." else None) or getattr(task, 'url', 'Task')

    def start_task(self, task):
        max_concurrent = int(self.settings.value('parallel_downloads', 2))
        task_name = self._task_display_name(task)
        if self.active_downloads >= max_concurrent:
            logger.info(f"[DownloadManager] Задача '{task_name}' в очереди (активно: {self.active_downloads}/{max_concurrent})")
            return

        # Защита от параллельного скачивания одинакового URL в один и тот же файл (WinError 32)
        if any(t != task and t.url == task.url and t.status == DownloadTask.Status.DOWNLOADING for t in self.tasks):
            logger.warning(f"[DownloadManager] Задача с таким же URL уже скачивается, оставляем в очереди: '{task_name}'")
            return

        self.active_downloads += 1
        logger.info(f"[DownloadManager] Старт загрузки: '{task_name}' (активно: {self.active_downloads}/{max_concurrent})")
        task.set_status(DownloadTask.Status.DOWNLOADING)
        worker = DownloadWorker(task, self.settings, self.ffmpeg_path, self.translator)
        self._workers[task] = worker
        worker.signals.finished.connect(lambda t=task: self.on_task_finished(t))
        worker.signals.error.connect(lambda error, t=task: self.on_task_error(t, error))
        self.thread_pool.start(worker)
        self._update_summary()

    def on_task_finished(self, task):
        task_name = self._task_display_name(task)
        logger.info(f"[DownloadManager] Загрузка завершена: '{task_name}'")
        if self.active_downloads > 0: self.active_downloads -= 1
        if task in self._workers: self._workers.pop(task, None)
        pending_tasks = [t for t in self.tasks if t.status == DownloadTask.Status.PENDING]
        if pending_tasks:
            self.start_task(pending_tasks[0])
        elif self.active_downloads == 0:
            self.is_downloading_active = False
            self.all_downloads_finished.emit()
        self._update_summary()

    def on_task_error(self, task, error_msg):
        task_name = self._task_display_name(task)
        logger.error(f"[DownloadManager] Ошибка загрузки задачи '{task_name}': {error_msg}")
        task.set_error(error_msg)
        self.on_task_finished(task)

    def stop_all(self):
        if not self.is_downloading_active and self.active_downloads == 0: return
        for task in self.tasks:
            if task.status in (DownloadTask.Status.FETCHING_INFO, DownloadTask.Status.DOWNLOADING,
                               DownloadTask.Status.PENDING, DownloadTask.Status.PROCESSING):
                task.request_stop()
                worker = self._workers.get(task)
                if worker: worker.cancel()
        self.status_updated.emit(self.translator.translate('stopping_downloads'))
        self.is_downloading_active = False
        self._update_summary()

    def remove_task(self, task):
        if task in self.tasks:
            task.request_stop()
            worker = self._workers.get(task)
            if worker: worker.cancel()
            try:
                self.tasks.remove(task)
            except ValueError:
                pass
            self._update_summary()

    def start_or_retry_task(self, task):
        if task.status in (DownloadTask.Status.ERROR, DownloadTask.Status.STOPPED, DownloadTask.Status.PENDING):
            task.set_status(DownloadTask.Status.PENDING)
            if not self.is_downloading_active:
                self.start_all()
            else:
                self.start_task(task)

    def get_completed_tasks(self):
        return [t for t in self.tasks if
                t.status in (DownloadTask.Status.COMPLETED, DownloadTask.Status.ERROR, DownloadTask.Status.STOPPED)]

    def _extract_best_link(self, streams_raw, target_res=None):
        if target_res is None:
            quality_setting = self.settings.value('quality_kinopub', '1080')
            target_res = 1080
            for q in [360, 480, 720, 1080, 1440, 2160]:
                if str(q) in str(quality_setting): target_res = q
        return extract_best_link(streams_raw, target_res=target_res)

    def _start_custom_extractor_scan(self, url, extractor, is_from_bot=False):
        self.status_updated.emit(f"Анализ {extractor.name}...")
        worker = CustomExtractorFetchWorker(url, extractor)
        worker.signals.ready.connect(lambda meta, ext=extractor: self._on_custom_extractor_ready(meta, ext, is_from_bot=is_from_bot))
        worker.signals.error.connect(lambda err, ext=extractor: self._on_custom_extractor_error(err, ext, is_from_bot=is_from_bot))
        self.thread_pool.start(worker)

    def _on_custom_extractor_error(self, err, extractor, is_from_bot=False):
        logger.error(f"[{extractor.name}] Ошибка анализа: {err}")
        self.status_updated.emit(f"Ошибка {extractor.name}: {err}")
        if is_from_bot and hasattr(self, 'bot_manager') and self.bot_manager:
            self.bot_manager.send_message(f"❌ Ошибка анализа {extractor.name}:\n{err}")

    def _on_custom_extractor_ready(self, meta, extractor, is_from_bot=False):
        episodes = meta.get('episodes', [])
        voiceovers = meta.get('voiceovers', [])
        if episodes or (voiceovers and len(voiceovers) > 1):
            if is_from_bot:
                if hasattr(self, 'bot_manager') and self.bot_manager:
                    self.bot_manager.start_interactive_selection(
                        meta=meta,
                        on_complete=lambda voice, quality, targets, m=meta, ext=extractor: self._start_custom_extractor_from_bot(m, ext, voice, quality, targets),
                        on_cancel=lambda: self.status_updated.emit(f"Выбор {extractor.name} отменен в Telegram.")
                    )
                return

            v_list = voiceovers or [{'name': 'Оригинал', 'id': '1'}]
            s_list = meta.get('seasons', [{'name': '1 Сезон', 'id': '1'}])
            ep_list = episodes or [{'name': 'Полный выпуск / Фильм', 'id': '1', 'season_id': '1', 'episode_number': 1}]
            qualities = meta.get('available_qualities', ['1080p', '720p', '480p'])
            is_movie = meta.get('is_movie', False) and len(ep_list) <= 1

            dialog = EpisodeSelectionDialog(
                v_list,
                s_list,
                ep_list,
                qualities,
                is_movie=is_movie,
                parent=self.parent_window
            )
            if dialog.exec():
                selected_targets = dialog.get_selected_targets()
                selected_v = dialog.get_selected_voiceover()
                selected_q = dialog.get_selected_quality()
                if not selected_targets and is_movie:
                    selected_targets = ep_list

                added_count = 0
                for ep in selected_targets:
                    ep_meta = dict(meta)
                    ep_meta.update(ep)
                    ep_meta['selected_voiceover'] = selected_v
                    try:
                        direct_url, q_badge = extractor.resolve_stream(ep_meta, quality=selected_q)
                    except Exception as e:
                        logger.error(f"[{extractor.name}] Ошибка получения потока: {e}")
                        direct_url = None

                    if not direct_url:
                        logger.warning(f"[{extractor.name}] Не удалось получить прямую ссылку для серии {ep.get('name')}")
                        continue

                    title = f"{meta.get('safe_anime_title', 'Anime')} - {ep.get('name', 'Серия')}"
                    if selected_v and selected_v.get('name') and selected_v.get('name') not in ('Default', 'Оригинал'):
                        title += f" [{selected_v.get('name')}]"

                    task = DownloadTask(direct_url)
                    task.title = title
                    task.custom_title = title
                    task.custom_quality = selected_q or q_badge
                    task.quality_badge = selected_q or q_badge or ""
                    task.thumbnail_url = meta.get('poster_url')
                    if any(d in direct_url for d in ('solodcdn', 'kodik')):
                        task.referer = 'https://kodikplayer.com/'
                    elif any(d in direct_url for d in ('aniboom', 'ya-ligh', 'boom-img')):
                        task.referer = 'https://aniboom.one/'
                    elif meta.get('referer'):
                        task.referer = meta.get('referer')
                    task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
                    self.tasks.append(task)
                    self.task_added.emit(task)
                    if task.thumbnail_url:
                        self.queue_thumbnail_load(task.thumbnail_url, task)
                    self.start_task(task)
                    added_count += 1

                if added_count == 0:
                    self.status_updated.emit(f"Не удалось получить видеопоток для выбранных серий {extractor.name}")
                self._update_summary()
        else:
            direct_url = meta.get('direct_url')
            if not direct_url:
                try:
                    direct_url, _ = extractor.resolve_stream(meta, quality=meta.get('quality', '1080p'))
                except Exception:
                    direct_url = None
            if not direct_url:
                self.status_updated.emit(f"Не удалось получить видео с {extractor.name}")
                if is_from_bot and hasattr(self, 'bot_manager') and self.bot_manager:
                    self.bot_manager.send_message(f"❌ Не удалось получить видео с {extractor.name}")
                return
            task = DownloadTask(direct_url)
            task.is_from_bot = is_from_bot
            task.custom_title = meta.get('safe_anime_title')
            task.custom_quality = meta.get('quality', '1080p')
            task.thumbnail_url = meta.get('poster_url')
            if meta.get('referer'):
                task.referer = meta.get('referer')
            task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
            self.tasks.append(task)
            self.task_added.emit(task)
            if task.thumbnail_url:
                self.queue_thumbnail_load(task.thumbnail_url, task)
            self.fetch_video_info(task)
            self._update_summary()

    def _start_custom_extractor_from_bot(self, meta, extractor, selected_v, selected_q, selected_targets):
        class ResolveStreamsWorker(QRunnable):
            def __init__(self, dm, meta, extractor, selected_v, selected_q, targets):
                super().__init__()
                self.dm = dm
                self.meta = meta
                self.extractor = extractor
                self.selected_v = selected_v
                self.selected_q = selected_q
                self.targets = targets

            def run(self):
                added_count = 0
                for ep in self.targets:
                    ep_meta = dict(self.meta)
                    ep_meta.update(ep)
                    ep_meta['selected_voiceover'] = self.selected_v
                    try:
                        direct_url, q_badge = self.extractor.resolve_stream(ep_meta, quality=self.selected_q)
                    except Exception as e:
                        logger.error(f"[{self.extractor.name}] Ошибка получения потока: {e}")
                        direct_url = None

                    if not direct_url:
                        logger.warning(f"[{self.extractor.name}] Не удалось получить прямую ссылку для {ep.get('name')}")
                        continue

                    title = f"{self.meta.get('safe_anime_title', 'Anime')} - {ep.get('name', 'Серия')}"
                    if self.selected_v and isinstance(self.selected_v, dict) and self.selected_v.get('name') and self.selected_v.get('name') not in ('Default', 'Оригинал'):
                        title += f" [{self.selected_v.get('name')}]"

                    task = DownloadTask(direct_url)
                    task.is_from_bot = True
                    task.title = title
                    task.custom_title = title
                    task.custom_quality = self.selected_q or q_badge
                    task.quality_badge = self.selected_q or q_badge or ""
                    task.thumbnail_url = self.meta.get('poster_url')
                    if any(d in direct_url for d in ('solodcdn', 'kodik')):
                        task.referer = 'https://kodikplayer.com/'
                    elif any(d in direct_url for d in ('aniboom', 'ya-ligh', 'boom-img')):
                        task.referer = 'https://aniboom.one/'
                    elif self.meta.get('referer'):
                        task.referer = self.meta.get('referer')
                    task.thumbnail_load_requested.connect(self.dm.queue_thumbnail_load)
                    self.dm.tasks.append(task)
                    self.dm.task_added.emit(task)
                    if task.thumbnail_url:
                        self.dm.queue_thumbnail_load(task.thumbnail_url, task)
                    self.dm.start_task(task)
                    added_count += 1

                if added_count == 0:
                    self.dm.status_updated.emit(f"Не удалось получить видеопоток для {self.extractor.name}")
                    if hasattr(self.dm, 'bot_manager') and self.dm.bot_manager:
                        self.dm.bot_manager.send_message(f"❌ Не удалось получить видеопоток для {self.extractor.name}")
                self.dm._update_summary()

        worker = ResolveStreamsWorker(self, meta, extractor, selected_v, selected_q, selected_targets)
        self.thread_pool.start(worker)

    def _start_lampa_scan(self, url):
        self.status_updated.emit("Ожидаю включения плеера в браузере...")
        worker = LampaScannerWorker(url, settings=self.settings)
        worker.signals.finished.connect(lambda results, u=url: self._on_lampa_finished(u, results))
        worker.signals.status.connect(self.status_updated.emit)
        self.thread_pool.start(worker)

    def _on_lampa_finished(self, url, results):
        if results:
            new_tasks = []
            for res in results:
                task = DownloadTask(res['url'])
                task.custom_title = res['title']
                if res.get('quality'):
                    task.custom_quality = res['quality']
                    task.quality_badge = res['quality']
                if res.get('poster_url'):
                    task.thumbnail_url = res['poster_url']
                task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
                self.tasks.append(task)
                self.task_added.emit(task)
                self.fetch_video_info(task)
                if task.thumbnail_url:
                    self.queue_thumbnail_load(task.thumbnail_url, task)
                new_tasks.append(task)
            for t in new_tasks:
                self.start_task(t)
        else:
            task = DownloadTask(url)
            task.set_error("Видео не включено или браузер закрыт.")
            self.tasks.append(task)
            self.task_added.emit(task)
        self._update_summary()

    def _start_kinopub_scan(self, url, existing_dialog=None, is_from_bot=False):
        self.status_updated.emit("Анализ KinoPub / Rezka...")
        if is_from_bot:
            worker = KinoPubFetchWorker(url, settings=self.settings)
            worker.signals.ready.connect(lambda meta: self._on_kinopub_meta_ready(meta, is_from_bot=True))
            worker.signals.error.connect(lambda err, u=url: self._on_kinopub_scan_error(err, None, u, is_from_bot=True))
            self.thread_pool.start(worker)
            return

        dialog = existing_dialog or KinoPubScanDialog(url, parent=self.parent_window)
        worker = KinoPubFetchWorker(url, settings=self.settings)

        dialog.cancelled.connect(worker.cancel)
        worker.signals.progress.connect(dialog.set_step_progress)
        worker.signals.ready.connect(lambda meta, d=dialog: self._on_kinopub_scan_ready(meta, d))
        worker.signals.error.connect(lambda err, d=dialog, u=url: self._on_kinopub_scan_error(err, d, u, is_from_bot=False))

        if not existing_dialog:
            dialog.retry_requested.connect(lambda d=dialog, u=url: self._start_kinopub_scan(u, existing_dialog=d, is_from_bot=False))
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

        self.thread_pool.start(worker)

    def _on_kinopub_scan_ready(self, meta, dialog):
        if dialog and not dialog.is_cancelled:
            try:
                dialog.accept()
            except Exception:
                pass
        self._on_kinopub_meta_ready(meta, is_from_bot=False)

    def _on_kinopub_scan_error(self, err, dialog, url, is_from_bot=False):
        info = format_kinopub_error(str(err))
        logger.error(f"KinoPub scan error for {url}: {err}")
        self.status_updated.emit(f"KinoPub: {info['short_status']}")
        if is_from_bot:
            if hasattr(self, 'bot_manager') and self.bot_manager:
                self.bot_manager.send_message(f"❌ Ошибка анализа видео (KinoPub / Rezka):\n{info['message']}")
            return
        if dialog and not dialog.is_cancelled:
            dialog.show_error(str(err))

    def _on_kinopub_meta_ready(self, meta, is_from_bot=False):
        url = meta['url']
        post_id = meta['post_id']
        voiceovers = meta['voiceovers']
        seasons = meta['seasons']
        episodes = meta['episodes']
        qualities = meta['available_qualities']
        voice_qualities = meta.get('voice_qualities', {})
        favs = meta.get('favs', '')
        is_movie = meta['is_movie']

        self._current_kinopub_poster = meta.get('poster_url')

        if is_from_bot:
            if hasattr(self, 'bot_manager') and self.bot_manager:
                self.bot_manager.start_interactive_selection(
                    meta=meta,
                    on_complete=lambda voice, quality, targets, m=meta: self._start_kinopub_from_bot(m, voice, quality, targets),
                    on_cancel=lambda: self.status_updated.emit("Выбор KinoPub отменен в Telegram.")
                )
            return

        if post_id:
            logger.info(f"[KinoPub] Открытие диалога выбора серий для '{meta.get('safe_anime_title')}' (post_id: {post_id})...")
            dialog = EpisodeSelectionDialog(
                voiceovers,
                seasons,
                episodes,
                qualities,
                voice_qualities=voice_qualities,
                is_movie=is_movie,
                parent=self.parent_window
            )
            if dialog.exec():
                selected_v_obj = dialog.get_selected_voiceover()
                selected_s_obj = dialog.get_selected_season()
                selected_voice = str(selected_v_obj.get('id', ''))
                if not selected_voice:
                    selected_voice = '59'
                selected_season = str(selected_s_obj.get('id', '1'))
                selected_quality = dialog.get_selected_quality()

                safe_v_name = re.sub(r'[\\/*?:"<>|]', "", selected_v_obj.get('name', 'Default'))
                safe_s_name = re.sub(r'[\\/*?:"<>|]', "", selected_s_obj.get('name', '1 Сезон'))
                targets = dialog.get_selected_targets()

                logger.info(f"[KinoPub] Диалог завершился подтверждением (OK).")
                logger.info(f"[KinoPub] Параметры: Озвучка='{safe_v_name}' (ID: {selected_voice}), Сезон='{safe_s_name}', Качество='{selected_quality}', Выбрано серий={len(targets)}")

                if not targets:
                    logger.warning("[KinoPub] Список выбранных серий пуст. Загрузка отменена.")
                    self.status_updated.emit("Серии не выбраны.")
                    return

                series_worker = KinoPubSeriesWorker(
                    url=url,
                    post_id=post_id,
                    selected_voice=selected_voice,
                    selected_season=selected_season,
                    selected_quality=selected_quality,
                    safe_anime_title=meta['safe_anime_title'],
                    safe_v_name=safe_v_name,
                    safe_s_name=safe_s_name,
                    is_movie=is_movie,
                    targets=targets,
                    cookies=meta['cookies'],
                    favs=favs,
                    settings=self.settings
                )

                # Сохраняем воркер в список, чтобы Python GC не уничтожил его во время выполнения
                self._active_series_workers.append(series_worker)

                series_dialog = KinoPubSeriesProgressDialog(len(targets), parent=self.parent_window)
                self._active_series_dialog = series_dialog

                series_dialog.cancel_requested.connect(series_worker.cancel)
                series_worker.signals.progress.connect(series_dialog.update_progress)
                series_worker.signals.status.connect(self.status_updated.emit)

                def on_series_success(res, w=series_worker, d=series_dialog):
                    if w in self._active_series_workers:
                        self._active_series_workers.remove(w)
                    try:
                        d.accept()
                    except Exception:
                        pass
                    self._on_kinopub_series_finished(res, is_from_bot=False)

                def on_series_failed(err, w=series_worker, d=series_dialog):
                    if w in self._active_series_workers:
                        self._active_series_workers.remove(w)
                    try:
                        d.accept()
                    except Exception:
                        pass
                    self._on_kinopub_series_error(err, is_from_bot=False)

                series_worker.signals.finished.connect(on_series_success)
                series_worker.signals.error.connect(on_series_failed)

                series_dialog.show()
                series_dialog.raise_()
                series_dialog.activateWindow()

                logger.info(f"[KinoPub] Запуск KinoPubSeriesWorker в пуле потоков thread_pool...")
                self.thread_pool.start(series_worker)
            else:
                logger.info("[KinoPub] Выбор серий отменен пользователем.")
                self.status_updated.emit("Выбор отменен.")
        elif meta.get('direct_url'):
            task = DownloadTask(meta['direct_url'])
            task.custom_title = meta['safe_anime_title']
            if meta.get('direct_quality'):
                task.custom_quality = meta['direct_quality']
                task.quality_badge = meta['direct_quality']
            elif meta.get('available_qualities'):
                task.custom_quality = str(meta['available_qualities'][0])
                task.quality_badge = task.custom_quality
            task.referer = meta.get('url')
            if meta.get('poster_url'):
                task.thumbnail_url = meta['poster_url']
            task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
            self.tasks.append(task)
            self.task_added.emit(task)
            self.fetch_video_info(task)
            if task.thumbnail_url:
                self.queue_thumbnail_load(task.thumbnail_url, task)
            self.start_task(task)
            self._update_summary()
        else:
            task = DownloadTask(url)
            task.set_error("Видео не найдено.")
            self.tasks.append(task)
            self.task_added.emit(task)
            self._update_summary()

    def _start_kinopub_from_bot(self, meta, selected_v_obj, selected_quality, targets):
        url = meta['url']
        post_id = meta.get('post_id')
        seasons = meta.get('seasons', [])
        is_movie = meta.get('is_movie', False)
        selected_voice = str(selected_v_obj.get('id', '59') if isinstance(selected_v_obj, dict) else selected_v_obj or '59')
        safe_v_name = re.sub(r'[\\/*?:"<>|]', "", selected_v_obj.get('name', 'Default') if isinstance(selected_v_obj, dict) else 'Default')
        safe_s_name = re.sub(r'[\\/*?:"<>|]', "", seasons[0].get('name', '1 Сезон') if seasons else '1 Сезон')
        selected_season = str(seasons[0].get('id', '1') if seasons else '1')

        if post_id:
            logger.info(f"[KinoPub-Bot] Запуск сбора ссылок: '{meta.get('safe_anime_title')}', озвучка: {safe_v_name}, серий: {len(targets)}")
            self.status_updated.emit(f"KinoPub: сбор ссылок для {len(targets)} серий...")
            series_worker = KinoPubSeriesWorker(
                url=url,
                post_id=post_id,
                selected_voice=selected_voice,
                selected_season=selected_season,
                selected_quality=selected_quality,
                safe_anime_title=meta['safe_anime_title'],
                safe_v_name=safe_v_name,
                safe_s_name=safe_s_name,
                is_movie=is_movie,
                targets=targets,
                cookies=meta.get('cookies', []),
                favs=meta.get('favs', ''),
                settings=self.settings
            )
            self._active_series_workers.append(series_worker)

            def on_series_success(res, w=series_worker):
                if w in self._active_series_workers:
                    self._active_series_workers.remove(w)
                self._on_kinopub_series_finished(res, is_from_bot=True)

            def on_series_failed(err, w=series_worker):
                if w in self._active_series_workers:
                    self._active_series_workers.remove(w)
                self._on_kinopub_series_error(err, is_from_bot=True)

            series_worker.signals.finished.connect(on_series_success)
            series_worker.signals.error.connect(on_series_failed)
            self.thread_pool.start(series_worker)
        elif meta.get('direct_url'):
            task = DownloadTask(meta['direct_url'])
            task.is_from_bot = True
            task.custom_title = meta.get('safe_anime_title')
            task.custom_quality = selected_quality or meta.get('direct_quality') or '1080p'
            task.quality_badge = task.custom_quality
            task.referer = meta.get('url')
            if meta.get('poster_url'):
                task.thumbnail_url = meta['poster_url']
            task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
            self.tasks.append(task)
            self.task_added.emit(task)
            self.fetch_video_info(task)
            if task.thumbnail_url:
                self.queue_thumbnail_load(task.thumbnail_url, task)
            self.start_task(task)
            self._update_summary()

    def _on_kinopub_series_finished(self, results, is_from_bot=False):
        logger.info(f"[KinoPub] Завершение сбора серий: получено {len(results) if results else 0} рабочих ссылок.")
        if results:
            poster = getattr(self, '_current_kinopub_poster', None)
            new_tasks = []
            for res in results:
                task = DownloadTask(res['url'])
                task.is_from_bot = is_from_bot
                task.custom_title = res['title']
                if res.get('quality'):
                    task.custom_quality = res['quality']
                    task.quality_badge = res['quality']
                if res.get('referer'):
                    task.referer = res['referer']
                if poster:
                    task.thumbnail_url = poster
                task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
                self.tasks.append(task)
                self.task_added.emit(task)
                self.fetch_video_info(task)
                if task.thumbnail_url:
                    self.queue_thumbnail_load(task.thumbnail_url, task)
                new_tasks.append(task)
                logger.info(f"[KinoPub] Добавлена серия в очередь: '{task.custom_title}' [{task.quality_badge}]")

            self.is_downloading_active = True
            self.download_started.emit()
            self.status_updated.emit(f"Добавлено серий: {len(results)}. Запуск загрузки...")
            for t in new_tasks:
                logger.info(f"[KinoPub] Запуск загрузки для: '{t.custom_title}'")
                self.start_task(t)
        else:
            logger.warning("[KinoPub] Список серий пуст — ни одна ссылка не была получена.")
            self.status_updated.emit("Не удалось получить ссылки на серии.")
            if is_from_bot and hasattr(self, 'bot_manager') and self.bot_manager:
                self.bot_manager.send_message("❌ Не удалось получить ссылки на выбранные серии KinoPub.")
            elif self.parent_window:
                QMessageBox.warning(self.parent_window, "KinoPub", "Не удалось получить рабочие ссылки на выбранные серии.")
        self._update_summary()

    def _on_kinopub_series_error(self, err, is_from_bot=False):
        logger.error(f"[KinoPub] Ошибка сбора ссылок на серии: {err}")
        self.status_updated.emit(f"Ошибка получения серий: {err}")
        if is_from_bot and hasattr(self, 'bot_manager') and self.bot_manager:
            self.bot_manager.send_message(f"❌ Ошибка KinoPub / Rezka:\n{err}")
        elif self.parent_window:
            QMessageBox.critical(self.parent_window, "Ошибка KinoPub / Rezka", f"Не удалось получить ссылки на серии:\n\n{err}")
        self._update_summary()

    def _on_kinopub_error(self, url, err):
        info = format_kinopub_error(str(err))
        task = DownloadTask(url)
        task.set_error(info['short_status'])
        self.tasks.append(task)
        self.task_added.emit(task)
        self._update_summary()