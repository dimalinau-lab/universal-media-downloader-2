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
            # Используем самые надежные флаги для восстановления стрима
            cmd = [
                self.ffmpeg_path, '-y', '-err_detect', 'ignore_err',
                '-fflags', '+genpts', '-i', self.part_file,
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
                'extract_flat': 'in_playlist', # Обязательно 'in_playlist' для быстрого сбора
                'skip_download': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'noplaylist': False, # <--- ГЛАВНЫЙ ФИКС: Заставляем видеть плейлист, а не одиночное видео
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

            if total > 0:
                self.task.set_file_size(total)
                percent = int((downloaded / total) * 90)
                self.task.update_progress(percent, f"Скачивание: {percent}% | {speed}")
            else:
                mb = downloaded / (1024 * 1024)
                self.task.update_progress(0, f"Скачивание: {mb:.1f} MB | {speed}")

        elif d.get('status') == 'finished':
            print(f"[ОТЛАДКА] [VOD] Поток скачан: {d.get('filename')}. Ждем склейку...")

    def simple_pp_hook(self, d):
        status = d.get('status')
        pp = d.get('postprocessor')
        print(f"[ОТЛАДКА] [VOD POSTPROCESSOR] {pp} -> {status}")

        if status == 'started':
            self.task.update_progress(95, "Склейка видео и звука...")
        elif status == 'finished':
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

                    self.task.update_progress(0, f"🔴 Запись эфира: {size_str} | {speed_str}")
                else:
                    self.task.update_progress(0, "🔴 Подключение к потоку...")
            except:
                pass
            time.sleep(1)

    def _default_save_path(self):
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
            self.signals.error.emit(str(e))
        finally:
            print(f"[ОТЛАДКА] --- ПОТОК ЗАВЕРШЕН: {self.task.url} ---\n")
            self._monitor_running = False
            self.signals.finished.emit()

    def _run_standard_vod(self, save_path):
        self.task.is_stream_mode = False
        print(f"[ОТЛАДКА] [VOD] Папка сохранения: {save_path}")
        self._start_time = time.time()  # <-- ФИКС 1: Фиксируем время старта задачи

        ydl_opts = {
            'outtmpl': os.path.join(save_path, '%(title)s [%(id)s].%(ext)s'),
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
            'ffmpeg_location': self.ffmpeg_path,
            'progress_hooks': [self.simple_progress_hook],
            'postprocessor_hooks': [self.simple_pp_hook],
            'quiet': True,
            'noprogress': True,
            'noplaylist': True,
            'ignoreerrors': True,
            # <-- ФИКС 2: Жестко игнорируем любые ошибки (например 429 субтитров), чтобы качать видео дальше!
            'postprocessors': []
        }

        # === 1. COOKIES ===
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

        # === 2. SPONSORBLOCK ===
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

        # === 3. СУБТИТРЫ ===
        if self.settings.value('subtitles_enabled', False, type=bool):
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            ydl_opts['subtitleslangs'] = ['ru', 'en']  # ФИКС 3: Убрал 'uk', так как он чаще всего крашит ютуб
            ydl_opts['sleep_subtitles'] = 2

            ydl_opts['postprocessors'].append({
                'key': 'FFmpegEmbedSubtitle',
                'when': 'post_process',
            })

        if not ydl_opts['postprocessors']:
            del ydl_opts['postprocessors']

        # === 4. ЗАПУСК СКАЧИВАНИЯ ===
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("[ОТЛАДКА] [VOD] yt-dlp: Начинаем скачивание...")
            if self.task.is_stop_requested() or self._cancel_requested:
                raise yt_dlp.utils.DownloadCancelled("Stopped")
            ydl.download([self.task.url])
            print("[ОТЛАДКА] [VOD] yt-dlp: Завершено.")

        # === 5. НАДЕЖНЫЙ ПОИСК ГОТОВОГО ФАЙЛА (УМНЫЙ) ===
        time.sleep(1.5)

        video_id = getattr(self.task, 'video_id', None)
        final_file = None
        valid_exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4a', '.mp3')

        # ПОИСК №1: Ищем файл, в названии которого есть уникальный ID именно этого видео
        if video_id:
            for f in os.listdir(save_path):
                if f"[{video_id}]" in f and f.endswith(valid_exts):
                    final_file = os.path.join(save_path, f)
                    break

        # ПОИСК №2: Если ID нет, ищем самый свежий файл, НО проверяем, чтобы он был создан ПОСЛЕ запуска этой задачи
        if not final_file:
            list_of_files = [os.path.join(save_path, f) for f in os.listdir(save_path)
                             if f.endswith(valid_exts) and not f.endswith('.part')]
            if list_of_files:
                latest_file = max(list_of_files, key=os.path.getmtime)
                # Если файл старше, чем старт задачи, значит скачивание не удалось, и это просто старый файл!
                if os.path.getmtime(latest_file) >= (self._start_time - 10):
                    final_file = latest_file

        # ПРОВЕРКА УСПЕХА
        if final_file and os.path.exists(final_file) and os.path.getsize(final_file) > 1024:
            print(f"[ОТЛАДКА] [VOD] Найден финальный файл: {final_file}")
            self.task.update_progress(100, "Скачано ✓")
            self.task.set_completed(final_file)
        else:
            # Если дошли сюда, значит видео физически не скачалось (ошибка Ютуба)
            raise Exception("Сбой скачивания. Файл не найден (возможно, блокировка 429).")

    def _run_twitch_stream(self, save_path):
        import re
        self.task.is_stream_mode = True
        self._start_time = time.time()

        ydl_opts = {
            'quiet': True,
            'noprogress': True,
            'format': 'best',
        }

        # === ПЕРЕДАЕМ COOKIES ДЛЯ ОБХОДА РЕКЛАМЫ ===
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
        # ===========================================

        try:
            print("[ОТЛАДКА] [TWITCH] Получаем прямую ссылку на поток (БЕЗ скачивания)...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.task.url, download=False)
                stream_url = info.get('url')
                title = info.get('title', 'twitch_stream')
                video_id = info.get('id', 'id')

            if not stream_url:
                raise Exception("Не удалось получить ссылку на поток")

            # Дальше идет старый код без изменений...
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            final_mp4 = os.path.join(save_path, f"{safe_title} [{video_id}].mp4")
            temp_ts = os.path.join(save_path, f"{safe_title} [{video_id}].ts")

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
                    self.task.update_progress(100, "Скачано ✓")
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