import logging
import re
from PyQt6.QtCore import QObject, pyqtSignal
from .threads import InfoWorker, DownloadWorker, ThumbnailWorker
from .download_task import DownloadTask

logger = logging.getLogger(__name__)


class DownloadManager(QObject):
    task_added = pyqtSignal(DownloadTask)
    download_started = pyqtSignal()
    all_downloads_finished = pyqtSignal()
    status_updated = pyqtSignal(str)
    summary_updated = pyqtSignal(str)
    active_threads_changed = pyqtSignal(int, int)

    def __init__(self, settings, ffmpeg_path, thread_pool, translator):
        super().__init__()
        self.settings = settings
        self.ffmpeg_path = ffmpeg_path
        self.thread_pool = thread_pool
        self.translator = translator
        self.tasks = []
        self.active_downloads = 0
        self.is_downloading_active = False
        self._workers = {}
        self.max_thumbnail_workers = 5  # Increased for better parallelism
        self.active_thumbnail_workers = 0
        self.thumbnail_queue = []

    def _update_summary(self):
        total = len(self.tasks)
        done = len([t for t in self.tasks if t.status == DownloadTask.Status.COMPLETED])
        errs = len([t for t in self.tasks if t.status == DownloadTask.Status.ERROR])
        self.summary_updated.emit(f"{done}/{total} ✓ • {errs} ⚠")
        self.active_threads_changed.emit(self.active_downloads, int(self.settings.value('parallel_downloads', 2)))

    def _normalize_url(self, url: str) -> str:
        u = url.strip()

        m = re.search(r"https?://(?:www\.)?kick\.com/[^/]+/videos/([0-9a-fA-F-]{6,})", u)
        if m:
            return f"https://kick.com/video/{m.group(1)}"

        rezka_match = re.search(r"https?://(?:www\.)?(?:hdrezka|rezka)\.[a-z]+/(.*)", u)
        if rezka_match:
            return f"https://hdrezka.ag/{rezka_match.group(1)}"

        return u

    def add_urls(self, urls):
        for url in urls:
            url = self._normalize_url(url)

            # --- СКАНЕР KINOPUB ---
            if "kinopub" in url or "kino.pub" in url:
                self.status_updated.emit("Сканирую сайт...")
                direct_url = self._parse_kinopub(url)

                if direct_url:
                    url = direct_url  # Ссылка найдена, заменяем на видео!
                else:
                    task = DownloadTask(url)
                    task.set_error("Видео не найдено в коде страницы.")
                    self.tasks.append(task)
                    self.task_added.emit(task)
                    continue
            # ----------------------

            task = DownloadTask(url)
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
        task.update_info(info)
        self._update_summary()

    def on_info_error(self, task, error):
        task.set_error(self.translator.translate('error_getting_info'))
        logger.error(f"Error fetching info for {task.url}: {error}")
        self._update_summary()

    def start_all(self):
        if self.is_downloading_active:
            return

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

    def start_task(self, task):
        max_concurrent = int(self.settings.value('parallel_downloads', 2))
        if self.active_downloads >= max_concurrent:
            return

        self.active_downloads += 1
        task.set_status(DownloadTask.Status.DOWNLOADING)

        worker = DownloadWorker(
            task,
            self.settings,
            self.ffmpeg_path,
            self.translator
        )
        self._workers[task] = worker
        worker.signals.finished.connect(lambda t=task: self.on_task_finished(t))
        worker.signals.error.connect(lambda error, t=task: self.on_task_error(t, error))

        self.thread_pool.start(worker)
        self._update_summary()

    def on_task_finished(self, task):
        if self.active_downloads > 0:
            self.active_downloads -= 1
        if task in self._workers:
            self._workers.pop(task, None)

        pending_tasks = [t for t in self.tasks if t.status == DownloadTask.Status.PENDING]
        if pending_tasks:
            self.start_task(pending_tasks[0])
        elif self.active_downloads == 0:
            self.is_downloading_active = False
            self.all_downloads_finished.emit()
        self._update_summary()

    def on_task_error(self, task, error_msg):
        task.set_error(error_msg)
        self.on_task_finished(task)

    def stop_all(self):
        if not self.is_downloading_active and self.active_downloads == 0:
            return

        for task in self.tasks:
            if task.status in (DownloadTask.Status.FETCHING_INFO, DownloadTask.Status.DOWNLOADING,
                               DownloadTask.Status.PENDING, DownloadTask.Status.PROCESSING):
                task.request_stop()
                worker = self._workers.get(task)
                if worker:
                    worker.cancel()

        self.status_updated.emit(self.translator.translate('stopping_downloads'))
        self.is_downloading_active = False
        self._update_summary()

    def remove_task(self, task):
        if task in self.tasks:
            task.request_stop()
            worker = self._workers.get(task)
            if worker:
                worker.cancel()
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

    def _parse_kinopub(self, url: str) -> str:
        import requests
        import re

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        try:
            req = requests.get(url, headers=headers, timeout=15)
            clean_text = req.text.replace('\\/', '/').replace('\\"', '"')

            quality_setting = self.settings.value('quality_kinopub', '1080')
            target_res = 1080
            if '360' in quality_setting:
                target_res = 360
            elif '480' in quality_setting:
                target_res = 480
            elif '720' in quality_setting:
                target_res = 720
            elif '1080' in quality_setting:
                target_res = 1080
            elif '1440' in quality_setting:
                target_res = 1440
            elif '2160' in quality_setting:
                target_res = 2160

            playerjs_links = re.findall(r'\[(\d+)p?\](https?://[^\s\'"<>\[\],]+\.(?:mp4|m3u8)[^\s\'"<>\[\],]*)',
                                        clean_text)
            json_links = re.findall(
                r'["\'](?:quality|label)["\']\s*:\s*["\'](\d+)p?["\'].*?["\'](?:url|file)["\']\s*:\s*["\'](https?://[^\s"<>]+)["\']',
                clean_text)

            all_tagged = playerjs_links + json_links

            if all_tagged:
                valid_links = [(int(res), link) for res, link in all_tagged if int(res) <= target_res]
                if valid_links:
                    valid_links.sort(key=lambda x: x[0], reverse=True)
                    logger.info(f"KinoPub: По тегам найдено точное качество {valid_links[0][0]}p")
                    return valid_links[0][1]

            streams = re.findall(r'(https?://[^\s\'"<>\[\],]+\.(?:m3u8|mp4)[^\s\'"<>\[\],]*)', clean_text)
            if streams:
                unique_streams = list(set(streams))

                def get_res_from_url(link):
                    m = re.search(r'(2160|1440|1080|720|480|360)', link)
                    return int(m.group(1)) if m else 0

                scored = [(get_res_from_url(s), s) for s in unique_streams]
                filtered = [x for x in scored if x[0] <= target_res]

                if filtered:
                    filtered.sort(key=lambda x: x[0], reverse=True)
                    if filtered[0][0] == 0:
                        manifests = [x[1] for x in filtered if 'manifest' in x[1] or 'master' in x[1]]
                        if manifests:
                            return manifests[0]
                    return filtered[0][1]

                return unique_streams[0]

        except Exception as e:
            logger.error(f"Ошибка сканера: {e}")

        return None