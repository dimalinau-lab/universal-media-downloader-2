import os
import re
import json
import time
import logging
import threading
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)

_DOMAIN_SNIFFER_LOCK = threading.Lock()
_DOMAIN_SNIFFER_CACHE: dict[str, str] = {}


def get_domain_sniffer_hint(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    with _DOMAIN_SNIFFER_LOCK:
        return _DOMAIN_SNIFFER_CACHE.get(host)


def set_domain_sniffer_hint(url: str, method: str | None):
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return
    with _DOMAIN_SNIFFER_LOCK:
        if method:
            _DOMAIN_SNIFFER_CACHE[host] = method
        else:
            _DOMAIN_SNIFFER_CACHE.pop(host, None)


def clear_domain_sniffer_cache():
    with _DOMAIN_SNIFFER_LOCK:
        _DOMAIN_SNIFFER_CACHE.clear()

BROWSER_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/131.0.0.0 Safari/537.36'
)

# Домены рекламы, счетчиков и телеметрии, которые необходимо строго игнорировать
AD_DOMAINS = {
    'doubleclick.net', 'google-analytics.com', 'googlesyndication.com',
    'mc.yandex.ru', 'an.yandex.ru', 'adriver.ru', 'adfox.ru', 'adroll.com',
    'scorecardresearch.com', 'clarity.ms', 'hotjar.com', 'sentry.io',
    'top-fwz1.mail.ru', 'counter.yadro.ru', 'facebook.com/tr',
    'criteo.com', 'outbrain.com', 'taboola.com', 'pubmatic.com',
    'rubiconproject.com', 'smartadserver.com', 'openx.net', 'moatads.com',
    'rtb.com', 'adsterra.com', 'propellerads.com', 'popads.net'
}

MEDIA_EXTENSIONS = ('.m3u8', '.mpd', '.mp4', '.webm', '.m4a', '.mp3', '.ogg', '.opus', '.flac')
MEDIA_CONTENT_TYPES = (
    'video/', 'audio/',
    'application/vnd.apple.mpegurl',
    'application/x-mpegurl',
    'application/dash+xml'
)


def is_ad_or_tracking(url: str) -> bool:
    """
    Проверяет, является ли URL рекламой или трекером.
    """
    u_lower = url.lower()
    parsed = urlparse(u_lower)
    hostname = parsed.hostname or ""

    for ad_d in AD_DOMAINS:
        if ad_d in hostname or ad_d in u_lower:
            return True

    # Проверка ключевых слов рекламы в пути/параметрах
    if any(k in u_lower for k in ('/ad/', '/ads/', 'adv_', 'pre-roll', 'preroll', 'vast', 'vpaid', '/promo/')):
        return True

    return False


def is_candidate_media_url(url: str, content_type: str = "") -> bool:
    """
    Проверяет, указывает ли URL или Content-Type на медиапоток.
    """
    if is_ad_or_tracking(url):
        return False

    clean_url = url.split('?')[0].lower()
    if clean_url.endswith(MEDIA_EXTENSIONS):
        return True

    if content_type:
        ct_lower = content_type.lower()
        if any(mct in ct_lower for mct in MEDIA_CONTENT_TYPES):
            # Исключаем изображения
            if 'image/' not in ct_lower and not clean_url.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp')):
                return True

    return False


_PREVIEW_URL_HINTS = (
    'preview', 'teaser', 'trailer', 'preroll', 'pre-roll', 'sample',
    'bumper', 'intro_clip', 'thumb_video', 'hover_video', 'storyboards'
)

_PRESERVED_TOKEN_HEADERS = (
    'authorization', 'x-access-token', 'x-csrf-token', 'x-xsrf-token',
    'x-playback-session-id', 'x-requested-with', 'x-auth-token',
    'x-api-key', 'x-signature', 'x-token'
)


def is_preview_or_trailer_url(url: str) -> bool:
    u_low = (url or "").lower()
    return any(hint in u_low for hint in _PREVIEW_URL_HINTS)


def detect_drm_in_manifest(body: str) -> str | None:
    """Обнаруживает признаки коммерческого DRM (Widevine, PlayReady, FairPlay, CENC) в HLS/DASH манифесте."""
    if not body:
        return None
    low = body.lower()
    if '<contentprotection' in low or 'cenc:default_kid' in low or 'edef8ba9-79d6-4ace-a3c8-27dcd51d21ed' in low or '9a04f079-9840-4286-ab92-e65be0885f95' in low:
        return 'Widevine/PlayReady'
    if 'method=sample-aes' in low or 'skd://' in low or 'com.widevine' in low:
        return 'FairPlay/Widevine'
    return None


def classify_sniffer_failure(diagnostics: dict | None) -> tuple[str, str]:
    """Возвращает (код_причины, понятное_сообщение <= 110 символов) по диагностике сниффера."""
    d = diagnostics or {}
    if d.get('drm_detected'):
        return ('drm', f"Поток защищён DRM ({d['drm_detected']}) — скачивание невозможно")
    if d.get('network_timeout'):
        return ('timeout', "Сайт не отвечает (таймаут соединения) — проверьте доступ или VPN")
    http_status = d.get('http_status')
    if d.get('challenge_detected') or http_status in (403, 429, 503):
        return ('antibot', "Сработала антибот-защита — нажмите 🌐 для ручного перехвата")
    return ('not_found', "Поток не найден — нажмите 🌐 на карточке для запуска плеера вручную")


def estimate_hls_duration(body: str) -> float:
    """Суммирует длительности #EXTINF сегментов в медиа-плейлисте HLS."""
    if not body:
        return 0.0
    total = 0.0
    for m in re.finditer(r'#EXTINF:\s*([0-9]+(?:\.[0-9]+)?)', body):
        try:
            total += float(m.group(1))
        except ValueError:
            pass
    return total


def parse_hls_master_qualities(m3u8_text: str, base_url: str) -> dict[str, str]:
    """Извлекает варианты разрешений ('1080p' -> url) из HLS #EXT-X-STREAM-INF мастер-плейлиста."""
    if not m3u8_text or '#EXT-X-STREAM-INF' not in m3u8_text:
        return {}
    variants: list[tuple[int, str]] = []
    lines = [ln.strip() for ln in m3u8_text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith('#EXT-X-STREAM-INF:'):
            res_m = re.search(r'RESOLUTION=\s*\d+x(\d+)', line, re.I)
            height = int(res_m.group(1)) if res_m else 0
            # Следующая непустая строка без # — URL варианта
            for j in range(i + 1, len(lines)):
                cand = lines[j]
                if not cand:
                    continue
                if cand.startswith('#'):
                    continue
                abs_url = urljoin(base_url, cand)
                if height > 0:
                    variants.append((height, abs_url))
                break
    variants.sort(key=lambda x: x[0], reverse=True)
    result: dict[str, str] = {}
    for h, v_url in variants:
        key = f"{h}p"
        if key not in result:
            result[key] = v_url
    return result


def score_captured_stream(stream: dict) -> int:
    """Ранжирует перехваченные медиапотоки: мастер HLS > обычный HLS > DASH > MP4, с понижением прероллов."""
    u = (stream.get('url') or '').lower()
    score = 1
    if stream.get('is_hls'):
        score = 8
        if stream.get('is_master') or 'master' in u or 'hls.m3u8' in u or 'manifest' in u:
            score = 15
    elif stream.get('is_dash'):
        score = 6
    elif '.mp4' in u or '.webm' in u:
        score = 5

    if is_preview_or_trailer_url(u):
        score -= 10

    hls_dur = stream.get('hls_duration')
    if isinstance(hls_dur, (int, float)) and hls_dur > 0:
        if hls_dur < 15.0 and not stream.get('is_master'):
            score -= 8
        elif hls_dur >= 30.0:
            score += 4

    return score


def build_preserved_headers(raw_headers: dict | None, page_url: str) -> dict:
    """Формирует заголовки для скачивания, сохраняя Referer, Origin и токен/авторизационные заголовки."""
    raw = raw_headers or {}
    lower_map = {str(k).lower(): (str(k), str(v)) for k, v in raw.items() if v}

    ref = (lower_map.get('referer', ('', ''))[1]) or page_url
    parsed_ref = urlparse(ref)
    default_origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}" if parsed_ref.scheme and parsed_ref.netloc else ""
    origin = (lower_map.get('origin', ('', ''))[1]) or default_origin
    ua = (lower_map.get('user-agent', ('', ''))[1]) or BROWSER_USER_AGENT

    headers = {'User-Agent': ua, 'Referer': ref}
    if origin:
        headers['Origin'] = origin

    for hk_low, (orig_k, val) in lower_map.items():
        if hk_low == 'authorization':
            headers['Authorization'] = val
        elif hk_low in _PRESERVED_TOKEN_HEADERS or hk_low.startswith(('x-auth', 'x-token', 'x-sign')):
            headers[orig_k] = val
    return headers


def _normalize_extracted_url(raw_url: str, base_url: str) -> str:
    if not raw_url:
        return ""
    u = raw_url.strip().replace(r'\/', '/').rstrip(';,"\'\\')
    if u.startswith('//'):
        scheme = urlparse(base_url).scheme or 'https'
        u = f"{scheme}:{u}"
    elif u.startswith('/'):
        u = urljoin(base_url, u)
    return u


def _collect_jsonld_urls(node, out_streams: list[str], out_embeds: list[str]):
    if isinstance(node, list):
        for item in node:
            _collect_jsonld_urls(item, out_streams, out_embeds)
    elif isinstance(node, dict):
        c_url = node.get('contentUrl')
        if isinstance(c_url, str) and c_url.strip():
            out_streams.append(c_url.strip())
        e_url = node.get('embedUrl')
        if isinstance(e_url, str) and e_url.strip():
            out_embeds.append(e_url.strip())
        for val in node.values():
            if isinstance(val, (dict, list)):
                _collect_jsonld_urls(val, out_streams, out_embeds)


def extract_streams_from_html(html: str, base_url: str) -> tuple[str, list[dict], list[str]]:
    """
    Извлекает (title, candidates, iframe_urls) из HTML:
    OpenGraph, JSON-LD, <video>/<source> (src/data-src), inline-скрипты (с учетом экранирования \\/).
    """
    if not html:
        return "", [], []

    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
    title = re.sub(r'[\r\n\t]+', ' ', title_match.group(1)).strip() if title_match else ""

    candidates: list[dict] = []
    seen_urls: set[str] = set()

    def _add_cand(raw_u: str, method: str):
        cand = _normalize_extracted_url(raw_u, base_url)
        if not cand.startswith('http') or is_ad_or_tracking(cand) or cand in seen_urls:
            return
        seen_urls.add(cand)
        low = cand.lower()
        candidates.append({
            'url': cand,
            'method': method,
            'is_hls': '.m3u8' in low,
            'is_dash': '.mpd' in low,
        })

    # 1. OpenGraph
    for pat in (
        r'<meta\s+[^>]*property=["\']og:video(?::secure_url|:url)?["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta\s+[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:video(?::secure_url|:url)?["\']',
    ):
        for m in re.finditer(pat, html, re.I):
            _add_cand(m.group(1), 'fast_opengraph')

    # 2. JSON-LD (schema.org VideoObject)
    jsonld_embeds: list[str] = []
    for jm in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
        try:
            payload = json.loads(jm.group(1).strip())
            ld_streams: list[str] = []
            _collect_jsonld_urls(payload, ld_streams, jsonld_embeds)
            for s in ld_streams:
                _add_cand(s, 'fast_jsonld')
        except Exception:
            pass

    # 3. <video> / <source> (src и data-src)
    for m in re.finditer(r'<(?:video|source)[^>]+(?:data-src|src)=["\']([^"\']+\.(?:m3u8|mpd|mp4|webm)[^"\']*)["\']', html, re.I):
        _add_cand(m.group(1), 'fast_html_video')

    # 4. Inline-скрипты и конфиги плееров (с разэкранированием \/)
    clean_html = html.replace(r'\/', '/')
    for m in re.finditer(r'["\']((?:https?:)?//[^"\'\s<>]+\.(?:m3u8|mpd)(?:\?[^"\'\s<>]*)?)["\']', clean_html, re.I):
        _add_cand(m.group(1), 'fast_inline_stream')
    for m in re.finditer(r'["\']((?:https?:)?//[^"\'\s<>]+\.(?:mp4|webm)(?:\?[^"\'\s<>]*)?)["\']', clean_html, re.I):
        _add_cand(m.group(1), 'fast_inline_mp4')

    # 5. Iframes + JSON-LD embedUrl
    iframes: list[str] = []
    for m in re.finditer(r'<(?:iframe|li)[^>]+(?:src|data-src|data-url)=["\']([^"\']*(?:embed|player|video|cdn|stream)[^"\']*)["\']', html, re.I):
        u_norm = _normalize_extracted_url(m.group(1), base_url)
        if u_norm.startswith('http') and not is_ad_or_tracking(u_norm) and u_norm not in iframes:
            iframes.append(u_norm)
    for emb in jsonld_embeds:
        u_norm = _normalize_extracted_url(emb, base_url)
        if u_norm.startswith('http') and not is_ad_or_tracking(u_norm) and u_norm not in iframes:
            iframes.append(u_norm)

    candidates.sort(key=score_captured_stream, reverse=True)
    return title, candidates, iframes


def get_browser_cookies_for_domain(url: str) -> list[dict]:
    """
    Универсальное извлечение куков для домена из установленных на ПК браузеров
    (Edge, Chrome, Yandex) для прозрачного обхода Cloudflare Turnstile и авторизаций.
    """
    try:
        from .browser_cookies import extract_cookies_live, detect_installed_browsers
        domain = urlparse(url).hostname or ""
        if not domain:
            return []

        parts = domain.split('.')
        base_domain = '.'.join(parts[-2:]) if len(parts) >= 2 else domain

        installed = [k for k, _ in detect_installed_browsers()]
        cookie_list = []
        for b_key in ['edge', 'chrome', 'yandex', 'brave', 'opera']:
            if b_key in installed:
                raw_cookies = extract_cookies_live(b_key, domain_filter=base_domain)
                if raw_cookies:
                    for c in raw_cookies:
                        cookie_list.append({
                            'name': c['name'],
                            'value': c['value'],
                            'domain': c['domain'],
                            'path': c.get('path', '/'),
                            'secure': c.get('secure', False)
                        })
                    logger.debug(f"[UniversalSniffer] Получено {len(cookie_list)} куков для {base_domain} из {b_key}.")
                    break
        return cookie_list
    except Exception as e:
        logger.debug(f"[UniversalSniffer] Ошибка извлечения куков браузера: {e}")
        return []


class FastMetaSniffer:
    """
    Уровень 3.1: Сверхбыстрый анализ HTML/DOM, JSON-LD и OpenGraph через curl_cffi с имитацией TLS Chrome.
    """
    @staticmethod
    def sniff(url: str, timeout: int = 5, is_cancelled=None, diagnostics: dict | None = None) -> dict | None:
        if is_cancelled and is_cancelled():
            return None
        try:
            from curl_cffi import requests
        except ImportError:
            return None

        try:
            if is_cancelled and is_cancelled():
                return None
            session = requests.Session(impersonate="chrome124")
            for ck in get_browser_cookies_for_domain(url):
                try:
                    session.cookies.set(ck['name'], ck['value'], domain=ck.get('domain', ''), path=ck.get('path', '/'))
                except Exception:
                    pass

            resp = session.get(
                url,
                headers={'User-Agent': BROWSER_USER_AGENT, 'Referer': url},
                timeout=timeout,
                allow_redirects=True
            )
            if diagnostics is not None:
                diagnostics['http_status'] = resp.status_code
            if resp.status_code != 200 or not resp.text:
                if diagnostics is not None and resp.text:
                    low_t = resp.text[:2500].lower()
                    if any(k in low_t for k in ('cf-browser-verification', 'just a moment', 'turnstile', 'within.website')):
                        diagnostics['challenge_detected'] = True
                return None

            title, candidates, iframes = extract_streams_from_html(resp.text, url)
            cookies_dict = dict(session.cookies.get_dict())

            if candidates:
                best = candidates[0]
                return {
                    'url': best['url'],
                    'title': title or "Web Stream",
                    'headers': build_preserved_headers({'Referer': url}, url),
                    'cookies': cookies_dict,
                    'is_hls': best['is_hls'],
                    'is_dash': best['is_dash'],
                    'method': best['method'],
                }

            for ifr_url in iframes[:6]:
                if is_cancelled and is_cancelled():
                    return None
                try:
                    sub_resp = session.get(
                        ifr_url,
                        headers={'User-Agent': BROWSER_USER_AGENT, 'Referer': url},
                        timeout=3,
                        allow_redirects=True
                    )
                    if sub_resp.status_code == 200 and sub_resp.text:
                        _, sub_cands, _ = extract_streams_from_html(sub_resp.text, ifr_url)
                        if sub_cands:
                            best_sub = sub_cands[0]
                            all_cookies = dict(session.cookies.get_dict())
                            return {
                                'url': best_sub['url'],
                                'title': title or "Web Stream",
                                'headers': build_preserved_headers({'Referer': ifr_url}, ifr_url),
                                'cookies': all_cookies,
                                'is_hls': best_sub['is_hls'],
                                'is_dash': best_sub['is_dash'],
                                'method': f"{best_sub['method']}_iframe",
                            }
                except Exception:
                    pass

        except Exception as e:
            err_l = str(e).lower()
            if diagnostics is not None and any(k in err_l for k in ('timed out', 'timeout', 'curl: (28)', 'could not resolve', 'connection refused')):
                diagnostics['network_timeout'] = True
            logger.debug(f"[FastMetaSniffer] Ошибка анализа: {e}")

        return None


class HeadlessEdgeSniffer:
    """
    Уровень 3.2: Интеллектуальный сниффер сетевого трафика через Playwright и системный Edge/Chromium.
    Поддерживает скрытый (headless) и интерактивный (headless=False) режимы.
    """
    @staticmethod
    def sniff(url: str, timeout: int = 18, status_callback=None, is_cancelled=None, diagnostics: dict | None = None) -> dict | None:
        return HeadlessEdgeSniffer._run_playwright(
            url, timeout=timeout, headless=True, status_callback=status_callback, is_cancelled=is_cancelled, diagnostics=diagnostics
        )

    @staticmethod
    def _run_playwright(url: str, timeout: int = 18, headless: bool = True, status_callback=None, is_cancelled=None, diagnostics: dict | None = None) -> dict | None:
        if is_cancelled and is_cancelled():
            return None
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            import sys
            is_frozen = getattr(sys, 'frozen', False)
            if not is_frozen:
                if status_callback:
                    status_callback("Первичная настройка движка браузера (playwright)...")
                try:
                    import subprocess
                    logger.info("[HeadlessEdgeSniffer] Автоматическая установка playwright в окружение...")
                    subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True, capture_output=True, timeout=60)
                    from playwright.sync_api import sync_playwright
                except Exception as auto_err:
                    logger.warning(f"[HeadlessEdgeSniffer] Библиотека playwright не установлена: {auto_err}")
                    return None
            else:
                logger.warning("[HeadlessEdgeSniffer] Playwright не обнаружен в скомпилированном пакете.")
                return None

        if status_callback:
            status_callback(
                "Инициализация защищенного браузера Edge..." if headless
                else "Откройте видео / пройдите проверку в окне браузера..."
            )

        captured_streams: list[dict] = []

        try:
            with sync_playwright() as p:
                browser = None
                launch_args = [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-infobars',
                    '--disable-dev-shm-usage',
                    '--disable-extensions',
                    '--window-size=1280,800' if not headless else '--window-size=1920,1080',
                ]
                if headless:
                    launch_args.extend([
                        '--disable-gpu',
                        '--mute-audio',
                        '--disable-background-timer-throttling',
                        '--disable-backgrounding-occluded-windows',
                        '--disable-renderer-backgrounding',
                    ])

                # Приоритет: системный Microsoft Edge (встроен в Windows без загрузки бинарников), затем Chrome
                for channel in ['msedge', 'chrome', None]:
                    try:
                        kwargs = {
                            'headless': headless,
                            'args': launch_args
                        }
                        if channel:
                            kwargs['channel'] = channel
                        browser = p.chromium.launch(**kwargs)
                        break
                    except Exception as launch_err:
                        logger.debug(f"[HeadlessEdgeSniffer] Канал {channel} не запустился: {launch_err}")

                if not browser:
                    logger.error("[HeadlessEdgeSniffer] Не удалось запустить Chromium/Edge браузер.")
                    return None

                context = browser.new_context(
                    user_agent=BROWSER_USER_AGENT,
                    viewport={'width': 1920, 'height': 1080} if headless else None,
                    locale='ru-RU',
                    timezone_id='Europe/Moscow',
                    ignore_https_errors=True
                )

                # Stealth-скрипты: обход анти-бот систем (Cloudflare Turnstile, DataDome, etc.)
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = {
                        runtime: {},
                        loadTimes: function() {},
                        csi: function() {},
                        app: {}
                    };
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] });
                    const origPerm = window.navigator.permissions.query;
                    if (origPerm) {
                        window.navigator.permissions.query = (p) => (
                            p.name === 'notifications' ?
                                Promise.resolve({ state: Notification.permission }) :
                                origPerm(p)
                        );
                    }
                """)

                # Инжекция сохраненных куков из браузера пользователя
                user_cookies = get_browser_cookies_for_domain(url)
                if user_cookies:
                    try:
                        context.add_cookies(user_cookies)
                    except Exception as err_c:
                        logger.debug(f"[HeadlessEdgeSniffer] Ошибка подстановки куков: {err_c}")

                page = context.new_page()
                page.on('dialog', lambda dialog: dialog.dismiss())

                # Защита от рекламных попапов/попандеров при кликах по плееру
                def on_popup(popup_page):
                    try:
                        if popup_page is not page:
                            popup_page.close()
                    except Exception:
                        pass

                context.on('page', on_popup)

                def _upsert_stream(entry: dict):
                    for existing in captured_streams:
                        if existing['url'] == entry['url']:
                            for k in ('is_master', 'hls_duration', 'variants'):
                                if entry.get(k) and not existing.get(k):
                                    existing[k] = entry[k]
                            if entry.get('headers') and len(entry['headers']) > len(existing.get('headers', {})):
                                existing['headers'] = entry['headers']
                            return
                    captured_streams.append(entry)

                # 1. Перехват сетевых запросов
                def on_request(req):
                    req_url = req.url
                    if is_candidate_media_url(req_url):
                        _upsert_stream({
                            'url': req_url,
                            'headers': dict(req.headers),
                            'is_hls': '.m3u8' in req_url.lower(),
                            'is_dash': '.mpd' in req_url.lower(),
                            'source': 'direct_req'
                        })

                # 2. Перехват сетевых ответов (включая сигнатуры #EXTM3U / <MPD и JSON API плееров)
                def on_response(resp):
                    try:
                        resp_url = resp.url
                        if is_ad_or_tracking(resp_url):
                            return

                        ct = resp.headers.get('content-type', '').lower()
                        status = resp.status
                        cand_by_url = is_candidate_media_url(resp_url, content_type=ct)

                        body_checked = False
                        body = ""
                        is_text_like = any(
                            t in ct for t in (
                                'application/json', 'text/plain', 'text/javascript',
                                'application/javascript', 'mpegurl', 'dash', 'xml', 'octet-stream'
                            )
                        )
                        if cand_by_url or (status == 200 and (is_text_like or not ct)):
                            cl = resp.headers.get('content-length')
                            if not cl or (cl.isdigit() and int(cl) <= 1024 * 512):
                                try:
                                    body = resp.text()
                                    body_checked = True
                                except Exception:
                                    body = ""

                        # 2a. Проверка по сигнатуре тела (#EXTM3U / <MPD) даже без расширения .m3u8/.mpd в URL
                        if body_checked and body:
                            head_strip = body[:400].lstrip()
                            if head_strip.startswith('#EXTM3U'):
                                drm_kind = detect_drm_in_manifest(body)
                                if drm_kind:
                                    if diagnostics is not None:
                                        diagnostics['drm_detected'] = drm_kind
                                    logger.warning(f"[HeadlessEdgeSniffer] Обнаружен DRM ({drm_kind}) в HLS: {resp_url}")
                                    return
                                is_master = '#EXT-X-STREAM-INF' in body
                                variants = parse_hls_master_qualities(body, resp_url) if is_master else {}
                                hls_dur = 0.0 if is_master else estimate_hls_duration(body)
                                _upsert_stream({
                                    'url': resp_url,
                                    'headers': dict(resp.request.headers),
                                    'is_hls': True,
                                    'is_dash': False,
                                    'is_master': is_master,
                                    'hls_duration': hls_dur,
                                    'variants': variants,
                                    'source': 'sig_extm3u' if not cand_by_url else 'media_resp',
                                })
                                return
                            if '<MPD' in head_strip:
                                drm_kind = detect_drm_in_manifest(body)
                                if drm_kind:
                                    if diagnostics is not None:
                                        diagnostics['drm_detected'] = drm_kind
                                    logger.warning(f"[HeadlessEdgeSniffer] Обнаружен DRM ({drm_kind}) в MPD: {resp_url}")
                                    return
                                _upsert_stream({
                                    'url': resp_url,
                                    'headers': dict(resp.request.headers),
                                    'is_hls': False,
                                    'is_dash': True,
                                    'is_master': True,
                                    'source': 'sig_mpd' if not cand_by_url else 'media_resp',
                                })
                                return

                        # 2b. Медиапоток по URL / Content-Type
                        if cand_by_url:
                            _upsert_stream({
                                'url': resp_url,
                                'headers': dict(resp.request.headers),
                                'is_hls': '.m3u8' in resp_url.lower() or 'mpegurl' in ct,
                                'is_dash': '.mpd' in resp_url.lower() or 'dash' in ct,
                                'source': 'media_resp'
                            })
                            return

                        # 2c. Анализ ответов API плееров (Playerjs, VideoJS, JWPlayer, etc.)
                        if body_checked and body and any(ext in body.lower() for ext in ('.m3u8', '.mpd', '.mp4')):
                            clean_body = body.replace(r'\/', '/')
                            matches = re.findall(r'https?://[^\s"\'<>\\]+\.(?:m3u8|mpd|mp4)[^\s"\'<>\\]*', clean_body, re.I)
                            for cand in matches:
                                cand = cand.rstrip(';,"')
                                if not is_ad_or_tracking(cand):
                                    logger.info(f"[HeadlessEdgeSniffer] Медиапоток найден в ответе API ({resp_url}): {cand}")
                                    _upsert_stream({
                                        'url': cand,
                                        'headers': dict(resp.request.headers),
                                        'is_hls': '.m3u8' in cand.lower(),
                                        'is_dash': '.mpd' in cand.lower(),
                                        'source': 'api_payload'
                                    })
                    except Exception as err_resp:
                        logger.debug(f"[HeadlessEdgeSniffer] Ошибка анализа ответа: {err_resp}")

                page.on('request', on_request)
                page.on('response', on_response)

                if status_callback:
                    status_callback(
                        "Загрузка страницы и обход защиты..." if headless
                        else "Войдите на сайт или нажмите Play в открывшемся окне..."
                    )

                nav_timed_out = False
                nav_timeout_ms = (min(timeout, 10) if headless else min(timeout, 25)) * 1000
                try:
                    page.goto(url, timeout=nav_timeout_ms, wait_until='commit')
                except Exception as nav_err:
                    nav_err_str = str(nav_err).lower()
                    if 'timeout' in nav_err_str or 'err_timed_out' in nav_err_str or 'err_connection' in nav_err_str:
                        nav_timed_out = True
                        if diagnostics is not None:
                            diagnostics['network_timeout'] = True
                    logger.debug(f"[HeadlessEdgeSniffer] Ошибка перехода: {nav_err}")

                if nav_timed_out and not captured_streams:
                    try:
                        browser.close()
                    except Exception:
                        pass
                    return None

                start_time = time.time()
                native_clicked = False

                # Цикл обнаружения и взаимодействия
                while time.time() - start_time < timeout:
                    if page.is_closed() or (is_cancelled and is_cancelled()):
                        logger.info("[HeadlessEdgeSniffer] Отмена или закрытие окна сниффера.")
                        try:
                            browser.close()
                        except Exception:
                            pass
                        return None

                    elapsed = time.time() - start_time

                    # Не обрываемся слишком рано, если пойман только трейлер/превью
                    non_preview_high = [
                        s for s in captured_streams
                        if (s.get('is_hls') or s.get('is_dash'))
                        and not is_preview_or_trailer_url(s.get('url', ''))
                        and (s.get('hls_duration', 0) == 0 or s.get('hls_duration', 0) >= 15.0 or s.get('is_master'))
                    ]
                    if any(s.get('is_master') for s in non_preview_high):
                        time.sleep(0.8)
                        break
                    if non_preview_high and elapsed >= 2.2:
                        time.sleep(0.9)
                        break
                    if captured_streams and elapsed > (12.0 if not headless else 6.0):
                        break

                    if headless and elapsed >= 1.5:
                        if status_callback and elapsed < 3.0:
                            status_callback("Активация плееров и перехват медиапотока...")

                        # 1. Активация ленивых iframe плееров (lazy-load)
                        try:
                            page.evaluate("""() => {
                                document.querySelectorAll('iframe').forEach(ifr => {
                                    const dataSrc = ifr.getAttribute('data-src') || ifr.getAttribute('data-lazy-src') || ifr.getAttribute('data-original') || ifr.getAttribute('data-url');
                                    if (dataSrc && (!ifr.src || ifr.src === 'about:blank')) {
                                        ifr.src = dataSrc;
                                    }
                                    try { ifr.scrollIntoView({behavior: 'instant', block: 'center'}); } catch(e){}
                                });
                                window.scrollBy(0, 300);
                            }""")
                        except Exception:
                            pass

                        # 2. Симуляция запуска плеера во всех дочерних фреймах
                        for frame in page.frames:
                            try:
                                frame.evaluate("""() => {
                                    document.querySelectorAll('video').forEach(v => {
                                        try { v.muted = true; v.play(); } catch(e){}
                                    });
                                    if (window.player && typeof window.player.api === 'function') {
                                        try { window.player.api('play'); } catch(e){}
                                    }
                                    if (window.playerjs && typeof window.playerjs.api === 'function') {
                                        try { window.playerjs.api('play'); } catch(e){}
                                    }
                                    const selectors = [
                                        '.vjs-big-play-button',
                                        'button[class*="play"]',
                                        '[aria-label*="play" i]',
                                        '.play-button',
                                        '.player-start',
                                        '#oframeplayer',
                                        '#player',
                                        'pjsdiv[id*="player"]',
                                        '.fp-play',
                                        'div[class*="play" i]'
                                    ];
                                    for (const sel of selectors) {
                                        const el = document.querySelector(sel);
                                        if (el) {
                                            try {
                                                el.click();
                                                ['mousedown', 'mouseup', 'click'].forEach(evt => {
                                                    el.dispatchEvent(new MouseEvent(evt, {bubbles: true, cancelable: true, view: window}));
                                                });
                                            } catch(e){}
                                        }
                                    }
                                    const watchLabels = ['смотреть', 'дивитись', 'дивитися', 'watch', 'play'];
                                    document.querySelectorAll('button, a[role="button"], a[class*="btn"], a[class*="play"], div[role="button"]').forEach(btn => {
                                        const txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                                        if (txt && txt.length <= 28 && watchLabels.some(lbl => txt === lbl || txt.startsWith(lbl + ' '))) {
                                            try { btn.click(); } catch(e){}
                                        }
                                    });
                                }""")
                            except Exception:
                                pass

                        # 3. Нативный доверенный клик Playwright (isTrusted = true), если JS-клик не сработал
                        if not native_clicked and elapsed >= 2.8 and not captured_streams:
                            native_clicked = True
                            for sel in (
                                '.vjs-big-play-button',
                                'button[class*="play"]',
                                '.play-button',
                                'button:has-text("Смотреть")',
                                'button:has-text("Дивитись")',
                                'button:has-text("Watch")',
                                'a:has-text("Смотреть")',
                                'a:has-text("Дивитись")',
                                '#player',
                                'video',
                                'iframe[src*="player"], iframe[src*="embed"], iframe',
                            ):
                                try:
                                    loc = page.locator(sel).first
                                    if loc.count() > 0 and loc.is_visible():
                                        loc.click(timeout=800, force=True)
                                        break
                                except Exception:
                                    pass

                    time.sleep(0.4)

                page_title = ""
                try:
                    if not page.is_closed():
                        page_title = page.title()
                        if diagnostics is not None and not captured_streams:
                            low_title = page_title.lower()
                            if any(k in low_title for k in ('just a moment', 'attention required', 'о, привет')):
                                diagnostics['challenge_detected'] = True
                            else:
                                html_head = page.content()[:3000].lower()
                                if any(k in html_head for k in ('cf-browser-verification', 'turnstile', 'within.website')):
                                    diagnostics['challenge_detected'] = True
                except Exception:
                    pass

                cookies_dict = {}
                try:
                    cookies = context.cookies()
                    for c in cookies:
                        cookies_dict[c['name']] = c['value']
                except Exception:
                    pass

                browser.close()

                if captured_streams:
                    captured_streams.sort(key=score_captured_stream, reverse=True)
                    best = captured_streams[0]

                    clean_title = re.sub(r'[\r\n\t]+', ' ', page_title).strip()
                    clean_title = re.sub(r'(?:смотреть онлайн|бесплатно в хорошем качестве|hd|720p|1080p|»|\(.*?\)).*$', '', clean_title, flags=re.I).strip()
                    clean_title = re.sub(r'[\\/*?:"<>|]', "", clean_title).strip()
                    if not clean_title or len(clean_title) < 2:
                        clean_title = page_title or "Captured Video"
                    clean_title = re.sub(r'[\\/*?:"<>|]', "", clean_title).strip()

                    headers = build_preserved_headers(best.get('headers', {}), url)
                    mode_prefix = "headless_edge" if headless else "interactive_edge"

                    return {
                        'url': best['url'],
                        'title': clean_title,
                        'headers': headers,
                        'cookies': cookies_dict,
                        'is_hls': best['is_hls'],
                        'is_dash': best['is_dash'],
                        'variants': best.get('variants') or {},
                        'method': f"{mode_prefix}_{best.get('source', 'unknown')}"
                    }

        except Exception as e:
            logger.error(f"[HeadlessEdgeSniffer] Непредвиденная ошибка: {e}")

        return None


class InteractiveBrowserSniffer:
    """
    Уровень 3.4: Интерактивный видимый браузер для сайтов со сложной защитой (капча/авторизация).
    """
    @staticmethod
    def sniff(url: str, timeout: int = 90, status_callback=None, is_cancelled=None, diagnostics: dict | None = None) -> dict | None:
        return HeadlessEdgeSniffer._run_playwright(
            url, timeout=timeout, headless=False, status_callback=status_callback, is_cancelled=is_cancelled, diagnostics=diagnostics
        )


class SeleniumEdgeSniffer:
    """
    Уровень 3.3: Резервный сниффер на базе Selenium WebDriver (Edge / Chrome).
    Используется как надежный фоллбэк при отсутствии или недоступности Playwright.
    """
    @staticmethod
    def sniff(url: str, timeout: int = 15, status_callback=None, is_cancelled=None) -> dict | None:
        if is_cancelled and is_cancelled():
            return None
        if status_callback:
            status_callback("Резервный перехват через Selenium Edge...")
        try:
            from selenium import webdriver
            from selenium.webdriver.edge.options import Options as EdgeOptions
        except ImportError:
            return None

        driver = None
        try:
            options = EdgeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--mute-audio')
            options.add_argument(f'user-agent={BROWSER_USER_AGENT}')
            options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
            options.set_capability('ms:loggingPrefs', {'performance': 'ALL'})

            try:
                driver = webdriver.Edge(options=options)
            except Exception:
                try:
                    from selenium.webdriver.chrome.options import Options as ChromeOptions
                    c_opts = ChromeOptions()
                    c_opts.add_argument('--headless=new')
                    c_opts.add_argument('--disable-gpu')
                    c_opts.add_argument('--no-sandbox')
                    c_opts.add_argument(f'user-agent={BROWSER_USER_AGENT}')
                    c_opts.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
                    driver = webdriver.Chrome(options=c_opts)
                except Exception:
                    return None

            if not driver:
                return None

            driver.set_page_load_timeout(timeout)
            try:
                driver.get(url)
            except Exception:
                pass

            start_t = time.time()
            streams = []
            while time.time() - start_t < timeout:
                if is_cancelled and is_cancelled():
                    break
                try:
                    logs = driver.get_log('performance')
                    for entry in logs:
                        msg_str = entry.get('message', '')
                        if any(ext in msg_str.lower() for ext in ('.m3u8', '.mpd')):
                            m = re.search(r'https?://[^\s"\'<>]+\.(?:m3u8|mpd)[^\s"\'<>]*', msg_str)
                            if m:
                                cand = m.group(0).replace(r'\/', '/')
                                if not is_ad_or_tracking(cand) and cand not in streams:
                                    streams.append(cand)
                    if streams:
                        break
                except Exception:
                    pass
                time.sleep(0.8)

            title = driver.title if driver else ""
            clean_title = re.sub(r'[\r\n\t]+', ' ', title).strip()
            clean_title = re.sub(r'(?:смотреть онлайн|бесплатно в хорошем качестве|hd|720p|1080p|»|\(.*?\)).*$', '', clean_title, flags=re.I).strip()
            clean_title = re.sub(r'[\\/*?:"<>|]', "", clean_title).strip()

            cookies = {}
            try:
                for c in driver.get_cookies():
                    cookies[c['name']] = c['value']
            except Exception:
                pass

            driver.quit()
            driver = None

            if streams:
                best_url = streams[0]
                return {
                    'url': best_url,
                    'title': clean_title or "Captured Video",
                    'headers': {'Referer': url, 'User-Agent': BROWSER_USER_AGENT},
                    'cookies': cookies,
                    'is_hls': '.m3u8' in best_url.lower(),
                    'is_dash': '.mpd' in best_url.lower(),
                    'method': 'selenium_edge_perf_log'
                }
        except Exception as e:
            logger.debug(f"[SeleniumEdgeSniffer] Ошибка: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        return None


def sniff_media_stream(url: str, timeout: int = 18, status_callback=None, is_cancelled=None, diagnostics: dict | None = None) -> dict | None:
    """
    Основная точка входа Универсального резолвера (Level 3):
    1. Сначала пробует мгновенный FastMetaSniffer (curl_cffi), если для домена не закэширован браузерный режим.
    2. При отсутствии результата запускает HeadlessEdgeSniffer (Playwright + Edge).
    3. При сбое Playwright запускает резервный SeleniumEdgeSniffer (пропускается при DRM или сетевом таймауте).
    """
    if is_cancelled and is_cancelled():
        return None

    diag = diagnostics if diagnostics is not None else {}
    hint = get_domain_sniffer_hint(url)

    if hint not in ('edge', 'selenium'):
        if status_callback:
            status_callback("Быстрый анализ разметки страницы (curl_cffi)...")

        fast_res = FastMetaSniffer.sniff(url, timeout=5, is_cancelled=is_cancelled, diagnostics=diag)
        if is_cancelled and is_cancelled():
            return None
        if fast_res:
            set_domain_sniffer_hint(url, 'fast')
            logger.info(f"[UniversalSniffer] Поток найден быстрым анализом: {fast_res['url']}")
            return fast_res
    else:
        logger.debug(f"[UniversalSniffer] Пропуск FastMetaSniffer по кэшу домена ({hint}) для {url}")

    if hint != 'selenium':
        logger.info(f"[UniversalSniffer] Запуск интеллектуального сниффера Edge для {url}...")
        edge_res = HeadlessEdgeSniffer.sniff(url, timeout=timeout, status_callback=status_callback, is_cancelled=is_cancelled, diagnostics=diag)
        if is_cancelled and is_cancelled():
            return None
        if edge_res:
            set_domain_sniffer_hint(url, 'edge')
            logger.info(f"[UniversalSniffer] Поток успешно перехвачен в браузере Edge: {edge_res['url']}")
            return edge_res

    if diag.get('drm_detected') or diag.get('network_timeout'):
        logger.info(f"[UniversalSniffer] Пропуск резервного Selenium Edge (drm={diag.get('drm_detected')}, timeout={diag.get('network_timeout')}).")
        return None

    # Резервный Уровень 3.3: Selenium Edge
    logger.info(f"[UniversalSniffer] Запуск резервного Selenium Edge для {url}...")
    sel_res = SeleniumEdgeSniffer.sniff(url, timeout=timeout, status_callback=status_callback, is_cancelled=is_cancelled)
    if is_cancelled and is_cancelled():
        return None
    if sel_res:
        set_domain_sniffer_hint(url, 'selenium')
        logger.info(f"[UniversalSniffer] Поток успешно перехвачен через Selenium: {sel_res['url']}")
        return sel_res

    set_domain_sniffer_hint(url, None)
    logger.warning(f"[UniversalSniffer] Не удалось обнаружить медиапоток на странице: {url}")
    return None
