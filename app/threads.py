import os
import traceback
import logging
import glob
import subprocess
import time
import hashlib
import yt_dlp
import threading
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

    def _get_key(self, url):
        return hashlib.md5(url.encode()).hexdigest()

    def get(self, url):
        key = self._get_key(url)
        if key in self._cache:
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return None

    def set(self, url, pixmap):
        key = self._get_key(url)
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self._max_size:
            oldest = self._order.pop(0)
            del self._cache[oldest]
        self._cache[key] = pixmap
        self._order.append(key)

    def clear(self):
        self._cache.clear()
        self._order.clear()


thumbnail_cache = ThumbnailCache(max_size=100)


class WorkerSignals(QObject):
    info_fetched = pyqtSignal(dict)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    thumbnail_loaded = pyqtSignal(QPixmap)


class InfoWorker(QRunnable):
    def __init__(self, url, settings):
        super().__init__()
        self.url = url
        self.settings = settings
        self.signals = WorkerSignals()

    def run(self):
        try:
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'nocheckcertificate': True,
                'enable_js': True,
                'remote_components': {'ejs:github': True},
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
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                self.signals.info_fetched.emit(info)
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
                pixmap = QPixmap.fromImage(image)
                thumbnail_cache.set(self.url, pixmap)
                self.signals.thumbnail_loaded.emit(pixmap)
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
                'extract_flat': True,
                'skip_download': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
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
        self.is_stream_mode = False

        self._start_time = None
        self._monitor_running = False
        self._monitor_thread = None

    def cancel(self):
        self._cancel_requested = True
        self._monitor_running = False
        self.task.request_stop()

    def _monitor_progress(self):
        last_size = 0
        last_time = time.time()

        save_dir = self.task.save_path or self._default_save_path()
        marker = f"[{self.task.video_id}]" if self.task.video_id else ""

        while self._monitor_running and not self.task.is_stop_requested() and not self._cancel_requested:
            try:
                target_file = None
                if marker:
                    candidates = []
                    for f in os.listdir(save_dir):
                        if marker in f and not f.endswith('.fixed.mp4'):
                            fp = os.path.join(save_dir, f)
                            if os.path.isfile(fp):
                                candidates.append(fp)
                    if candidates:
                        target_file = max(candidates, key=os.path.getmtime)

                if target_file and os.path.exists(target_file):
                    size = os.path.getsize(target_file)

                    now = time.time()
                    time_diff = now - last_time
                    if time_diff > 0:
                        speed_bps = (size - last_size) / time_diff
                    else:
                        speed_bps = 0

                    last_size = size
                    last_time = now

                    if speed_bps < 0: speed_bps = 0
                    if speed_bps < 1024 * 1024:
                        speed_str = f"{speed_bps / 1024:.1f} KB/s"
                    else:
                        speed_str = f"{speed_bps / (1024 * 1024):.2f} MB/s"

                    elapsed = now - self._start_time
                    h = int(elapsed // 3600)
                    m = int((elapsed % 3600) // 60)
                    s = int(elapsed % 60)
                    time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

                    mb = size / (1024 * 1024)
                    size_str = f"{mb:.1f} MB" if mb < 1024 else f"{mb / 1024:.2f} GB"

                    progress_text = f"🔴 Запись: {time_str} | {size_str} | {speed_str}"
                    self.task.update_progress(0, progress_text)
                else:
                    self.task.update_progress(0, "🔴 Подключение к эфиру...")

            except Exception as e:
                pass

            time.sleep(1)

    def progress_hook(self, d):
        try:
            if getattr(self, 'is_stream_mode', False):
                return

            if self.task.is_stop_requested() or self._cancel_requested:
                raise yt_dlp.utils.DownloadCancelled("Download stopped by user.")

            fn = d.get('filename')
            tmp = d.get('tmpfilename')
            if tmp or fn:
                self.task.update_current_paths(tmpfilename=tmp, filename=fn)

            if d.get('status') == 'downloading':
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes') or 0

                speed_raw = d.get('_speed_str')
                speed = str(speed_raw).strip() if speed_raw is not None else 'N/A'

                if total_bytes and total_bytes > 0:
                    self.task.set_file_size(total_bytes)
                    raw_percent = (downloaded / total_bytes) * 100
                    percent = int(raw_percent * 0.9)

                    eta_raw = d.get('_eta_str')
                    eta = str(eta_raw).strip() if eta_raw is not None else 'N/A'

                    progress_text = f"{int(raw_percent)}% | {speed} | ETA: {eta}"
                    self.task.update_progress(percent, progress_text)
                else:
                    mb = downloaded / (1024 * 1024)
                    size_str = f"{mb:.1f} MB" if mb < 1024 else f"{mb / 1024:.2f} GB"
                    progress_text = f"Скачано: {size_str} | {speed}"
                    self.task.update_progress(0, progress_text)

            elif d.get('status') == 'finished':
                self.task.set_status(self.task.Status.PROCESSING)
                self.task.update_progress(90, "Обработка...")
                final_path = d.get('filename')
                if final_path:
                    self.task.update_current_paths(filename=final_path)

        except yt_dlp.utils.DownloadCancelled:
            raise
        except Exception as e:
            pass

    def postprocessor_hook(self, d):
        if self.task.is_stop_requested() or self._cancel_requested:
            raise yt_dlp.utils.DownloadCancelled("Download stopped by user during processing.")

        status = d.get('status')
        pp_name = d.get('postprocessor', '')

        if status == 'started':
            self.task.update_progress(92, f"Конвертация ({pp_name})...")

        elif status == 'finished':
            self.task.update_progress(98, "Сохранение...")
            info = d.get('info_dict', {})
            new_filepath = info.get('filepath') or info.get('_filename')
            if new_filepath:
                self._target_out_path = new_filepath
                self.task.update_current_paths(filename=new_filepath)

    def _default_save_path(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        dl_dir = os.path.join(root, 'downloads')
        os.makedirs(dl_dir, exist_ok=True)
        return dl_dir

    def _cleanup_incomplete(self, save_path):
        try:
            paths = set()
            if self.task.current_tmpfilename:
                paths.add(self.task.current_tmpfilename)
            if self.task.current_filename and os.path.exists(self.task.current_filename):
                paths.add(self.task.current_filename)
            if self.task.video_id:
                marker = f"[{self.task.video_id}]"
                for name in os.listdir(save_path):
                    if marker in name:
                        paths.add(os.path.join(save_path, name))
            for pattern in ("*.part", "*.ytdl", "*.temp", "*.aria2", "*.fragment", "*.frag", "*.downloading"):
                for p in glob.glob(os.path.join(save_path, pattern)):
                    if self.task.video_id and f"[{self.task.video_id}]" not in os.path.basename(p):
                        continue
                    paths.add(p)
            for p in list(paths):
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass

    def run(self):
        self._target_out_path = None
        self._monitor_running = False
        try:
            platform = self.task.platform.lower().replace(' ', '_').replace('(', '').replace(')', '')
            quality_key = f'quality_{platform}'
            chosen_format = self.settings.value(quality_key, 'bestvideo+bestaudio/best')

            save_path = self.settings.value('save_path', '')
            if not save_path or not os.path.isdir(save_path):
                save_path = self._default_save_path()
            self.task.save_path = save_path

            stream_choice = getattr(self.task, 'stream_mode_choice', None)

            is_actual_live = False
            if hasattr(self.task, 'info') and isinstance(self.task.info, dict):
                live_status = self.task.info.get('live_status')
                duration = self.task.info.get('duration')

                if live_status in ('is_live', 'is_upcoming') or self.task.info.get('is_live') is True:
                    is_actual_live = True
                elif duration in (0, None):
                    is_actual_live = True

            if not is_actual_live and ('twitch.tv' in self.task.url.lower()):
                is_actual_live = True

            self.is_stream_mode = False
            if stream_choice is not None:
                self.is_stream_mode = True
            elif is_actual_live:
                self.is_stream_mode = True

            if self.is_stream_mode and stream_choice is None:
                stream_choice = 'from_now'
                self.task.stream_mode_choice = stream_choice

            self.task.is_stream_mode = self.is_stream_mode

            ydl_opts = {
                'outtmpl': os.path.join(save_path, '%(title)s [%(id)s].%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'postprocessor_hooks': [self.postprocessor_hook],
                'quiet': True,
                'noprogress': True,
                'ignoreerrors': False,
                'overwrites': True,
                'ffmpeg_location': self.ffmpeg_path,
                'prefer_ffmpeg': False,
                'legacyserverconnect': True,
                'source_address': '0.0.0.0',
                'socket_timeout': 30,
                'retries': 15,
                'fragment_retries': 15,
                'skip_unavailable_fragments': True,
                'hls_prefer_native': True,
            }

            if self.is_stream_mode:
                if stream_choice == 'from_start':
                    ydl_opts['wait_for_video'] = (20, 60)
                    ydl_opts['live_from_start'] = True
                    ydl_opts['format'] = chosen_format
                    ydl_opts['merge_output_format'] = 'mp4'
                elif stream_choice == 'from_now':
                    ydl_opts['live_from_start'] = False
                    ydl_opts['format'] = 'best'

            is_audio_only = chosen_format in ['bestaudio/best', 'bestaudio'] or str(chosen_format).startswith(
                'bestaudio')
            video_only_mode = chosen_format == 'video_only_stripped'

            if not self.is_stream_mode:
                if is_audio_only:
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192'
                    }]
                elif video_only_mode:
                    ydl_opts['format'] = 'bestvideo[ext=mp4]/bestvideo/best'
                else:
                    ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
                    ydl_opts['merge_output_format'] = 'mp4'

            use_cookies = self.settings.value('use_cookies', False, type=bool)
            if use_cookies:
                source_type = self.settings.value('cookie_source_type', 'file')
                if source_type == 'file':
                    cookie_file = self.settings.value('cookies_path', '')
                    if cookie_file and os.path.exists(cookie_file):
                        ydl_opts['cookiefile'] = cookie_file
                else:
                    browser = self.settings.value('cookie_browser', 'none')
                    if browser != 'none':
                        ydl_opts['cookiesfrombrowser'] = (browser,)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.task.url, download=False)
                self._target_out_path = ydl.prepare_filename(info)

                if self.task.is_stop_requested() or self._cancel_requested:
                    raise yt_dlp.utils.DownloadCancelled("Download stopped before start.")

                if self.is_stream_mode:
                    self._start_time = time.time()
                    self._monitor_running = True
                    self._monitor_thread = threading.Thread(target=self._monitor_progress, daemon=True)
                    self._monitor_thread.start()

                    ydl.download([self.task.url])

                    self._monitor_running = False
                    if self.is_stream_mode:
                        raise yt_dlp.utils.DownloadCancelled("Stream closed.")
                    else:
                        self.task.set_completed(self._target_out_path)


        except yt_dlp.utils.DownloadCancelled:

            self._monitor_running = False

            is_deleted = getattr(self.task, 'is_removed', False)

            if getattr(self, 'is_stream_mode', False) and self._target_out_path and not is_deleted:

                self.task.set_status(self.task.Status.PROCESSING)

                self.task.update_progress(95, "Остановлена запись. Ожидание завершения потока...")

                # Ждем 3 секунды, чтобы процесс yt-dlp полностью отпустил файл

                time.sleep(3.0)

                recovered_path = None

                try:

                    save_dir = self.task.save_path or self._default_save_path()

                    marker = f"[{self.task.video_id}]" if self.task.video_id else ""

                    out_path = self._target_out_path

                    if not out_path.endswith('.mp4'):
                        out_path = os.path.splitext(out_path)[0] + '.mp4'

                    # Ищем файл с расширением .part

                    part_files = []

                    if marker:

                        for f in os.listdir(save_dir):

                            if marker in f and f.endswith('.part'):
                                fp = os.path.join(save_dir, f)

                                part_files.append(fp)

                    if part_files:

                        best_file = part_files[0]

                        # Сборка без FFmpeg-загрузчика, только конвертация (самый надежный путь)

                        cmd = [self.ffmpeg_path, '-y', '-err_detect', 'ignore_err', '-i', best_file, '-c', 'copy',
                               out_path]

                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40)

                        if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:

                            recovered_path = out_path

                        else:

                            # Если FFmpeg не смог, просто перемещаем файл

                            import shutil

                            shutil.move(best_file, out_path)

                            recovered_path = out_path


                except Exception as e:

                    logger.error(f"Ошибка склейки: {e}")

                if recovered_path and os.path.exists(recovered_path):
                    self.task.set_completed(recovered_path)

                    return

                    # Очистка если удалили задачу

            if is_deleted:
                path = self.task.save_path or self._default_save_path()

                self._cleanup_incomplete(path)

            self.task.set_status(self.task.Status.STOPPED)