import os
import re
import time
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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
    Уровень 3.1: Сверхбыстрый анализ HTML/DOM и OpenGraph через curl_cffi с имитацией TLS Chrome.
    Отрабатывает за 1 секунду без запуска тяжелого браузера.
    """
    @staticmethod
    def sniff(url: str, timeout: int = 5, is_cancelled=None) -> dict | None:
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
            resp = session.get(
                url,
                headers={'User-Agent': BROWSER_USER_AGENT, 'Referer': url},
                timeout=timeout,
                allow_redirects=True
            )
            if resp.status_code != 200 or not resp.text:
                return None

            html = resp.text

            # 1. Заголовок страницы
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
            title = title_match.group(1).strip() if title_match else ""
            title = re.sub(r'[\r\n\t]+', ' ', title).strip()

            # 2. OpenGraph теги видео
            og_match = re.search(
                r'<meta\s+property=["\']og:video(?::secure_url|:url)?["\']\s+content=["\']([^"\']+)["\']',
                html,
                re.I
            )
            if not og_match:
                og_match = re.search(
                    r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:video(?::secure_url|:url)?["\']',
                    html,
                    re.I
                )

            if og_match:
                cand = og_match.group(1).strip()
                if cand.startswith('http') and not is_ad_or_tracking(cand):
                    return {
                        'url': cand,
                        'title': title or "Web Video",
                        'headers': {'Referer': url, 'User-Agent': BROWSER_USER_AGENT},
                        'method': 'fast_opengraph'
                    }

            # 3. Прямые теги <video src="..."> и <source src="...">
            video_match = re.search(r'<video[^>]+src=["\'](https?://[^"\']+\.(?:mp4|m3u8|webm)[^"\']*)["\']', html, re.I)
            if not video_match:
                video_match = re.search(r'<source[^>]+src=["\'](https?://[^"\']+\.(?:mp4|m3u8|webm)[^"\']*)["\']', html, re.I)

            if video_match:
                cand = video_match.group(1).strip()
                if not is_ad_or_tracking(cand):
                    return {
                        'url': cand,
                        'title': title or "Web Video",
                        'headers': {'Referer': url, 'User-Agent': BROWSER_USER_AGENT},
                        'method': 'fast_html_video'
                    }

            # 4. Поиск манифестов .m3u8 в inline-скриптах плееров (HLS)
            m3u8_matches = re.findall(r'["\'](https?://[^"\']+\.m3u8(?:\?[^"\']*)?)["\']', html)
            for cand in m3u8_matches:
                if not is_ad_or_tracking(cand):
                    return {
                        'url': cand,
                        'title': title or "Web Stream",
                        'headers': {'Referer': url, 'User-Agent': BROWSER_USER_AGENT},
                        'method': 'fast_inline_m3u8'
                    }

            # 5. Анализ встроенных iframe плееров (cinemar, alloha, kodik, videocdn, embed, player)
            iframe_matches = re.findall(r'<(?:iframe|li)[^>]+(?:src|data-src)=["\'](https?://[^"\']*(?:embed|player|video|cdn|stream)[^"\']*)["\']', html, re.I)
            for ifr_url in iframe_matches:
                if is_ad_or_tracking(ifr_url):
                    continue
                try:
                    sub_resp = session.get(
                        ifr_url,
                        headers={'User-Agent': BROWSER_USER_AGENT, 'Referer': url},
                        timeout=3,
                        allow_redirects=True
                    )
                    if sub_resp.status_code == 200 and sub_resp.text:
                        sub_html = sub_resp.text
                        sub_m3u8 = re.findall(r'["\'](https?://[^"\']+\.m3u8(?:\?[^"\']*)?)["\']', sub_html)
                        for cand in sub_m3u8:
                            if not is_ad_or_tracking(cand):
                                return {
                                    'url': cand,
                                    'title': title or "Web Stream",
                                    'headers': {'Referer': ifr_url, 'User-Agent': BROWSER_USER_AGENT, 'Origin': f"{urlparse(ifr_url).scheme}://{urlparse(ifr_url).netloc}"},
                                    'method': 'fast_iframe_m3u8'
                                }
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"[FastMetaSniffer] Ошибка анализа: {e}")

        return None


class HeadlessEdgeSniffer:
    """
    Уровень 3.2: Интеллектуальный сниффер сетевого трафика через Playwright и системный Edge/Chromium.
    Оснащен:
    - Stealth-маскировкой (обход Cloudflare Turnstile, скрытие navigator.webdriver).
    - Инжекцией сессионных куков пользователя из установленных браузеров.
    - Активацией ленивых iframes (data-src, data-lazy-src) и скроллингом страницы.
    - Перехватом JSON API ответов плееров (Playerjs, VideoJS, JWPlayer), содержащих скрытые .m3u8/.mp4.
    - Автоматической симуляцией клика по плееру внутри всех фреймов.
    """
    @staticmethod
    def sniff(url: str, timeout: int = 18, status_callback=None, is_cancelled=None) -> dict | None:
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
            status_callback("Инициализация защищенного браузера Edge...")

        captured_streams = []

        try:
            with sync_playwright() as p:
                browser = None
                launch_args = [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-infobars',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--mute-audio',
                    '--disable-extensions',
                    '--window-size=1920,1080',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding'
                ]

                # Приоритет: системный Microsoft Edge (встроен в Windows без загрузки бинарников), затем Chrome
                for channel in ['msedge', 'chrome', None]:
                    try:
                        kwargs = {
                            'headless': True,
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
                    viewport={'width': 1920, 'height': 1080},
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

                # 1. Перехват сетевых запросов
                def on_request(req):
                    req_url = req.url
                    if is_candidate_media_url(req_url):
                        if not any(s['url'] == req_url for s in captured_streams):
                            captured_streams.append({
                                'url': req_url,
                                'headers': dict(req.headers),
                                'is_hls': '.m3u8' in req_url.lower(),
                                'is_dash': '.mpd' in req_url.lower(),
                                'source': 'direct_req'
                            })

                # 2. Перехват сетевых ответов (включая JSON API плееров)
                def on_response(resp):
                    try:
                        resp_url = resp.url
                        if is_ad_or_tracking(resp_url):
                            return

                        ct = resp.headers.get('content-type', '').lower()
                        status = resp.status

                        # 2a. Медиапоток по Content-Type
                        if is_candidate_media_url(resp_url, content_type=ct):
                            if not any(s['url'] == resp_url for s in captured_streams):
                                captured_streams.append({
                                    'url': resp_url,
                                    'headers': dict(resp.request.headers),
                                    'is_hls': '.m3u8' in resp_url.lower() or 'mpegurl' in ct,
                                    'is_dash': '.mpd' in resp_url.lower() or 'dash' in ct,
                                    'source': 'media_resp'
                                })
                            return

                        # 2b. Анализ ответов API плееров (Playerjs, VideoJS, JWPlayer, etc.)
                        if status == 200 and any(t in ct for t in ('application/json', 'text/plain', 'text/javascript', 'application/javascript')):
                            cl = resp.headers.get('content-length')
                            if cl and int(cl) > 1024 * 512:
                                return  # Защита памяти: пропускаем файлы более 512 КБ

                            try:
                                body = resp.text()
                            except Exception:
                                return

                            if body and any(ext in body.lower() for ext in ('.m3u8', '.mpd', '.mp4')):
                                clean_body = body.replace(r'\/', '/')
                                matches = re.findall(r'https?://[^\s"\'<>\\]+\.(?:m3u8|mpd|mp4)[^\s"\'<>\\]*', clean_body, re.I)
                                for cand in matches:
                                    cand = cand.rstrip(';,"')
                                    if not is_ad_or_tracking(cand) and not any(s['url'] == cand for s in captured_streams):
                                        logger.info(f"[HeadlessEdgeSniffer] Медиапоток найден в ответе API ({resp_url}): {cand}")
                                        captured_streams.append({
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
                    status_callback("Загрузка страницы и обход защиты...")

                try:
                    page.goto(url, timeout=timeout * 1000, wait_until='domcontentloaded')
                except Exception as nav_err:
                    logger.debug(f"[HeadlessEdgeSniffer] Ошибка перехода: {nav_err}")

                start_time = time.time()

                # Цикл обнаружения и интерактивного взаимодействия
                while time.time() - start_time < timeout:
                    if is_cancelled and is_cancelled():
                        logger.info("[HeadlessEdgeSniffer] Отмена сниффинга по сигналу пользователя.")
                        try:
                            browser.close()
                        except Exception:
                            pass
                        return None

                    high_prio = [s for s in captured_streams if s['is_hls'] or s['is_dash']]
                    if high_prio:
                        # Даем небольшую паузу на случай получения мастер-манифеста с максимальным качеством
                        time.sleep(0.8)
                        break

                    if captured_streams and (time.time() - start_time > 5.0):
                        break

                    elapsed = time.time() - start_time
                    if elapsed >= 1.5:
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
                                    // Запуск встроенного video
                                    document.querySelectorAll('video').forEach(v => {
                                        try { v.muted = true; v.play(); } catch(e){}
                                    });
                                    // Интеграция с API веб-плееров
                                    if (window.player && typeof window.player.api === 'function') {
                                        try { window.player.api('play'); } catch(e){}
                                    }
                                    if (window.playerjs && typeof window.playerjs.api === 'function') {
                                        try { window.playerjs.api('play'); } catch(e){}
                                    }
                                    // Поиск и нажатие кнопок плеера
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
                                }""")
                            except Exception:
                                pass

                    time.sleep(0.4)

                page_title = ""
                try:
                    page_title = page.title()
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
                    # Ранжирование: сначала HLS мастер-манифесты, затем обычные HLS, затем DASH, затем MP4
                    def stream_score(s):
                        u = s['url'].lower()
                        score = 1
                        if s['is_hls']:
                            score = 8
                            if 'master' in u or 'hls.m3u8' in u or 'manifest' in u:
                                score = 10
                        elif s['is_dash']:
                            score = 6
                        elif '.mp4' in u:
                            score = 5
                        return score

                    captured_streams.sort(key=stream_score, reverse=True)
                    best = captured_streams[0]

                    clean_title = re.sub(r'[\r\n\t]+', ' ', page_title).strip()
                    # Убираем типичные суффиксы киносайтов ("» Страница 2", "смотреть онлайн бесплатно в хорошем качестве")
                    clean_title = re.sub(r'(?:смотреть онлайн|бесплатно в хорошем качестве|hd|720p|1080p|»|\(.*?\)).*$', '', clean_title, flags=re.I).strip()
                    clean_title = re.sub(r'[\\/*?:"<>|]', "", clean_title).strip()
                    if not clean_title or len(clean_title) < 2:
                        clean_title = page_title or "Captured Video"
                    clean_title = re.sub(r'[\\/*?:"<>|]', "", clean_title).strip()

                    # Формируем реферер и заголовки из контекста перехвата
                    best_headers = best.get('headers', {})
                    ref = best_headers.get('referer') or best_headers.get('Referer') or url
                    origin = best_headers.get('origin') or best_headers.get('Origin') or f"{urlparse(ref).scheme}://{urlparse(ref).netloc}"

                    headers = {
                        'User-Agent': BROWSER_USER_AGENT,
                        'Referer': ref,
                        'Origin': origin
                    }

                    return {
                        'url': best['url'],
                        'title': clean_title,
                        'headers': headers,
                        'cookies': cookies_dict,
                        'is_hls': best['is_hls'],
                        'is_dash': best['is_dash'],
                        'method': f"headless_edge_{best.get('source', 'unknown')}"
                    }

        except Exception as e:
            logger.error(f"[HeadlessEdgeSniffer] Непредвиденная ошибка: {e}")

        return None


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


def sniff_media_stream(url: str, timeout: int = 18, status_callback=None, is_cancelled=None) -> dict | None:
    """
    Основная точка входа Универсального резолвера (Level 3):
    1. Сначала пробует мгновенный FastMetaSniffer (curl_cffi).
    2. При отсутствии результата запускает HeadlessEdgeSniffer (Playwright + Edge).
    3. При сбое Playwright запускает резервный SeleniumEdgeSniffer.
    """
    if is_cancelled and is_cancelled():
        return None

    if status_callback:
        status_callback("Быстрый анализ разметки страницы (curl_cffi)...")

    fast_res = FastMetaSniffer.sniff(url, timeout=5, is_cancelled=is_cancelled)
    if is_cancelled and is_cancelled():
        return None
    if fast_res:
        logger.info(f"[UniversalSniffer] Поток найден быстрым анализом: {fast_res['url']}")
        return fast_res

    logger.info(f"[UniversalSniffer] Запуск интеллектуального сниффера Edge для {url}...")
    edge_res = HeadlessEdgeSniffer.sniff(url, timeout=timeout, status_callback=status_callback, is_cancelled=is_cancelled)
    if is_cancelled and is_cancelled():
        return None
    if edge_res:
        logger.info(f"[UniversalSniffer] Поток успешно перехвачен в браузере Edge: {edge_res['url']}")
        return edge_res

    # Резервный Уровень 3.3: Selenium Edge
    logger.info(f"[UniversalSniffer] Запуск резервного Selenium Edge для {url}...")
    sel_res = SeleniumEdgeSniffer.sniff(url, timeout=timeout, status_callback=status_callback, is_cancelled=is_cancelled)
    if is_cancelled and is_cancelled():
        return None
    if sel_res:
        logger.info(f"[UniversalSniffer] Поток успешно перехвачен через Selenium: {sel_res['url']}")
        return sel_res

    logger.warning(f"[UniversalSniffer] Не удалось обнаружить медиапоток на странице: {url}")
    return None
