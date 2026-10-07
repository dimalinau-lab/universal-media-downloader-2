import sys
import os
import traceback
import logging
import glob
import subprocess
import time
import hashlib
import yt_dlp
import threading
import re
from PyQt6.QtCore import QRunnable, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QImage
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


class StreamAssembler(QRunnable):
    def __init__(self, part_file, out_path, ffmpeg_path, task):
        super().__init__()
        self.part_file = part_file
        self.out_path = out_path
        self.ffmpeg_path = ffmpeg_path
        self.task = task
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.task.update_progress(95, "Склейка стрима начата...")
            cmd = [
                self.ffmpeg_path, '-y', '-err_detect', 'ignore_err',
                '-fflags', '+genpts', '-threads', '0', '-i', self.part_file,
                '-c', 'copy', self.out_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(self.out_path):
                self.task.set_completed(self.out_path)
        except Exception as e:
            logger.error(f"Ошибка в отдельном сборщике: {e}")
            self.task.set_status(self.task.Status.ERROR)
        finally:
            self.signals.finished.emit()


class WorkerSignals(QObject):
    info_fetched = pyqtSignal(dict)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    thumbnail_loaded = pyqtSignal(QImage)


class InfoWorker(QRunnable):
    def __init__(self, url, settings):
        super().__init__()
        self.url = url
        self.settings = settings
        self.signals = WorkerSignals()

    def run(self):
        try:
            info_referer = 'https://vi3000.top/'
            if any(d in self.url for d in ('solodcdn', 'kodik')):
                info_referer = 'https://kodikplayer.com/'
            elif any(d in self.url for d in ('aniboom', 'ya-ligh', 'boom-img')):
                info_referer = 'https://aniboom.one/'
            elif any(d in self.url for d in ('kinopub', 'rezka', 'voidboost')):
                info_referer = 'https://kinopub.me/'

            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'enable_js': True,
                'remote_components': {'ejs:github': True},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': info_referer,
                    'Origin': info_referer.rstrip('/')
                }
            }
            use_cookies = self.settings.value('use_cookies', False, type=bool)
            if use_cookies:
                source_type = self.settings.value('cookie_source_type', 'file')
                if source_type == 'file':
                    cookie_file = self.settings.value('cookies_path', '')
                    if cookie_file and os.path.exists(cookie_file):
                        ydl_opts['cookiefile'] = cookie_file
                else:
                    browser = self.settings.value('cookie_browser', self.settings.value('cookie_source', 'none'))
                    if browser and browser != 'none':
                        try:
                            ydl_opts['cookiesfrombrowser'] = (browser,)
                        except Exception as e:
                            logger.warning(f"Browser {browser} not available for cookies: {e}")

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=False)
                    if not info:
                        raise Exception("yt-dlp не смог извлечь информацию о видео (контент недоступен или неподдерживаемый URL)")
                    self.signals.info_fetched.emit(info)
            except Exception as e:
                err_str = str(e).lower()
                if ('cookie' in err_str or 'dpapi' in err_str) and ('cookiesfrombrowser' in ydl_opts or 'cookiefile' in ydl_opts):
                    logger.warning(f"Cookie extraction failed ({e}), retrying without cookies...")
                    ydl_opts.pop('cookiesfrombrowser', None)
                    ydl_opts.pop('cookiefile', None)
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(self.url, download=False)
                        if not info:
                            raise Exception("yt-dlp не смог извлечь информацию о видео (контент недоступен или неподдерживаемый URL)")
                        self.signals.info_fetched.emit(info)
                else:
                    raise
        except Exception as e:
            logger.error(f"InfoWorker error for {self.url}: {e}")
            self.signals.error.emit(str(e))


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
        print(f"[ОТЛАДКА] Пользователь нажал ОТМЕНУ для {self.task.url}")
        self._cancel_requested = True
        self._monitor_running = False
        self.task.request_stop()

    def simple_progress_hook(self, d):
        if self._cancel_requested or self.task.is_stop_requested():
            raise yt_dlp.utils.DownloadCancelled("Остановлено юзером")

        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('_speed_str', 'N/A').strip()
            eta = d.get('_eta_str')
            eta_part = f" • ост. {eta}" if eta else ""

            frag_index = d.get('fragment_index')
            frag_count = d.get('fragment_count')
            frag_info = f" [{frag_index}/{frag_count}]" if frag_index and frag_count else ""

            if total > 0:
                self.task.set_file_size(total)
                percent = int((downloaded / total) * 90)
                self.task.update_progress(percent, f"Скачивание: {percent}%{frag_info} • {speed}{eta_part}")
            elif frag_index and frag_count:
                percent = int((frag_index / frag_count) * 90)
                self.task.update_progress(percent, f"Скачивание: {percent}% (фрагмент {frag_index}/{frag_count}) • {speed}{eta_part}")
            else:
                mb = downloaded / (1024 * 1024)
                self.task.update_progress(0, f"Скачивание: {mb:.1f} MB • {speed}{eta_part}")

        elif d.get('status') == 'finished':
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
            print(f"[ОТЛАДКА] [VOD] Поток скачан: {fn}. Ждем склейку...")

    def simple_pp_hook(self, d):
        status = d.get('status')
        pp = d.get('postprocessor')
        print(f"[ОТЛАДКА] [VOD POSTPROCESSOR] {pp} -> {status}")

        if status == 'started':
            self.task.update_progress(95, "Склейка видео и звука...")
        elif status == 'finished':
            info_dict = d.get('info_dict', {})
            pp_file = info_dict.get('filepath') or info_dict.get('_filename')
            if pp_file:
                self._last_downloaded_filename = pp_file
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
            except:
                pass
            time.sleep(1)

    def _default_save_path(self):
        if getattr(sys, 'frozen', False):
            root = os.path.dirname(sys.executable)
        else:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        dl_dir = os.path.join(root, 'downloads')
        os.makedirs(dl_dir, exist_ok=True)
        return dl_dir

    def run(self):
        print(f"\n[ОТЛАДКА] --- СТАРТ ЗАДАЧИ: {self.task.url} ---")
        try:
            save_path = self.settings.value('save_path', '')
            if not save_path or not os.path.isdir(save_path):
                save_path = self._default_save_path()
            self.task.save_path = save_path

            is_twitch = 'twitch.tv' in self.task.url.lower()

            if is_twitch:
                print("[ОТЛАДКА] Режим: СТРИМ TWITCH")
                self._run_twitch_stream(save_path)
            else:
                print("[ОТЛАДКА] Режим: ОБЫЧНОЕ ВИДЕО (VOD)")
                self._run_standard_vod(save_path)

        except yt_dlp.utils.DownloadCancelled:
            print("[ОТЛАДКА] Загрузка отменена юзером/скриптом.")
            self.task.set_status(self.task.Status.STOPPED)
        except Exception as e:
            import traceback
            print(f"[ОТЛАДКА] КРИТИЧЕСКАЯ ОШИБКА В RUN: {traceback.format_exc()}")
            self.signals.error.emit(f"Ошибка загрузчика: {str(e)}")
        finally:
            print(f"[ОТЛАДКА] --- ПОТОК ЗАВЕРШЕН: {self.task.url} ---\n")
            self._monitor_running = False
            self.signals.finished.emit()

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
        elif task_override == '1080p':
            return 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best', 'mp4', []
        elif task_override == '720p':
            return 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best', 'mp4', []
        elif task_override == 'best':
            return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best', 'mp4', []

        fmt = self.settings.value(platform_key, '') if platform_key else ''
        pps = []
        merge_fmt = 'mp4'

        codec_pref = self.settings.value('video_codec_preference', 'auto')

        if not fmt or fmt == 'best':
            if codec_pref == 'h264':
                fmt = 'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[vcodec^=avc1]+bestaudio/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'
            elif codec_pref == 'av1_vp9':
                fmt = 'bestvideo[vcodec^=av01|vcodec^=vp9]+bestaudio/bestvideo+bestaudio/best'
            else:
                fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
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
            fmt = 'bestvideo/best'
        elif fmt == 'worst':
            fmt = 'worstvideo+worstaudio/worst'
        elif '[height<=' in fmt:
            if codec_pref == 'h264' and '[vcodec' not in fmt:
                h_match = re.search(r'height<=(\d+)', fmt)
                if h_match:
                    h = h_match.group(1)
                    fmt = f'bestvideo[height<={h}][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best'
            elif codec_pref == 'av1_vp9' and '[vcodec' not in fmt:
                h_match = re.search(r'height<=(\d+)', fmt)
                if h_match:
                    h = h_match.group(1)
                    fmt = f'bestvideo[height<={h}][vcodec^=av01|vcodec^=vp9]+bestaudio/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best'

        return fmt, merge_fmt, pps

    def _run_standard_vod(self, save_path):
        self.task.is_stream_mode = False
        print(f"[ОТЛАДКА] [VOD] Папка сохранения: {save_path}")
        self._start_time = time.time()

        custom_t = getattr(self.task, 'custom_title', None)
        task_t = getattr(self.task, 'title', None)
        base_title = (custom_t.strip() if custom_t else "") or (task_t.strip() if task_t and task_t not in ("...", "") else "")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", base_title).strip() if base_title else ""
        safe_title = safe_title[:150]

        time_range = getattr(self.task, 'time_range', None)
        range_suffix = ""
        if time_range:
            s_sec, e_sec = time_range
            s_str = f"{int(s_sec//3600):02d}-{int((s_sec%3600)//60):02d}-{int(s_sec%60):02d}" if s_sec >= 3600 else f"{int(s_sec//60):02d}-{int(s_sec%60):02d}"
            e_str = f"{int(e_sec//3600):02d}-{int((e_sec%3600)//60):02d}-{int(e_sec%60):02d}" if e_sec >= 3600 else f"{int(e_sec//60):02d}-{int(e_sec%60):02d}"
            range_suffix = f"_[{s_str}_{e_str}]"

        if safe_title:
            out_filename = f"{safe_title}{range_suffix}.%(ext)s"
        else:
            out_filename = f"%(title)s{range_suffix}.%(ext)s"

        out_template = os.path.join(save_path, out_filename)

        referer_url = getattr(self.task, 'referer', None)
        if not referer_url:
            if 'nip.io' in self.task.url or 'alloha' in self.task.url:
                referer_url = 'https://vi3000.top/'
            elif 'voidboost' in self.task.url:
                referer_url = 'https://kinopub.me/'
            elif any(d in self.task.url for d in ('solodcdn', 'kodik')):
                referer_url = 'https://kodikplayer.com/'
            elif any(d in self.task.url for d in ('aniboom', 'ya-ligh', 'boom-img')):
                referer_url = 'https://aniboom.one/'
            else:
                referer_url = 'https://kinopub.me/'

        fmt, merge_fmt, extra_pps = self._resolve_format_and_pps()

        ydl_opts = {
            'outtmpl': out_template,
            'format': fmt,
            'ffmpeg_location': self.ffmpeg_path,
            'progress_hooks': [self.simple_progress_hook],
            'postprocessor_hooks': [self.simple_pp_hook],
            'quiet': True,
            'noprogress': True,
            'noplaylist': True,
            'ignoreerrors': False,
            'nocheckcertificate': True,

            # --- ЗАЩИТА ОТ РАЗРЫВА СОЕДИНЕНИЯ С СЕРВЕРОМ ---
            'retries': 30,  # Количество попыток переподключения
            'fragment_retries': 30,  # Количество попыток для отдельных фрагментов
            'file_access_retries': 10,  # Попытки доступа к файлу
            'continuedl': True,  # Обязательно докачивать файл при обрыве
            # -----------------------------------------------

            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Referer': referer_url,
                'Origin': referer_url.strip('/')
            },
            'postprocessors': list(extra_pps)
        }
        if merge_fmt:
            ydl_opts['merge_output_format'] = merge_fmt

        speed_limit = self.settings.value('speed_limit', 0, type=int)
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
                browser = self.settings.value('cookie_browser', self.settings.value('cookie_source', 'none'))
                if browser and browser != 'none':
                    try:
                        ydl_opts['cookiesfrombrowser'] = (browser,)
                    except Exception as e:
                        print(f"[ОТЛАДКА] Ошибка загрузки куки: {e}")

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
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            ydl_opts['subtitleslangs'] = ['ru', 'en']
            ydl_opts['sleep_subtitles'] = 2

            ydl_opts['postprocessors'].append({
                'key': 'FFmpegEmbedSubtitle',
                'when': 'post_process',
            })

        if not ydl_opts['postprocessors']:
            del ydl_opts['postprocessors']

        if time_range:
            start_s, end_s = time_range
            ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func([], [(float(start_s), float(end_s))])
            ydl_opts['force_keyframes_at_cuts'] = True

        if fmt == 'bestaudio/best' and self.settings.value('embed_thumbnail', True, type=bool):
            ydl_opts['writethumbnail'] = True

        # === ЗАПУСК СКАЧИВАНИЯ ===
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                print("[ОТЛАДКА] [VOD] yt-dlp: Начинаем скачивание...")
                if self.task.is_stop_requested() or self._cancel_requested:
                    raise yt_dlp.utils.DownloadCancelled("Stopped")
                ydl.download([self.task.url])
                print("[ОТЛАДКА] [VOD] yt-dlp: Завершено.")
        except yt_dlp.utils.DownloadCancelled:
            raise
        except Exception as e:
            err_str = str(e).lower()
            if ('cookie' in err_str or 'dpapi' in err_str) and ('cookiesfrombrowser' in ydl_opts or 'cookiefile' in ydl_opts):
                print(f"[ОТЛАДКА] Сбой из-за куки ({e}), повторяем скачивание без куки...")
                ydl_opts.pop('cookiesfrombrowser', None)
                ydl_opts.pop('cookiefile', None)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    if self.task.is_stop_requested() or self._cancel_requested:
                        raise yt_dlp.utils.DownloadCancelled("Stopped")
                    ydl.download([self.task.url])
                    print("[ОТЛАДКА] [VOD] yt-dlp (без куки): Завершено.")
            elif 'subtitle' in err_str and ('writesubtitles' in ydl_opts or 'writeautomaticsub' in ydl_opts):
                print(f"[ОТЛАДКА] Сбой скачивания субтитров ({e}), повторяем скачивание видео без субтитров...")
                ydl_opts.pop('writesubtitles', None)
                ydl_opts.pop('writeautomaticsub', None)
                ydl_opts.pop('subtitleslangs', None)
                if 'postprocessors' in ydl_opts:
                    ydl_opts['postprocessors'] = [p for p in ydl_opts['postprocessors'] if p.get('key') != 'FFmpegEmbedSubtitle']
                    if not ydl_opts['postprocessors']:
                        del ydl_opts['postprocessors']
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    if self.task.is_stop_requested() or self._cancel_requested:
                        raise yt_dlp.utils.DownloadCancelled("Stopped")
                    ydl.download([self.task.url])
                    print("[ОТЛАДКА] [VOD] yt-dlp (без субтитров): Завершено.")
            else:
                raise
        time.sleep(1.5)

        final_file = None
        valid_exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4a', '.mp3')

        # 1. Приоритет: точный файл, перехваченный через хуки yt-dlp
        if getattr(self, '_last_downloaded_filename', None):
            candidate = self._last_downloaded_filename
            if os.path.exists(candidate) and not candidate.endswith('.part') and os.path.getsize(candidate) > 1024:
                final_file = candidate
            else:
                base_cand, _ = os.path.splitext(candidate)
                for ext in valid_exts:
                    if os.path.exists(base_cand + ext) and os.path.getsize(base_cand + ext) > 1024:
                        final_file = base_cand + ext
                        break

        # 2. Поиск по целевому названию в папке сохранения
        if not final_file and safe_title:
            for f in os.listdir(save_path):
                if f.startswith(safe_title) and f.endswith(valid_exts) and not f.endswith('.part'):
                    final_file = os.path.join(save_path, f)
                    break

        # 3. Запасной план: поиск самого свежего подходящего файла
        if not final_file:
            list_of_files = [os.path.join(save_path, f) for f in os.listdir(save_path)
                             if f.endswith(valid_exts) and not f.endswith('.part')]
            if list_of_files:
                latest_file = max(list_of_files, key=os.path.getmtime)
                if os.path.getmtime(latest_file) >= (self._start_time - 10):
                    final_file = latest_file

        if final_file and os.path.exists(final_file) and os.path.getsize(final_file) > 1024:
            base_fname = os.path.splitext(os.path.basename(final_file))[0]
            if getattr(self.task, 'custom_title', None):
                self.task.title = self.task.custom_title
            elif not getattr(self.task, 'title', None) or self.task.title in ("...", ""):
                self.task.title = base_fname
            self.task.info_updated.emit()
            print(f"[ОТЛАДКА] [VOD] Найден финальный файл: {final_file}")
            self.task.update_progress(100, "Скачано")
            self.task.set_completed(final_file)
        else:
            raise Exception("Сбой скачивания: Файл пуст или yt-dlp не смог обработать поток.")

    def _run_twitch_stream(self, save_path):
        import re
        self.task.is_stream_mode = True
        self._start_time = time.time()

        ydl_opts = {
            'quiet': True,
            'noprogress': True,
            'format': 'best',
        }
        use_cookies = self.settings.value('use_cookies', False, type=bool)
        if use_cookies:
            source_type = self.settings.value('cookie_source_type', 'file')
            if source_type == 'file':
                cookie_file = self.settings.value('cookies_path', '')
                if cookie_file and os.path.exists(cookie_file):
                    ydl_opts['cookiefile'] = cookie_file
            else:
                browser = self.settings.value('cookie_browser', self.settings.value('cookie_source', 'none'))
                if browser and browser != 'none':
                    try:
                        ydl_opts['cookiesfrombrowser'] = (browser,)
                    except Exception as e:
                        print(f"[ОТЛАДКА] Ошибка загрузки куки: {e}")


        try:
            print("[ОТЛАДКА] [TWITCH] Получаем прямую ссылку на поток (БЕЗ скачивания)...")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.task.url, download=False)
            except Exception as e:
                err_str = str(e).lower()
                if ('cookie' in err_str or 'dpapi' in err_str) and ('cookiesfrombrowser' in ydl_opts or 'cookiefile' in ydl_opts):
                    print(f"[ОТЛАДКА] [TWITCH] Сбой из-за куки ({e}), повторяем без куки...")
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

            safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:150]
            final_mp4 = os.path.join(save_path, f"{safe_title}.mp4")
            temp_ts = os.path.join(save_path, f"{safe_title}.ts")

            print(f"[ОТЛАДКА] [TWITCH] Прямая запись через FFmpeg в: {temp_ts}")

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
                    print("[ОТЛАДКА] [TWITCH] Команда СТОП! Жестко убиваем FFmpeg...")
                    process.kill()
                    process.wait()
                    break
                time.sleep(1)

            self._monitor_running = False

            if getattr(self.task, 'is_removed', False):
                print("[ОТЛАДКА] [TWITCH] Задача удалена из списка.")
                if os.path.exists(temp_ts): os.remove(temp_ts)
                self.task.set_status(self.task.Status.STOPPED)
                return

            if os.path.exists(temp_ts) and os.path.getsize(temp_ts) > 1024:
                self.task.update_progress(98, "Формирование MP4 файла...")
                print("[ОТЛАДКА] [TWITCH] Быстрая конвертация TS -> MP4...")

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
                    except:
                        pass
                    print("[ОТЛАДКА] [TWITCH] УСПЕХ! Стрим сохранен.")
                    self.task.update_progress(100, "Скачано")
                    self.task.set_completed(final_mp4)
                else:
                    self.task.set_status(self.task.Status.ERROR)
            else:
                print("[ОТЛАДКА] [TWITCH] Временный файл пуст или не создан.")
                self.task.set_status(self.task.Status.STOPPED)

        except Exception as e:
            print(f"[ОТЛАДКА] [TWITCH] Ошибка: {e}")
            self._monitor_running = False
            self.task.set_status(self.task.Status.ERROR)