import sys
import os
import shutil
import logging
import subprocess
import time
import hashlib
class _LazyYtDlp:
    _module = None

    def __getattr__(self, name):
        if _LazyYtDlp._module is None:
            import yt_dlp as _real
            _LazyYtDlp._module = _real
        try:
            return getattr(_LazyYtDlp._module, name)
        except AttributeError:
            import importlib
            try:
                submodule = importlib.import_module(f"yt_dlp.{name}")
                setattr(_LazyYtDlp._module, name, submodule)
                return submodule
            except ImportError:
                raise AttributeError(f"module 'yt_dlp' has no attribute '{name}'")

yt_dlp = _LazyYtDlp()
import threading
import concurrent.futures
import re
from .stream_helper import StreamResolverHelper
from .path_manager import get_aria2c_path, get_downloads_dir


def clean_ansi(text: str) -> str:
    """Полное удаление ANSI escape-кодов, терминальных последовательностей и мусорных глифов."""
    if not text:
        return ""
    # Удаление управляющих кодов ESC [...m, ESC ]...BEL, а также непечатаемых символов
    s = re.sub(r'(?:\x1b|[\uFFFD\x00-\x1F]|\x1b?\[)[0-9;]*[a-zA-Z]|\x1b\].*?(?:\x07|\x1b\\)|[\x00-\x1f\x7f\ufffd]', '', str(text))
    # Удаление артефактов шрифта при выводе ESC кодов: '[]', '[0;32m', '[[0m'
    s = re.sub(r'\[\]\[[0-9;]*m|\[\]|\[+[\d;]+m', '', s)
    return re.sub(r'\s+', ' ', s).strip()
from PyQt6.QtCore import QRunnable, pyqtSignal, QObject
from PyQt6.QtGui import QImage
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_http_session = None


def get_http_session():
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retry_strategy
        )
        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)
        _http_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    return _http_session


class ThumbnailCache:
    def __init__(self, max_size=100):
        self._cache = {}
        self._order = []
        self._max_size = max_size
        self._lock = threading.Lock()

    def _get_key(self, url):
        return hashlib.md5(url.encode()).hexdigest()

    def get(self, url):
        with self._lock:
            key = self._get_key(url)
            if key in self._cache:
                if key in self._order:
                    self._order.remove(key)
                self._order.append(key)
                return self._cache[key]
            return None

    def set(self, url, image):
        with self._lock:
            key = self._get_key(url)
            if key in self._cache:
                if key in self._order:
                    self._order.remove(key)
            elif len(self._cache) >= self._max_size and self._order:
                oldest = self._order.pop(0)
                self._cache.pop(oldest, None)
            self._cache[key] = image
            self._order.append(key)

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._order.clear()


thumbnail_cache = ThumbnailCache(max_size=100)


class WorkerSignals(QObject):
    info_fetched = pyqtSignal(dict)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    thumbnail_loaded = pyqtSignal(QImage)


class UniversalSnifferSignals(QObject):
    stream_found = pyqtSignal(dict)
    error = pyqtSignal(str)
    status_updated = pyqtSignal(str)


class UniversalSnifferWorker(QRunnable):
    """
    Фоновый рабочий поток универсального перехватчика (Level 3).
    Выполняет двухэтапный поиск потока (curl_cffi -> Playwright Headless Edge)
    и передает захваченный поток с заголовками и куками в основной поток.
    Поддерживает мгновенную отмену по сигналу пользователя или остановке задачи.
    """
    def __init__(self, url: str, timeout: int = 18, task=None):
        super().__init__()
        self.url = url
        self.timeout = timeout
        self.task = task
        self._is_cancelled = False
        self.signals = UniversalSnifferSignals()

    def cancel(self):
        self._is_cancelled = True
        if self.task:
            self.task.request_stop()

    def is_cancelled_check(self) -> bool:
        if self._is_cancelled:
            return True
        if self.task and self.task.is_stop_requested():
            return True
        return False

    def run(self):
        try:
            if self.is_cancelled_check():
                return

            from .universal_sniffer import sniff_media_stream

            def on_status(msg):
                if not self.is_cancelled_check():
                    self.signals.status_updated.emit(msg)

            res = sniff_media_stream(
                self.url,
                timeout=self.timeout,
                status_callback=on_status,
                is_cancelled=self.is_cancelled_check
            )

            if self.is_cancelled_check():
                logger.info(f"[UniversalSnifferWorker] Задача {self.url} остановлена, результат отменен.")
                return

            if res:
                self.signals.stream_found.emit(res)
            else:
                self.signals.error.emit(f"Не удалось обнаружить видеопоток на странице: {self.url}")
        except Exception as e:
            if not self.is_cancelled_check():
                self.signals.error.emit(str(e))


class InfoWorker(QRunnable):
    def __init__(self, url, settings, headers=None, referer=None, cookies=None):
        super().__init__()
        self.url = url
        self.settings = settings
        self.headers = headers or {}
        self.referer = referer
        self.cookies = cookies or {}
        self.signals = WorkerSignals()

    def run(self):
        try:
            info_referer = self.referer or StreamResolverHelper.get_stream_referer(self.url, default_referer='https://vi3000.top/')

            u_clean = self.url.lower().split('?')[0]
            is_direct_stream = any(d in u_clean for d in ('solodcdn', 'rooster.cloud2')) or u_clean.endswith(('.mp4', '.mkv', '.webm', '.ts', '.mov', '.avi'))
            if is_direct_stream:
                try:
                    s_head = requests.Session()
                    s_head.trust_env = False
                    h_resp = s_head.head(
                        self.url,
                        headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Referer': info_referer,
                            'Origin': info_referer.rstrip('/')
                        },
                        verify=False,
                        timeout=4,
                        allow_redirects=True
                    )
                    cl = h_resp.headers.get('Content-Length')
                    filesize = int(cl) if cl and cl.isdigit() else 0
                    if h_resp.status_code in (200, 206) and filesize > 1024:
                        m_h = re.search(r'[/_](\d{3,4})p?[\._/]', self.url)
                        target_h = int(m_h.group(1)) if m_h else 360
                        title = f"Kodik Video ({target_h}p)" if any(d in self.url for d in ('solodcdn', 'kodik')) else os.path.splitext(os.path.basename(u_clean))[0]
                        formats = [{
                            'format_id': f"{target_h}p",
                            'url': self.url,
                            'ext': 'mp4',
                            'height': target_h,
                            'width': int(target_h * 16 / 9),
                            'filesize': filesize,
                            'filesize_approx': filesize,
                            'vcodec': 'h264',
                            'acodec': 'aac',
                        }]
                        if any(d in self.url for d in ('solodcdn', 'kodik')):
                            m_kodik = re.search(r'/(\d{3,4})\.mp4', self.url)
                            if m_kodik:
                                curr_h = int(m_kodik.group(1))
                                for alt_h in (360, 480, 720, 1080):
                                    if alt_h == curr_h:
                                        continue
                                    formats.append({
                                        'format_id': f"{alt_h}p",
                                        'url': re.sub(r'/\d{3,4}\.mp4', f'/{alt_h}.mp4', self.url),
                                        'ext': 'mp4',
                                        'height': alt_h,
                                        'width': int(alt_h * 16 / 9),
                                        'filesize': int(filesize * (alt_h / curr_h) ** 1.3) if filesize else 0,
                                        'filesize_approx': int(filesize * (alt_h / curr_h) ** 1.3) if filesize else 0,
                                        'vcodec': 'h264',
                                        'acodec': 'aac',
                                    })
                        direct_info = {
                            'id': hashlib.md5(self.url.encode()).hexdigest()[:10],
                            'title': title,
                            'ext': 'mp4',
                            'height': target_h,
                            'formats': formats,
                            'filesize': filesize,
                            'filesize_approx': filesize,
                            'extractor': 'generic',
                            'extractor_key': 'DirectStream',
                            'webpage_url': self.url,
                        }
                        try:
                            self.signals.info_fetched.emit(direct_info)
                        except RuntimeError:
                            pass
                        return
                except Exception as e_head:
                    logger.debug(f"Direct stream fast HEAD probe failed ({e_head}), falling back to yt-dlp")

            info_logger = _YtdlLogger(logger)
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'enable_js': True,
                'logger': info_logger,
                'remote_components': {'ejs:github': True},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': info_referer,
                    'Origin': info_referer.rstrip('/')
                }
            }
            if self.headers:
                ydl_opts['http_headers'].update(self.headers)
            if self.cookies and isinstance(self.cookies, dict):
                ydl_opts['http_headers']['Cookie'] = '; '.join(f"{k}={v}" for k, v in self.cookies.items())

            # High-speed analysis optimizations across all platforms
            ydl_opts.update({
                'noplaylist': True,
                'writesubtitles': False,
                'allsubtitles': False,
                'writeautomaticsub': False,
                'getcomments': False,
                'no_color': True,
            })

            u_lower = self.url.lower()
            is_youtube = any(d in u_lower for d in ('youtube.com', 'youtu.be'))
            is_tiktok = any(d in u_lower for d in ('tiktok.com',))

            if is_youtube:
                ydl_opts.update({
                    'socket_timeout': 10,
                })
            elif is_tiktok:
                ydl_opts.update({
                    'socket_timeout': 8,
                    'extractor_args': {
                        'tiktok': {
                            'api_hostname': 'api16-normal-c-useast1a.tiktokv.com'
                        }
                    }
                })
            else:
                ydl_opts.update({
                    'socket_timeout': 8,
                    'extract_flat': 'discard_in_playlist',
                    'check_formats': False,
                    'lazy_playlist': True,
                })
            use_cookies = self.settings.value('use_cookies', False, type=bool)
            if use_cookies:
                source_type = self.settings.value('cookie_source_type', 'file')
                if source_type == 'file':
                    cookie_file = self.settings.value('cookies_path', '')
                    if cookie_file and os.path.exists(cookie_file):
                        ydl_opts['cookiefile'] = cookie_file
                else:
                    # ИЗОЛЯЦИЯ: Живые куки браузера запрашиваются только для YouTube
                    if is_youtube:
                        browser = self.settings.value('cookie_browser', self.settings.value('cookie_source', 'none'))
                        if browser and browser != 'none':
                            try:
                                from .browser_cookies import get_best_browser_cookiefile
                                live_file, count, b_name = get_best_browser_cookiefile(browser)
                                if live_file and count > 0:
                                    ydl_opts['cookiefile'] = live_file
                            except Exception as e:
                                logger.warning(f"Browser {browser} not available for cookies: {e}")

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=False)
                    if not info:
                        real_err = info_logger.last_error or "yt-dlp не смог извлечь информацию о видео (контент недоступен или неподдерживаемый URL)"
                        raise Exception(real_err)
                    try:
                        self.signals.info_fetched.emit(info)
                    except RuntimeError:
                        pass
            except Exception as e:
                err_str = str(e).lower()
                if ('cookie' in err_str or 'dpapi' in err_str) and ('cookiesfrombrowser' in ydl_opts or 'cookiefile' in ydl_opts):
                    logger.warning(f"Cookie extraction failed ({e}), retrying without cookies...")
                    ydl_opts.pop('cookiesfrombrowser', None)
                    ydl_opts.pop('cookiefile', None)
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(self.url, download=False)
                        if not info:
                            real_err = info_logger.last_error or "yt-dlp не смог извлечь информацию о видео (контент недоступен или неподдерживаемый URL)"
                            raise Exception(real_err)
                        try:
                            self.signals.info_fetched.emit(info)
                        except RuntimeError:
                            pass
                else:
                    raise
        except Exception as e:
            logger.error(f"InfoWorker error for {self.url}: {e}")
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class ThumbnailWorker(QRunnable):
    def __init__(self, url, task):
        super().__init__()
        self.url = url
        self.task = task
        self.signals = WorkerSignals()

    def run(self):
        try:
            cached = thumbnail_cache.get(self.url)
            if cached is not None:
                self.signals.thumbnail_loaded.emit(cached)
                return

            session = get_http_session()
            response = session.get(self.url, timeout=10)
            response.raise_for_status()
            image = QImage()
            image.loadFromData(response.content)
            if not image.isNull():
                thumbnail_cache.set(self.url, image)
                self.signals.thumbnail_loaded.emit(image)
        except Exception as e:
            logger.debug(f"Failed to load thumbnail from {self.url}: {e}")


class PlaylistCheckWorker(QRunnable):
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.signals = WorkerSignals()

    def run(self):
        try:
            ydl_opts = {
                'quiet': True,
                'extract_flat': 'in_playlist',
                'skip_download': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'noplaylist': False,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if info:
                    self.signals.info_fetched.emit(info)
                else:
                    self.signals.error.emit("Нет данных")
        except Exception as e:
            self.signals.error.emit(str(e))


class _YtdlLogger:
    def __init__(self, parent_logger):
        self.parent = parent_logger
        self.last_error = ""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg):
        self.parent.warning(f"[yt-dlp] {msg}")
    def error(self, msg):
        self.last_error = str(msg)
        self.parent.error(f"[yt-dlp] {msg}")


class DownloadWorker(QRunnable):
    def __init__(self, task, settings, ffmpeg_path, translator):
        super().__init__()
        self.task = task
        self.settings = settings
        self.ffmpeg_path = ffmpeg_path
        self.translator = translator
        self.signals = WorkerSignals()
        self._cancel_requested = False

        self._start_time = None
        self._monitor_running = False
        self._last_downloaded_filename = None

    def cancel(self):
        logger.info(f"Пользователь нажал ОТМЕНУ для {self.task.url}")
        self._cancel_requested = True
        self._monitor_running = False
        self.task.request_stop()

    def simple_progress_hook(self, d):
        if self._cancel_requested or self.task.is_stop_requested():
            raise yt_dlp.utils.DownloadCancelled("Остановлено юзером")

        fn = d.get('filename') or ''
        info_dict = d.get('info_dict') or {}
        fn_lower = fn.lower()
        sub_exts = ('.vtt', '.srt', '.ass', '.lrc', '.sub', '.sbv')
        is_subtitle = (
            any(fn_lower.endswith(ext) or f'{ext}.part' in fn_lower or f'{ext}.ytdl' in fn_lower for ext in sub_exts)
            or info_dict.get('ext') in ('vtt', 'srt', 'ass', 'lrc', 'sub', 'sbv')
            or info_dict.get('extractor_key') == 'Subtitles'
            or d.get('postprocessor') in ('FFmpegSubtitlesConvertor', 'FFmpegEmbedSubtitle')
        )

        if d.get('status') == 'downloading':
            if is_subtitle:
                return

            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)

            speed_val = d.get('speed')
            if speed_val is not None and speed_val > 0:
                if speed_val >= 1024 * 1024:
                    speed = f"{speed_val / (1024 * 1024):.2f} MiB/s"
                else:
                    speed = f"{speed_val / 1024:.1f} KiB/s"
            else:
                speed_raw = d.get('_speed_str', '')
                speed = clean_ansi(speed_raw) or 'N/A'

            eta_val = d.get('eta')
            if eta_val is not None and eta_val >= 0:
                eta_val = int(eta_val)
                if eta_val >= 3600:
                    eta = f"{eta_val // 3600:02d}:{int((eta_val % 3600) // 60):02d}:{int(eta_val % 60):02d}"
                else:
                    eta = f"{int(eta_val // 60):02d}:{int(eta_val % 60):02d}"
            else:
                eta_raw = d.get('_eta_str', '')
                eta = clean_ansi(eta_raw)

            eta_part = f" • ост. {eta}" if eta else ""

            frag_index = d.get('fragment_index')
            frag_count = d.get('fragment_count')
            frag_info = f" [{frag_index}/{frag_count}]" if frag_index and frag_count else ""

            if total > 0:
                # Стабилизация размера: если размер уже определен, не перезаписываем его плавающими оценками каждого фрагмента
                curr_size = getattr(self.task, 'file_size_str', '')
                if not curr_size or curr_size in ('...', ''):
                    if total > 100 * 1024 or getattr(self.task, 'audio_only', False):
                        self.task.set_file_size(total)
                percent = int((downloaded / total) * 90)
                self.task.update_progress(percent, f"Скачивание: {percent}%{frag_info}, {speed}{eta_part}")
            elif frag_index and frag_count:
                percent = int((frag_index / frag_count) * 90)
                self.task.update_progress(percent, f"Скачивание: {percent}% (фрагмент {frag_index}/{frag_count}), {speed}{eta_part}")
            else:
                mb = downloaded / (1024 * 1024)
                self.task.update_progress(0, f"Скачивание: {mb:.1f} MB, {speed}{eta_part}")

        elif d.get('status') == 'finished':
            if is_subtitle:
                return
            fn = d.get('filename')
            if fn:
                self._last_downloaded_filename = fn
            info_dict = d.get('info_dict', {})
            real_t = info_dict.get('title')
            custom_t = getattr(self.task, 'custom_title', None)
            if not custom_t and real_t and (not getattr(self.task, 'title', None) or self.task.title in ("...", "")):
                if real_t in ('720', '1080', '480', '360', 'master', 'manifest', 'index') or (isinstance(real_t, str) and real_t.isdigit()):
                    if any(d_url in self.task.url for d_url in ('solodcdn', 'kodik')):
                        real_t = f"Kodik Video ({real_t}p)" if real_t.isdigit() else "Kodik Video"
                    elif any(d_url in self.task.url for d_url in ('ya-ligh', 'aniboom')):
                        real_t = "AniBoom Video"
                self.task.title = real_t
                self.task.info_updated.emit()

            real_h = info_dict.get('height')
            if getattr(self.task, 'audio_only', False) or info_dict.get('vcodec') == 'none':
                audio_fmt = str(self.settings.value('audio_format', 'mp3')).upper()
                self.task.quality_badge = "MP3" if getattr(self.task, 'quality_override', '') == 'audio_mp3' or audio_fmt == 'MP3' else "AUDIO"
                self.task.info_updated.emit()
            elif real_h:
                self.task.quality_badge = f"{real_h}p"
                self.task.info_updated.emit()

            logger.debug(f"[VOD] Поток скачан: {fn}. Ждем склейку...")

    def simple_pp_hook(self, d):
        status = d.get('status')
        pp = d.get('postprocessor')
        logger.debug(f"[VOD POSTPROCESSOR] {pp} -> {status}")

        if status == 'started':
            self.task.update_progress(95, "Склейка видео и звука...")
        elif status == 'finished':
            info_dict = d.get('info_dict', {})
            pp_file = info_dict.get('filepath') or info_dict.get('_filename')
            if pp_file:
                self._last_downloaded_filename = pp_file
            if pp == 'FFmpegExtractAudio' or getattr(self.task, 'audio_only', False):
                audio_fmt = str(self.settings.value('audio_format', 'mp3')).upper()
                self.task.quality_badge = "MP3" if audio_fmt == 'MP3' else "AUDIO"
            elif info_dict.get('height'):
                self.task.quality_badge = f"{info_dict.get('height')}p"
            real_t = info_dict.get('title')
            custom_t = getattr(self.task, 'custom_title', None)
            if not custom_t and real_t and (not getattr(self.task, 'title', None) or self.task.title in ("...", "")):
                if real_t in ('720', '1080', '480', '360', 'master', 'manifest', 'index') or (isinstance(real_t, str) and real_t.isdigit()):
                    if any(d_url in self.task.url for d_url in ('solodcdn', 'kodik')):
                        real_t = f"Kodik Video ({real_t}p)" if real_t.isdigit() else "Kodik Video"
                    elif any(d_url in self.task.url for d_url in ('ya-ligh', 'aniboom')):
                        real_t = "AniBoom Video"
                self.task.title = real_t
                self.task.info_updated.emit()
            self.task.update_progress(99, "Сохранение...")

    def _monitor_progress_twitch(self, target_file):
        last_size = 0
        last_time = time.time()

        while self._monitor_running and not self._cancel_requested and not self.task.is_stop_requested():
            try:
                if target_file and os.path.exists(target_file):
                    size = os.path.getsize(target_file)
                    now = time.time()
                    diff = now - last_time
                    speed_bps = (size - last_size) / diff if diff > 0 else 0
                    last_size, last_time = size, now

                    speed_str = f"{speed_bps / 1024:.1f} KB/s" if speed_bps < 1024 * 1024 else f"{speed_bps / (1024 * 1024):.2f} MB/s"
                    mb = size / (1024 * 1024)
                    size_str = f"{mb:.1f} MB" if mb < 1024 else f"{mb / 1024:.2f} GB"

                    self.task.update_progress(0, f"Запись эфира: {size_str} | {speed_str}")
                else:
                    self.task.update_progress(0, "Подключение к потоку...")
            except Exception:
                pass
            time.sleep(1)

    def _default_save_path(self):
        return get_downloads_dir()

    def run(self):
        logger.info(f"--- СТАРТ ЗАДАЧИ: {self.task.url} ---")
        try:
            save_path = self.settings.value('save_path', '')
            if not save_path or not os.path.isdir(save_path):
                save_path = self._default_save_path()
            self.task.save_path = save_path

            # Автовосстановление оригинального веб-адреса, если в url попал временный CDN плейлист
            orig_url = getattr(self.task, 'original_url', None) or (
                getattr(self.task, 'info', {}).get('webpage_url') if isinstance(getattr(self.task, 'info', None), dict) else None
            )
            if orig_url and any(cdn in self.task.url.lower() for cdn in ('ttvnw.net', 'googlevideo.com', 'fbcdn.net')):
                logger.info(f"Восстановление оригинального URL: {self.task.url} -> {orig_url}")
                self.task.url = orig_url

            u_lower = self.task.url.lower()
            is_twitch = ('twitch.tv' in u_lower) or ('ttvnw.net' in u_lower)
            is_twitch_vod_or_clip = (
                '/videos/' in u_lower or
                '/clip/' in u_lower or
                'clips.twitch.tv' in u_lower
            )

            # Прямая трансляция канала Twitch (НЕ архивные записи /videos/ и НЕ клипы)
            if is_twitch and not is_twitch_vod_or_clip:
                logger.info("[TWITCH] Режим: ЗАПИСЬ ПРЯМОГО СТРИМА TWITCH")
                self._run_twitch_stream(save_path)
            else:
                logger.info("[VOD] Режим: ОБЫЧНОЕ ВИДЕО (VOD / ЗАПИСЬ / КЛИП)")
                self._run_standard_vod(save_path)

        except yt_dlp.utils.DownloadCancelled:
            logger.info("Загрузка отменена юзером/скриптом.")
            self.task.set_status(self.task.Status.STOPPED)
        except Exception as e:
            logger.error(f"Критическая ошибка в потоке загрузки: {e}", exc_info=True)
            clean_err_msg = clean_ansi(str(e))
            clean_err_msg = re.sub(r'^(?:ERROR:\s*)+', '', clean_err_msg, flags=re.IGNORECASE).strip()
            try:
                self.signals.error.emit(f"Ошибка загрузчика: {clean_err_msg}")
            except RuntimeError:
                pass
        finally:
            logger.info(f"--- ПОТОК ЗАВЕРШЕН: {self.task.url} ---")
            self._monitor_running = False
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

    def _resolve_format_and_pps(self):
        u = self.task.url.lower()
        platform_key = None
        if 'youtube.com' in u or 'youtu.be' in u:
            platform_key = 'quality_youtube'
        elif 'rutube.ru' in u:
            platform_key = 'quality_rutube'
        elif 'tiktok.com' in u:
            platform_key = 'quality_tiktok'
        elif 'instagram.com' in u:
            platform_key = 'quality_instagram'
        elif 'vk.com' in u or 'vkvideo.ru' in u:
            platform_key = 'quality_vk'
        elif 'pornhub.com' in u:
            platform_key = 'quality_pornhub'
        elif 'facebook.com' in u or 'fb.watch' in u:
            platform_key = 'quality_facebook'
        elif 'twitter.com' in u or 'x.com' in u:
            platform_key = 'quality_x_twitter'
        elif 'kinopoisk.ru' in u:
            platform_key = 'quality_kinopoisk'
        elif 'twitch.tv' in u:
            platform_key = 'quality_twitch'
        elif 'kick.com' in u:
            platform_key = 'quality_kick'
        elif 'kinopub' in u or 'kino.pub' in u or 'rezka' in u or 'voidboost' in u:
            platform_key = 'quality_kinopub'
        elif 'animego' in u or 'aniboom' in u or 'kodik' in u:
            platform_key = 'quality_animego'
        elif 'vi3000' in u or 'lampa' in u or 'cub' in u:
            platform_key = 'quality_lampa'
        elif 'pinterest.com' in u or 'pin.it' in u:
            platform_key = 'quality_pinterest'

        task_override = getattr(self.task, 'quality_override', None)
        task_audio_only = getattr(self.task, 'audio_only', False)

        if task_audio_only or task_override in ('audio_only', 'audio_mp3'):
            fmt = 'bestaudio/best'
            merge_fmt = None
            audio_codec = 'mp3' if task_override == 'audio_mp3' else str(self.settings.value('audio_format', 'mp3')).lower()
            audio_quality = '320' if task_override == 'audio_mp3' else str(self.settings.value('audio_bitrate', '192'))
            if audio_quality == 'VBR/Best':
                audio_quality = '0'
            pps = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_codec,
                'preferredquality': audio_quality,
            }]
            if self.settings.value('embed_metadata', True, type=bool):
                pps.append({'key': 'FFmpegMetadata', 'add_metadata': True})
            if self.settings.value('embed_thumbnail', True, type=bool):
                pps.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})
            return fmt, merge_fmt, pps
        elif task_override and (task_override.endswith('p') or task_override.isdigit()):
            h = task_override.rstrip('p')
            is_yt = ('youtube.com' in u or 'youtu.be' in u)
            if is_yt:
                fmt = (
                    f'bestvideo[format_note!*=Premium][height<={h}][ext=mp4]+bestaudio[ext=m4a]/'
                    f'bestvideo[format_note!*=Premium][height<={h}]+bestaudio/'
                    f'bestvideo[format_note!*=Premium][width<={h}]+bestaudio/'
                    f'bestvideo[format_note!*=Premium]+bestaudio/'
                    f'best[height<={h}]/best'
                )
            else:
                fmt = (
                    f'bestvideo[height<={h}]+bestaudio/'
                    f'bestvideo[width<={h}]+bestaudio/'
                    f'bestvideo[height<={h}]/'
                    f'best[height<={h}]/'
                    f'bestvideo+bestaudio/'
                    f'best/b/all'
                )
            return fmt, 'mp4', []
        elif task_override == 'best':
            is_yt = ('youtube.com' in u or 'youtu.be' in u)
            if is_yt:
                fmt = 'bestvideo[format_note!*=Premium][ext=mp4]+bestaudio[ext=m4a]/bestvideo[format_note!*=Premium]+bestaudio/best'
            else:
                fmt = 'bestvideo+bestaudio/best'
            return fmt, 'mp4', []

        fmt = self.settings.value(platform_key, '') if platform_key else ''
        pps = []
        merge_fmt = 'mp4'

        codec_pref = self.settings.value('video_codec_preference', 'auto')
        is_yt = ('youtube.com' in u or 'youtu.be' in u)

        if not fmt or fmt == 'best':
            if is_yt:
                if codec_pref == 'h264':
                    fmt = 'bestvideo[format_note!*=Premium][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[format_note!*=Premium][vcodec^=avc1]+bestaudio/bestvideo[format_note!*=Premium][ext=mp4]+bestaudio[ext=m4a]/bestvideo[format_note!*=Premium]+bestaudio/best'
                elif codec_pref == 'av1_vp9':
                    fmt = 'bestvideo[format_note!*=Premium][vcodec^=av01|vcodec^=vp9]+bestaudio/bestvideo[format_note!*=Premium]+bestaudio/best'
                else:
                    fmt = 'bestvideo[format_note!*=Premium][ext=mp4]+bestaudio[ext=m4a]/bestvideo[format_note!*=Premium]+bestaudio/best'
            else:
                fmt = 'bestvideo+bestaudio/best'
        elif fmt == 'bestaudio/best':
            merge_fmt = None
            audio_codec = str(self.settings.value('audio_format', 'mp3')).lower()
            audio_quality = str(self.settings.value('audio_bitrate', '192'))
            if audio_quality == 'VBR/Best':
                audio_quality = '0'
            pps.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_codec,
                'preferredquality': audio_quality,
            })
            if self.settings.value('embed_metadata', True, type=bool):
                pps.append({'key': 'FFmpegMetadata', 'add_metadata': True})
            if self.settings.value('embed_thumbnail', True, type=bool):
                pps.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})
        elif fmt == 'video_only_stripped':
            fmt = 'bestvideo[format_note!*=Premium]/bestvideo/best' if is_yt else 'bestvideo/best'
        elif fmt == 'worst':
            fmt = 'worstvideo+worstaudio/worst'
        elif '[height<=' in fmt:
            h_match = re.search(r'height<=(\d+)', fmt)
            if h_match:
                h = h_match.group(1)
                if is_yt:
                    if codec_pref == 'h264' and '[vcodec' not in fmt:
                        fmt = f'bestvideo[format_note!*=Premium][height<={h}][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[format_note!*=Premium][width<={h}][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[format_note!*=Premium][height<={h}]+bestaudio/best[height<={h}]/best'
                    elif codec_pref == 'av1_vp9' and '[vcodec' not in fmt:
                        fmt = f'bestvideo[format_note!*=Premium][height<={h}][vcodec^=av01|vcodec^=vp9]+bestaudio/bestvideo[format_note!*=Premium][width<={h}][vcodec^=av01|vcodec^=vp9]+bestaudio/bestvideo[format_note!*=Premium][height<={h}]+bestaudio/best[height<={h}]/best'
                    else:
                        fmt = f'bestvideo[format_note!*=Premium][height<={h}]+bestaudio/bestvideo[format_note!*=Premium][width<={h}]+bestaudio/bestvideo[format_note!*=Premium]+bestaudio/best[height<={h}]/best'
                else:
                    fmt = f'bestvideo[height<={h}]+bestaudio/bestvideo[width<={h}]+bestaudio/bestvideo[height<={h}]/best[height<={h}]/bestvideo+bestaudio/best/b/all'

        if ('youtube.com' in u or 'youtu.be' in u) and fmt and fmt != 'bestaudio/best':
            parts = fmt.split('/')
            clean_parts = []
            for part in parts:
                if 'bestvideo' in part and '[format_note!*=Premium]' not in part:
                    part = part.replace('bestvideo', 'bestvideo[format_note!*=Premium]')
                if (part == 'best' or part.startswith('best[')) and '[format_note!*=Premium]' not in part:
                    part = part.replace('best', 'best[format_note!*=Premium]', 1)
                clean_parts.append(part)
            fmt = '/'.join(clean_parts)

        return fmt, merge_fmt, pps

    def _run_standard_vod(self, save_path):
        self.task.is_stream_mode = False
        logger.debug(f"[VOD] Папка сохранения: {save_path}")
        self._start_time = time.time()

        try:
            free_space = shutil.disk_usage(save_path).free
            if free_space < 100 * 1024 * 1024:
                raise OSError(f"Недостаточно свободного места на диске ({free_space // (1024*1024)} МБ доступно)")
        except OSError as e:
            if "Недостаточно свободного места" in str(e):
                raise
            logger.warning(f"Не удалось проверить свободное место на диске: {e}")

        fmt, merge_fmt, extra_pps = self._resolve_format_and_pps()

        custom_t = getattr(self.task, 'custom_title', None)
        task_t = getattr(self.task, 'title', None)
        base_title = (custom_t.strip() if custom_t else "") or (task_t.strip() if task_t and task_t not in ("...", "") else "")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", base_title).strip() if base_title else ""
        safe_title = safe_title[:150]

        # Определение тега качества для уникальности имени файла
        raw_badge = (getattr(self.task, 'quality_badge', '') or getattr(self.task, 'custom_quality', '') or "").replace(' ▾', '').strip()
        is_audio = getattr(self.task, 'audio_only', False) or getattr(self.task, 'quality_override', '') in ('audio_only', 'audio_mp3') or fmt == 'bestaudio/best'

        q_tag = ""
        if is_audio:
            q_tag = "MP3"
        elif raw_badge:
            m_b = re.search(r'(\d{3,4}p|4K|2K|AUDIO|MP3)', raw_badge, re.IGNORECASE)
            q_tag = m_b.group(1) if m_b else raw_badge
        elif getattr(self.task, 'quality_override', None):
            qo = str(self.task.quality_override).strip()
            if qo.isdigit():
                q_tag = f"{qo}p"
            elif qo.endswith('p'):
                q_tag = qo
        elif '[height<=' in fmt:
            h_m = re.search(r'height<=(\d+)', fmt)
            if h_m:
                q_tag = f"{h_m.group(1)}p"

        if not q_tag:
            u_m = re.search(r'[/_\[\(](\d{3,4})p?[\._/\]\)]', self.task.url)
            if u_m:
                q_tag = f"{u_m.group(1)}p"

        time_range = getattr(self.task, 'time_range', None)
        range_suffix = ""
        if time_range:
            s_sec, e_sec = time_range
            s_str = f"{int(s_sec//3600):02d}-{int((s_sec%3600)//60):02d}-{int(s_sec%60):02d}" if s_sec >= 3600 else f"{int(s_sec//60):02d}-{int(s_sec%60):02d}"
            e_str = f"{int(e_sec//3600):02d}-{int((e_sec%3600)//60):02d}-{int(e_sec%60):02d}" if e_sec >= 3600 else f"{int(e_sec//60):02d}-{int(e_sec%60):02d}"
            range_suffix = f"_[{s_str}_{e_str}]"

        q_suffix = ""
        if q_tag:
            if safe_title:
                safe_title = re.sub(r'\s*\[\s*(?:\d{3,4}p|MP3|AUDIO|4K|2K)\s*\]\s*$', '', safe_title, flags=re.IGNORECASE).strip()
            q_suffix = f" [{q_tag}]"

        filename_tpl = str(self.settings.value('filename_template', '{title} [{quality}]') or '{title} [{quality}]')
        out_template = StreamResolverHelper.resolve_output_template(
            save_path=save_path,
            template=filename_tpl,
            task=self.task,
            quality_tag=q_tag,
            range_suffix=range_suffix,
            is_ytdlp=True,
            create_dirs=True,
        )
        out_dir = os.path.dirname(out_template) or save_path

        referer_url = getattr(self.task, 'referer', None)
        if not referer_url:
            if 'nip.io' in self.task.url or 'alloha' in self.task.url:
                referer_url = 'https://vi3000.top/'
            else:
                referer_url = StreamResolverHelper.get_stream_referer(self.task.url, default_referer='https://kinopub.me/')

        ydl_opts = {
            'outtmpl': out_template,
            'format': fmt,
            'overwrites': True,
            'ffmpeg_location': self.ffmpeg_path,
            'progress_hooks': [self.simple_progress_hook],
            'postprocessor_hooks': [self.simple_pp_hook],
            'quiet': True,
            'noprogress': True,
            'noplaylist': True,
            'ignoreerrors': False,
            'nocheckcertificate': True,
            'color': 'never',
            'enable_js': True,
            'remote_components': {'ejs:github': True},

            # --- ЗАЩИТА ОТ РАЗРЫВА СОЕДИНЕНИЯ С СЕРВЕРОМ ---
            'retries': 30,  # Количество попыток переподключения
            'fragment_retries': 30,  # Количество попыток для отдельных фрагментов
            'file_access_retries': 10,  # Попытки доступа к файлу
            'continuedl': True,  # Обязательно докачивать файл при обрыве
            # -----------------------------------------------
            'postprocessors': list(extra_pps)
        }

        if not ('youtube.com' in self.task.url or 'youtu.be' in self.task.url):
            ydl_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Referer': referer_url,
                'Origin': referer_url.strip('/')
            }
            task_headers = getattr(self.task, 'http_headers', None)
            if task_headers and isinstance(task_headers, dict):
                ydl_opts['http_headers'].update(task_headers)
            task_cookies = getattr(self.task, 'cookies', None)
            if task_cookies and isinstance(task_cookies, dict):
                ydl_opts['http_headers']['Cookie'] = '; '.join(f"{k}={v}" for k, v in task_cookies.items())
        if merge_fmt:
            ydl_opts['merge_output_format'] = merge_fmt

        try:
            speed_limit = int(self.settings.value('speed_limit', 0, type=int) or 0)
        except (ValueError, TypeError):
            speed_limit = 0
        if speed_limit > 0:
            ydl_opts['ratelimit'] = speed_limit

        # Ускорение скачивания: многопоточная загрузка фрагментов HLS/DASH потоков (Rezka, Lampa, Rutube, YouTube)
        concurrent_frags = self.settings.value('concurrent_fragments', 8, type=int)
        if concurrent_frags > 1:
            ydl_opts['concurrent_fragment_downloads'] = concurrent_frags

        # Оптимизация сети, сетевых буферов и устойчивость к обрывам
        ydl_opts['buffersize'] = 1024 * 1024  # 1 MB сетевой буфер
        ydl_opts['http_chunk_size'] = 10 * 1024 * 1024  # 10 MB чанки для потоков
        ydl_opts['socket_timeout'] = 30
        ydl_opts['extractor_retries'] = 5

        # Многопоточный FFmpeg для быстрой склейки
        ydl_opts['postprocessor_args'] = {
            'ffmpeg': ['-threads', '0']
        }

        use_cookies = self.settings.value('use_cookies', False, type=bool)
        if use_cookies:
            source_type = self.settings.value('cookie_source_type', 'file')
            if source_type == 'file':
                cookie_file = self.settings.value('cookies_path', '')
                if cookie_file and os.path.exists(cookie_file):
                    ydl_opts['cookiefile'] = cookie_file
            else:
                # ИЗОЛЯЦИЯ: Живые куки браузера запрашиваются строго для YouTube.
                # Для AnimeGO, Kodik, Rutube, TikTok, Lampa и прямых m3u8/mp4 потоков куки браузера не трогаются.
                is_yt = ('youtube.com' in self.task.url.lower() or 'youtu.be' in self.task.url.lower())
                if is_yt:
                    browser = self.settings.value('cookie_browser', self.settings.value('cookie_source', 'none'))
                    if browser and browser != 'none':
                        try:
                            from .browser_cookies import get_best_browser_cookiefile
                            live_file, count, b_name = get_best_browser_cookiefile(browser)
                            if live_file and count > 0:
                                ydl_opts['cookiefile'] = live_file
                        except Exception as e:
                            logger.warning(f"Ошибка загрузки куки: {e}")

        if self.settings.value('sponsorblock_enabled', False, type=bool):
            sb_categories = ['sponsor', 'intro', 'outro', 'selfpromo', 'interaction']
            ydl_opts['postprocessors'].append({
                'key': 'SponsorBlock',
                'categories': sb_categories,
            })
            ydl_opts['postprocessors'].append({
                'key': 'ModifyChapters',
                'remove_sponsor_segments': sb_categories,
            })

        if self.settings.value('subtitles_enabled', False, type=bool):
            raw_langs = str(self.settings.value('subtitles_langs', 'ru, en') or 'ru, en')
            sub_langs = StreamResolverHelper.parse_subtitle_langs(raw_langs)
            sub_mode = str(self.settings.value('subtitles_mode', 'embed') or 'embed')
            sub_fmt = str(self.settings.value('subtitles_format', 'srt') or 'srt').lower()
            if sub_fmt not in ('srt', 'vtt', 'ass'):
                sub_fmt = 'srt'

            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = False
            ydl_opts['subtitleslangs'] = sub_langs
            ydl_opts['subtitlesformat'] = f"{sub_fmt}/best"
            ydl_opts['ignoreerrors'] = 'only_download'  # Не обрывать загрузку видео при сбое дорожки субтитров

            if sub_mode in ('separate', 'both'):
                ydl_opts['postprocessors'].append({
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': sub_fmt,
                })
            if sub_mode in ('embed', 'both'):
                ydl_opts['postprocessors'].append({
                    'key': 'FFmpegEmbedSubtitle',
                    'when': 'post_process',
                    'already_have_subtitle': (sub_mode == 'both'),
                })

        if not ydl_opts['postprocessors']:
            del ydl_opts['postprocessors']

        is_yt = ('youtube.com' in self.task.url or 'youtu.be' in self.task.url)
        needs_post_trim = False
        if time_range:
            start_s, end_s = time_range
            if is_yt:
                # YouTube CDN блокирует прямые сегментные запросы через внешний FFmpeg (HTTP 403 Forbidden).
                # Скачиваем видео штатным загрузчиком yt-dlp и мгновенно обрезаем локальным FFmpeg.
                needs_post_trim = True
            else:
                ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func([], [(float(start_s), float(end_s))])
                ydl_opts['force_keyframes_at_cuts'] = True

        if fmt == 'bestaudio/best' and self.settings.value('embed_thumbnail', True, type=bool):
            ydl_opts['writethumbnail'] = True

        # === ЗАПУСК СКАЧИВАНИЯ ===
        if StreamResolverHelper.is_kodik_stream(self.task.url):
            self.task.url = StreamResolverHelper.clean_stream_url(self.task.url)

        u_clean = self.task.url.lower().split('?')[0]
        is_direct_stream = (StreamResolverHelper.is_kodik_stream(u_clean) or
                            u_clean.endswith(('.mp4', '.mkv', '.webm'))) and not time_range
        if is_direct_stream:
            if StreamResolverHelper.is_kodik_stream(self.task.url) and q_tag:
                self.task.url = StreamResolverHelper.replace_quality(self.task.url, q_tag)
            referer_url = StreamResolverHelper.get_stream_referer(self.task.url, default_referer=referer_url)
            logger.info(f"[VOD] Обнаружен прямой видеопоток: {self.task.url}. Запуск прямого быстрого скачивания...")
            try:
                self._download_direct_stream(save_path, out_template, referer_url)
                return
            except Exception as direct_err:
                logger.warning(f"[VOD] Прямое скачивание потока вызвало ошибку ({direct_err}), пробуем через yt-dlp...")

        # Подключение внешнего мультисегментного ускорителя aria2c (при наличии)
        aria2c_exe = get_aria2c_path()
        if aria2c_exe and self.settings.value('enable_aria2c', True, type=bool) and not time_range:
            logger.info(f"[VOD] Обнаружен ускоритель aria2c: {aria2c_exe}. Подключение мультисегментного загрузчика...")
            ydl_opts['external_downloader'] = aria2c_exe
            ydl_opts['external_downloader_args'] = {
                'aria2c': ['-x', '8', '-s', '8', '-k', '1M', '-j', '4']
            }

        ytdl_logger = _YtdlLogger(logger)
        ydl_opts['logger'] = ytdl_logger

        def _execute_download(opts):
            with yt_dlp.YoutubeDL(opts) as ydl:
                logger.info("[VOD] yt-dlp: Начинаем скачивание...")
                if self.task.is_stop_requested() or self._cancel_requested:
                    raise yt_dlp.utils.DownloadCancelled("Stopped")
                ret_code = ydl.download([self.task.url])
                logger.info(f"[VOD] yt-dlp: Завершено с кодом {ret_code}.")
                if ret_code != 0:
                    err_msg = ytdl_logger.last_error or f"yt-dlp завершился с кодом ошибки {ret_code}"
                    raise yt_dlp.utils.DownloadError(err_msg)

        try:
            _execute_download(ydl_opts)
        except yt_dlp.utils.DownloadCancelled:
            raise
        except Exception as e:
            err_str = str(e).lower()
            if any(d in err_str for d in ('unable to download webpage', '10054', 'connectionreset', 'connection aborted')):
                if any(d in self.task.url.lower() for d in ('solodcdn', 'rooster.cloud2')) or self.task.url.lower().split('?')[0].endswith(('.mp4', '.mkv', '.webm', '.ts', '.mov', '.avi')):
                    if any(d in self.task.url for d in ('solodcdn', 'kodik')) and q_tag and q_tag.endswith('p'):
                        h_digits = q_tag[:-1]
                        if re.search(r'/\d{3,4}\.mp4', self.task.url):
                            self.task.url = re.sub(r'/\d{3,4}\.mp4', f'/{h_digits}.mp4', self.task.url)
                    logger.warning(f"Прямой поток Kodik/MP4 вызвал сброс соединения ({e}). Запуск прямого HTTP потока...")
                    self._download_direct_stream(save_path, out_template, referer_url)
                    return
            if 'requested format is not available' in err_str:
                logger.warning(f"Запрошенный формат недоступен ({e}). Пробуем универсальный fallback (bestvideo+bestaudio/best)...")
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
                try:
                    _execute_download(ydl_opts)
                    return
                except Exception as fmt_fallback_err:
                    e = fmt_fallback_err
                    err_str = str(e).lower()
            if 'download_ranges' in ydl_opts:
                logger.warning(f"Прямое скачивание отрезка не удалось ({e}). Скачиваем видео целиком и обрежем локально...")
                ydl_opts.pop('download_ranges', None)
                ydl_opts.pop('force_keyframes_at_cuts', None)
                needs_post_trim = True
                try:
                    _execute_download(ydl_opts)
                except Exception as range_retry_err:
                    e = range_retry_err
                    err_str = str(e).lower()
            if ('cookie' in err_str or 'dpapi' in err_str) and ('cookiesfrombrowser' in ydl_opts or 'cookiefile' in ydl_opts):
                logger.warning(f"Сбой из-за куки ({e}), повторяем скачивание без куки...")
                ydl_opts.pop('cookiesfrombrowser', None)
                ydl_opts.pop('cookiefile', None)
                try:
                    _execute_download(ydl_opts)
                except Exception as retry_err:
                    retry_err_str = str(retry_err).lower()
                    if ('subtitle' in retry_err_str or '429' in retry_err_str) and ('writesubtitles' in ydl_opts or 'writeautomaticsub' in ydl_opts):
                        logger.warning(f"Сбой субтитров в повторе ({retry_err}), завершаем скачивание видео без субтитров...")
                        ydl_opts.pop('writesubtitles', None)
                        ydl_opts.pop('writeautomaticsub', None)
                        ydl_opts.pop('subtitleslangs', None)
                        if 'postprocessors' in ydl_opts:
                            ydl_opts['postprocessors'] = [p for p in ydl_opts['postprocessors'] if p.get('key') != 'FFmpegEmbedSubtitle']
                            if not ydl_opts['postprocessors']:
                                del ydl_opts['postprocessors']
                        _execute_download(ydl_opts)
                    elif 'empty' in retry_err_str or 'fragment' in retry_err_str or '403' in retry_err_str:
                        logger.warning(f"Сбой фрагментов в повторе ({retry_err}), переключаемся на совместимый поток...")
                        ydl_opts['format'] = 'bestvideo[format_note!*=Premium][protocol^=http]+bestaudio[protocol^=http]/bestvideo[format_note!*=Premium]+bestaudio/best[format_note!*=Premium]/best/worst'
                        _execute_download(ydl_opts)
                    else:
                        raise retry_err
            elif ('subtitle' in err_str or '429' in err_str) and ('writesubtitles' in ydl_opts or 'writeautomaticsub' in ydl_opts):
                logger.warning(f"Сбой скачивания субтитров ({e}), повторяем скачивание видео без субтитров...")
                ydl_opts.pop('writesubtitles', None)
                ydl_opts.pop('writeautomaticsub', None)
                ydl_opts.pop('subtitleslangs', None)
                if 'postprocessors' in ydl_opts:
                    ydl_opts['postprocessors'] = [p for p in ydl_opts['postprocessors'] if p.get('key') != 'FFmpegEmbedSubtitle']
                    if not ydl_opts['postprocessors']:
                        del ydl_opts['postprocessors']
                try:
                    _execute_download(ydl_opts)
                except Exception as sub_retry_err:
                    sub_retry_str = str(sub_retry_err).lower()
                    if 'empty' in sub_retry_str or 'fragment' in sub_retry_str or '403' in sub_retry_str:
                        logger.warning(f"Сбой фрагментов ({sub_retry_err}), переключаемся на совместимый поток...")
                        ydl_opts['format'] = 'bestvideo[format_note!*=Premium][protocol^=http]+bestaudio[protocol^=http]/bestvideo[format_note!*=Premium]+bestaudio/best[format_note!*=Premium]/best/worst'
                        _execute_download(ydl_opts)
                    else:
                        raise
            elif 'empty' in err_str or 'fragment' in err_str or '403' in err_str:
                logger.warning(f"Сбой фрагментов/потока ({e}). Пробуем скачать совместимый формат без m3u8/premium...")
                ydl_opts['format'] = 'bestvideo[format_note!*=Premium][protocol^=http]+bestaudio[protocol^=http]/bestvideo[format_note!*=Premium]+bestaudio/best[format_note!*=Premium]/best/worst'
                try:
                    _execute_download(ydl_opts)
                except Exception as stream_err:
                    stream_err_str = str(stream_err).lower()
                    # Если прямой DASH поток заблокирован, пробуем прогрессивный поток (например, format 18/22)
                    if '403' in stream_err_str or 'empty' in stream_err_str:
                        logger.info("Попытка загрузки через прогрессивный поток best/worst...")
                        ydl_opts['format'] = 'best/worst'
                        try:
                            _execute_download(ydl_opts)
                        except Exception as prog_err:
                            prog_err_str = str(prog_err).lower()
                            # Если YouTube блокирует 403 даже прогрессивный поток без куки, пробуем резервные куки браузера
                            if is_yt and ('403' in prog_err_str or 'sign in' in prog_err_str or 'empty' in prog_err_str) and not ydl_opts.get('cookiefile'):
                                rescued = False
                                try:
                                    from .browser_cookies import get_best_browser_cookiefile
                                    for b in ('edge', 'chrome', 'yandex', 'firefox', 'brave', 'opera'):
                                        live_file, count, b_name = get_best_browser_cookiefile(b)
                                        if live_file and count > 0:
                                            logger.info(f"YouTube заблокировал анонимный доступ (403). Автоматически подключаем cookies из {b_name}...")
                                            ydl_opts['cookiefile'] = live_file
                                            ydl_opts['format'] = fmt
                                            _execute_download(ydl_opts)
                                            rescued = True
                                            break
                                except Exception as rescue_err:
                                    logger.warning(f"Авто-восстановление через cookies не удалось: {rescue_err}")
                                if not rescued:
                                    raise yt_dlp.utils.DownloadError(
                                        "YouTube заблокировал анонимное скачивание (HTTP 403). Для этого видео требуются cookies (включите в Настройках)."
                                    )
                            else:
                                raise prog_err
                    else:
                        raise
            else:
                raise

        time.sleep(1.5)

        final_file = None
        valid_exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4a', '.mp3')

        # 1. Приоритет: точный файл, перехваченный через хуки yt-dlp
        if getattr(self, '_last_downloaded_filename', None):
            candidate = self._last_downloaded_filename
            if os.path.exists(candidate) and candidate.endswith(valid_exts) and not candidate.endswith('.part') and os.path.getsize(candidate) > 1024:
                final_file = candidate
            else:
                base_cand, _ = os.path.splitext(candidate)
                base_cand = re.sub(r'\.[a-z]{2}(?:-[A-Za-z]+)?$', '', base_cand)
                for ext in valid_exts:
                    if os.path.exists(base_cand + ext) and os.path.getsize(base_cand + ext) > 1024:
                        final_file = base_cand + ext
                        break

        # 2. Поиск по целевому названию в папке сохранения
        search_dir = out_dir if os.path.isdir(out_dir) else save_path
        target_name = f"{safe_title}{q_suffix}" if safe_title else ""
        if not final_file and target_name:
            candidates = [os.path.join(search_dir, f) for f in os.listdir(search_dir)
                          if f.startswith(target_name) and f.endswith(valid_exts) and not f.endswith('.part')]
            if candidates:
                final_file = max(candidates, key=os.path.getmtime)
            elif safe_title:
                candidates = [os.path.join(search_dir, f) for f in os.listdir(search_dir)
                              if f.startswith(safe_title) and f.endswith(valid_exts) and not f.endswith('.part')]
                if candidates:
                    final_file = max(candidates, key=os.path.getmtime)

        # 3. Запасной план: поиск самого свежего подходящего файла
        if not final_file:
            list_of_files = [os.path.join(search_dir, f) for f in os.listdir(search_dir)
                             if f.endswith(valid_exts) and not f.endswith('.part')]
            if list_of_files:
                latest_file = max(list_of_files, key=os.path.getmtime)
                if os.path.getmtime(latest_file) >= (self._start_time - 10):
                    final_file = latest_file

        if needs_post_trim and time_range and final_file and os.path.exists(final_file):
            final_file = self._trim_media_file(final_file, time_range[0], time_range[1])
            self._last_downloaded_filename = final_file

        if is_audio and final_file and os.path.exists(final_file) and not final_file.lower().endswith(('.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg')):
            logger.info(f"[VOD] Пост-извлечение MP3 звука из видео: {final_file}")
            self.task.update_progress(96, "Извлечение MP3 звука...")
            mp3_path = os.path.splitext(final_file)[0] + '.mp3'
            cmd = [
                self.ffmpeg_path, '-y',
                '-i', final_file,
                '-vn',
                '-acodec', 'libmp3lame',
                '-b:a', '320k',
                mp3_path
            ]
            try:
                creationflags = 0x08000000 if sys.platform == 'win32' else 0
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                if res.returncode == 0 and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 1024:
                    try:
                        os.remove(final_file)
                    except OSError:
                        pass
                    final_file = mp3_path
            except Exception as e_conv:
                logger.warning(f"Ошибка пост-конвертации в MP3: {e_conv}")

        if final_file and os.path.exists(final_file) and os.path.getsize(final_file) > 1024:
            base_fname = os.path.splitext(os.path.basename(final_file))[0]
            if getattr(self.task, 'custom_title', None):
                self.task.title = self.task.custom_title
            elif not getattr(self.task, 'title', None) or self.task.title in ("...", ""):
                self.task.title = base_fname
            actual_size = os.path.getsize(final_file)
            self.task.set_file_size(actual_size, force=True)
            self.task.info_updated.emit()
            logger.info(f"[VOD] Найден финальный файл: {final_file} ({actual_size} байт)")
            self.task.update_progress(100, "Скачано")
            self.task.set_completed(final_file)
        else:
            raise Exception("Сбой скачивания: Файл пуст или yt-dlp не смог обработать поток.")

    def _download_direct_stream(self, _save_path, out_template, referer_url):
        self.task.is_stream_mode = False
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Referer': referer_url,
            'Origin': referer_url.rstrip('/')
        }
        raw_target = out_template.replace('.%(ext)s', '.mp4') if '.%(ext)s' in out_template else out_template
        target_path = raw_target if raw_target.endswith(('.mp4', '.mkv', '.webm')) else f"{raw_target}.mp4"
        part_path = target_path + '.part'

        session = requests.Session()
        session.trust_env = False
        task_cookies = getattr(self.task, 'cookies', None)
        if task_cookies and isinstance(task_cookies, dict):
            session.cookies.update(task_cookies)
        task_headers = getattr(self.task, 'http_headers', None)
        if task_headers and isinstance(task_headers, dict):
            headers.update(task_headers)

        # 1. Проверяем URL и при необходимости выполняем каскадный fallback при 404
        r = session.get(self.task.url, headers=headers, stream=True, verify=False, timeout=15)
        if r.status_code == 404 and any(d in self.task.url for d in ('solodcdn', 'kodik')):
            for fallback_h in ['720', '480', '360']:
                if f'/{fallback_h}.mp4' not in self.task.url:
                    fb_url = re.sub(r'/\d{1,4}\.mp4', f'/{fallback_h}.mp4', self.task.url)
                    logger.info(f"[Kodik] Пробуем доступное качество {fallback_h}p вместо 404: {fb_url}")
                    r_fb = session.get(fb_url, headers=headers, stream=True, verify=False, timeout=15)
                    if r_fb.status_code in (200, 206):
                        self.task.url = fb_url
                        if not getattr(self.task, 'audio_only', False):
                            self.task.quality_badge = f"{fallback_h}p"
                        r = r_fb
                        break

        r.raise_for_status()

        cl = r.headers.get('Content-Length')
        total_bytes = int(cl) if cl and cl.isdigit() else 0
        accepts_range = r.headers.get('Accept-Ranges', '').lower() == 'bytes' or r.status_code == 206
        r.close()

        if total_bytes > 0:
            self.task.set_file_size(total_bytes)

        try:
            speed_limit = int(self.settings.value('speed_limit', 0, type=int) or 0)
        except (ValueError, TypeError):
            speed_limit = 0
        multipart_success = False
        try:
            max_cfg_threads = int(self.settings.value('max_chunk_threads', 4, type=int) or 4)
        except (ValueError, TypeError):
            max_cfg_threads = 4
        num_chunks = StreamResolverHelper.calculate_chunk_count(total_bytes, max_configured_threads=max_cfg_threads)

        # 2. Многопоточная параллельная загрузка при поддержке Range и размере > 3 МБ
        if total_bytes >= 3 * 1024 * 1024 and num_chunks > 1 and (accepts_range or any(d in self.task.url for d in ('solodcdn', 'kodik', 'orion'))):
            logger.info(f"[DirectStream] Запуск многопоточного скачивания ({num_chunks} потоков) для {total_bytes} байт...")
            thread_speed_limit = (speed_limit // num_chunks) if speed_limit > 0 else 0
            chunk_size = total_bytes // num_chunks
            chunk_ranges = []
            for i in range(num_chunks):
                start = i * chunk_size
                end = (i + 1) * chunk_size - 1 if i < num_chunks - 1 else total_bytes - 1
                chunk_ranges.append((start, end))

            chunk_downloaded = [0] * num_chunks
            for i, (s, e) in enumerate(chunk_ranges):
                c_path = f"{part_path}.part{i}"
                if os.path.exists(c_path):
                    chunk_downloaded[i] = min(os.path.getsize(c_path), e - s + 1)

            def _download_single_chunk(idx, start_byte, end_byte):
                chunk_file = f"{part_path}.part{idx}"
                existing_len = os.path.getsize(chunk_file) if os.path.exists(chunk_file) else 0
                target_len = end_byte - start_byte + 1
                if existing_len >= target_len:
                    chunk_downloaded[idx] = target_len
                    return True

                for attempt in range(1, 4):
                    if self._cancel_requested or self.task.is_stop_requested():
                        return False
                    try:
                        req_start = start_byte + existing_len
                        req_end = end_byte
                        c_headers = dict(headers)
                        c_headers['Range'] = f'bytes={req_start}-{req_end}'
                        s = requests.Session()
                        s.trust_env = False
                        with s.get(self.task.url, headers=c_headers, stream=True, verify=False, timeout=15) as resp:
                            if resp.status_code not in (200, 206):
                                raise Exception(f"HTTP {resp.status_code}")
                            mode = 'ab' if existing_len > 0 else 'wb'
                            with open(chunk_file, mode) as cf:
                                for chunk in resp.iter_content(chunk_size=128 * 1024):
                                    if self._cancel_requested or self.task.is_stop_requested():
                                        return False
                                    if not chunk:
                                        continue
                                    chunk_t0 = time.time()
                                    cf.write(chunk)
                                    chunk_downloaded[idx] += len(chunk)
                                    existing_len += len(chunk)

                                    if thread_speed_limit > 0:
                                        min_sec = len(chunk) / thread_speed_limit
                                        el = time.time() - chunk_t0
                                        if el < min_sec:
                                            time.sleep(min_sec - el)

                            if os.path.getsize(chunk_file) >= target_len:
                                return True
                    except Exception as c_err:
                        logger.warning(f"[DirectStream] Поток {idx+1}/{num_chunks}: ошибка попытки {attempt}/3 ({c_err})")
                        time.sleep(1.0)
                        existing_len = os.path.getsize(chunk_file) if os.path.exists(chunk_file) else 0

                return False

            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=num_chunks) as executor:
                    futures = [
                        executor.submit(_download_single_chunk, i, s, e)
                        for i, (s, e) in enumerate(chunk_ranges)
                    ]

                    start_t = time.time()
                    last_update_t = start_t
                    last_downloaded = sum(chunk_downloaded)
                    speed_smooth = 0.0

                    while not all(f.done() for f in futures):
                        if self._cancel_requested or self.task.is_stop_requested():
                            self.task.set_status(self.task.Status.STOPPED)
                            return

                        time.sleep(0.3)
                        now = time.time()
                        cur_downloaded = sum(chunk_downloaded)

                        if now - last_update_t >= 0.5:
                            elapsed = now - last_update_t
                            bytes_diff = cur_downloaded - last_downloaded
                            inst_speed = bytes_diff / elapsed if elapsed > 0 else 0
                            speed_smooth = 0.8 * speed_smooth + 0.2 * inst_speed if speed_smooth > 0 else inst_speed
                            last_update_t = now
                            last_downloaded = cur_downloaded

                            pct = int((cur_downloaded / total_bytes) * 100) if total_bytes > 0 else 50
                            speed_str = ""
                            if speed_smooth > 0:
                                b = float(speed_smooth)
                                for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
                                    if b < 1024.0:
                                        speed_str = f"{b:.1f} {unit}"
                                        break
                                    b /= 1024.0
                            self.task.update_progress(pct, f"Скачивание ({num_chunks} потоков)... {speed_str}".strip())

                    results = [f.result() for f in futures]
                    if all(results):
                        with open(part_path, 'wb') as fout:
                            for i in range(num_chunks):
                                c_p = f"{part_path}.part{i}"
                                with open(c_p, 'rb') as fin:
                                    shutil.copyfileobj(fin, fout, length=1024 * 1024)
                                try:
                                    os.remove(c_p)
                                except OSError:
                                    pass
                        multipart_success = True
            except Exception as mp_err:
                logger.warning(f"[DirectStream] Ошибка многопоточной загрузки: {mp_err}")

        # 3. Безопасный Fallback на однопоточный режим при сбое или отсутствии Range
        if not multipart_success:
            if self._cancel_requested or self.task.is_stop_requested():
                self.task.set_status(self.task.Status.STOPPED)
                return

            logger.info("[DirectStream] Переключение на стандартный однопоточный режим загрузки...")
            for i in range(num_chunks):
                c_p = f"{part_path}.part{i}"
                if os.path.exists(c_p):
                    try:
                        os.remove(c_p)
                    except OSError:
                        pass

            existing_bytes = os.path.getsize(part_path) if os.path.exists(part_path) else 0
            headers_single = dict(headers)
            if existing_bytes > 0:
                headers_single['Range'] = f'bytes={existing_bytes}-'

            r = session.get(self.task.url, headers=headers_single, stream=True, verify=False, timeout=15)
            if r.status_code not in (200, 206):
                headers_single.pop('Range', None)
                existing_bytes = 0
                r = session.get(self.task.url, headers=headers_single, stream=True, verify=False, timeout=15)
            r.raise_for_status()

            mode = 'ab' if existing_bytes > 0 else 'wb'
            downloaded = existing_bytes
            start_t = time.time()
            last_update_t = start_t
            last_downloaded = downloaded
            speed_smooth = 0.0

            with open(part_path, mode) as f:
                for chunk in r.iter_content(chunk_size=512 * 1024):
                    if self._cancel_requested or self.task.is_stop_requested():
                        r.close()
                        self.task.set_status(self.task.Status.STOPPED)
                        return
                    if not chunk:
                        continue
                    chunk_t0 = time.time()
                    f.write(chunk)
                    downloaded += len(chunk)

                    if speed_limit > 0:
                        min_sec = len(chunk) / speed_limit
                        el = time.time() - chunk_t0
                        if el < min_sec:
                            time.sleep(min_sec - el)

                    now = time.time()
                    if now - last_update_t >= 0.5:
                        elapsed = now - last_update_t
                        bytes_diff = downloaded - last_downloaded
                        inst_speed = bytes_diff / elapsed if elapsed > 0 else 0
                        speed_smooth = 0.8 * speed_smooth + 0.2 * inst_speed if speed_smooth > 0 else inst_speed
                        last_update_t = now
                        last_downloaded = downloaded

                        pct = int((downloaded / total_bytes) * 100) if total_bytes > 0 else 50
                        speed_str = ""
                        if speed_smooth > 0:
                            b = float(speed_smooth)
                            for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
                                if b < 1024.0:
                                    speed_str = f"{b:.1f} {unit}"
                                    break
                                b /= 1024.0
                        self.task.update_progress(pct, f"Скачивание... {speed_str}".strip())
            r.close()

        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except OSError:
                pass
        os.rename(part_path, target_path)

        is_audio_mode = getattr(self.task, 'audio_only', False) or getattr(self.task, 'quality_override', '') in ('audio_only', 'audio_mp3') or getattr(self.task, 'quality_badge', '') in ('MP3', 'AUDIO')
        if is_audio_mode and os.path.exists(target_path) and not target_path.lower().endswith(('.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg')):
            self.task.update_progress(96, "Извлечение MP3 звука...")
            mp3_path = os.path.splitext(target_path)[0] + '.mp3'
            cmd = [
                self.ffmpeg_path, '-y',
                '-i', target_path,
                '-vn',
                '-acodec', 'libmp3lame',
                '-b:a', '320k',
                mp3_path
            ]
            try:
                creationflags = 0x08000000 if sys.platform == 'win32' else 0
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                if res.returncode == 0 and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 1024:
                    try:
                        os.remove(target_path)
                    except OSError:
                        pass
                    target_path = mp3_path
            except Exception as e_conv:
                logger.warning(f"Ошибка конвертации в MP3: {e_conv}")

        if os.path.exists(target_path) and os.path.getsize(target_path) > 1024:
            base_fname = os.path.splitext(os.path.basename(target_path))[0]
            if getattr(self.task, 'custom_title', None):
                self.task.title = self.task.custom_title
            elif not getattr(self.task, 'title', None) or self.task.title in ("...", ""):
                self.task.title = base_fname
            actual_size = os.path.getsize(target_path)
            self.task.set_file_size(actual_size, force=True)
            self.task.info_updated.emit()
            logger.info(f"[VOD] Прямой поток успешно сохранен: {target_path} ({actual_size} байт)")
            self.task.update_progress(100, "Скачано")
            self.task.set_completed(target_path)
        else:
            raise Exception("Сбой прямого скачивания: Файл пуст или не был сохранен.")

    def _trim_media_file(self, file_path, start_s, end_s):
        logger.info(f"[VOD] Локальная обрезка отрезка {start_s}s - {end_s}s для файла: {file_path}")
        self.task.update_progress(99, "Обрезка отрезка...")
        try:
            self.signals.progress.emit(99, "Обрезка отрезка...")
        except Exception:
            pass
        base, ext = os.path.splitext(file_path)
        tmp_cut = f"{base}_cut{ext}"

        # 1. Сначала пробуем мгновенный stream copy (-c copy)
        cmd_copy = [
            self.ffmpeg_path, '-y',
            '-ss', str(float(start_s)),
            '-to', str(float(end_s)),
            '-i', file_path,
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            tmp_cut
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        success = False
        try:
            r = subprocess.run(
                cmd_copy,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=creationflags,
                encoding='utf-8',
                errors='replace'
            )
            if r.returncode == 0 and os.path.exists(tmp_cut) and os.path.getsize(tmp_cut) > 1024:
                success = True
            else:
                logger.warning(f"[VOD] Stream copy завершился с кодом {r.returncode}")
        except Exception as e:
            logger.warning(f"[VOD] Stream copy вызвал ошибку: {e}")

        # 2. Если copy не подошёл, обрезаем с быстрой перекодировкой
        if not success:
            logger.info("[VOD] Обрезка с быстрой перекодировкой через FFmpeg...")
            cmd_encode = [
                self.ffmpeg_path, '-y',
                '-ss', str(float(start_s)),
                '-to', str(float(end_s)),
                '-i', file_path,
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
                tmp_cut
            ]
            try:
                r = subprocess.run(
                    cmd_encode,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    creationflags=creationflags,
                    encoding='utf-8',
                    errors='replace'
                )
                if r.returncode == 0 and os.path.exists(tmp_cut) and os.path.getsize(tmp_cut) > 1024:
                    success = True
                else:
                    logger.error(f"[VOD] Перекодирование завершилось с кодом {r.returncode}")
            except Exception as e:
                logger.error(f"[VOD] Ошибка перекодирования отрезка: {e}")

        if success and os.path.exists(tmp_cut) and os.path.getsize(tmp_cut) > 1024:
            try:
                os.replace(tmp_cut, file_path)
                logger.info(f"[VOD] Успешно сохранён отрезок: {file_path}")
                return file_path
            except Exception:
                try:
                    os.remove(file_path)
                    os.rename(tmp_cut, file_path)
                    return file_path
                except Exception:
                    return tmp_cut
        return file_path

    def _run_twitch_stream(self, save_path):
        self.task.is_stream_mode = True
        self._start_time = time.time()

        try:
            free_space = shutil.disk_usage(save_path).free
            if free_space < 100 * 1024 * 1024:
                raise OSError(f"Недостаточно свободного места на диске ({free_space // (1024*1024)} МБ доступно)")
        except OSError as e:
            if "Недостаточно свободного места" in str(e):
                raise
            logger.warning(f"Не удалось проверить свободное место на диске: {e}")

        fmt, merge_fmt, extra_pps = self._resolve_format_and_pps()
        ydl_opts = {
            'quiet': True,
            'noprogress': True,
            'format': fmt or 'best',
            'color': 'never',
        }
        use_cookies = self.settings.value('use_cookies', False, type=bool)
        if use_cookies:
            source_type = self.settings.value('cookie_source_type', 'file')
            if source_type == 'file':
                cookie_file = self.settings.value('cookies_path', '')
                if cookie_file and os.path.exists(cookie_file):
                    ydl_opts['cookiefile'] = cookie_file
            else:
                # ИЗОЛЯЦИЯ: Живые куки браузера запрашиваются строго для YouTube.
                # Для AnimeGO, Kodik, Rutube, TikTok, Lampa и прямых m3u8/mp4 потоков куки браузера не трогаются.
                is_yt = ('youtube.com' in self.task.url.lower() or 'youtu.be' in self.task.url.lower())
                if is_yt:
                    browser = self.settings.value('cookie_browser', self.settings.value('cookie_source', 'none'))
                    if browser and browser != 'none':
                        try:
                            from .browser_cookies import get_best_browser_cookiefile
                            live_file, count, b_name = get_best_browser_cookiefile(browser)
                            if live_file and count > 0:
                                ydl_opts['cookiefile'] = live_file
                        except Exception as e:
                            logger.warning(f"Ошибка загрузки куки: {e}")

        try:
            logger.info("[TWITCH] Получаем прямую ссылку на поток (БЕЗ скачивания)...")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.task.url, download=False)
            except Exception as e:
                err_str = str(e).lower()
                if ('cookie' in err_str or 'dpapi' in err_str) and ('cookiesfrombrowser' in ydl_opts or 'cookiefile' in ydl_opts):
                    logger.warning(f"[TWITCH] Сбой из-за куки ({e}), повторяем без куки...")
                    ydl_opts.pop('cookiesfrombrowser', None)
                    ydl_opts.pop('cookiefile', None)
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(self.task.url, download=False)
                else:
                    raise
            stream_url = info.get('url')
            title = info.get('title', 'twitch_stream')

            if hasattr(self.task, 'custom_title') and self.task.custom_title:
                title = self.task.custom_title

            if not stream_url:
                raise Exception("Не удалось получить ссылку на поток")

            if not getattr(self.task, 'custom_title', None):
                self.task.title = title
            filename_tpl = str(self.settings.value('filename_template', '{title} [{quality}]') or '{title} [{quality}]')
            q_badge = getattr(self.task, 'quality_badge', '') or getattr(self.task, 'custom_quality', '') or ''
            base_out = StreamResolverHelper.resolve_output_template(
                save_path=save_path,
                template=filename_tpl,
                task=self.task,
                quality_tag=q_badge.replace(' ▾', '').strip(),
                is_ytdlp=False,
                create_dirs=True,
            )
            final_mp4 = f"{base_out}.mp4"
            temp_ts = f"{base_out}.ts"

            logger.info(f"[TWITCH] Прямая запись через FFmpeg в: {temp_ts}")

            cmd = [
                self.ffmpeg_path,
                '-y',
                '-i', stream_url,
                '-c', 'copy',
                temp_ts
            ]

            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)

            self._monitor_running = True
            threading.Thread(target=self._monitor_progress_twitch, args=(temp_ts,), daemon=True).start()

            while process.poll() is None:
                if self._cancel_requested or self.task.is_stop_requested():
                    logger.info("[TWITCH] Команда СТОП! Завершаем процесс FFmpeg...")
                    process.kill()
                    process.wait()
                    break
                time.sleep(1)

            self._monitor_running = False

            if getattr(self.task, 'is_removed', False):
                logger.info("[TWITCH] Задача удалена из списка.")
                if os.path.exists(temp_ts):
                    try:
                        os.remove(temp_ts)
                    except OSError:
                        pass
                self.task.set_status(self.task.Status.STOPPED)
                return

            if os.path.exists(temp_ts) and os.path.getsize(temp_ts) > 1024:
                self.task.update_progress(98, "Формирование MP4 файла...")
                logger.info("[TWITCH] Быстрая конвертация TS -> MP4...")

                remux_cmd = [
                    self.ffmpeg_path, '-y',
                    '-err_detect', 'ignore_err',
                    '-i', temp_ts,
                    '-c', 'copy',
                    final_mp4
                ]
                subprocess.run(remux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)

                if os.path.exists(final_mp4):
                    try:
                        os.remove(temp_ts)
                    except OSError:
                        pass
                    logger.info("[TWITCH] Успешно: Стрим сохранен.")
                    self.task.update_progress(100, "Скачано")
                    self.task.set_completed(final_mp4)
                else:
                    self.task.set_status(self.task.Status.ERROR)
            else:
                logger.warning("[TWITCH] Временный файл пуст или не создан.")
                self.task.set_status(self.task.Status.STOPPED)

        except Exception as e:
            logger.error(f"[TWITCH] Ошибка: {e}")
            self._monitor_running = False
            friendly_err = StreamResolverHelper.format_user_friendly_error(str(e), self.translator)
            self.task.set_error(friendly_err)