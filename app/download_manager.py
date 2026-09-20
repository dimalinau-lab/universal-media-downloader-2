import os
import sys
import logging
import re
import time
import subprocess
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout, QApplication

from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from .threads import InfoWorker, DownloadWorker, ThumbnailWorker
from .download_task import DownloadTask

logger = logging.getLogger(__name__)


def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


# === ОКНО ВЫБОРА ===
class EpisodeSelectionDialog(QDialog):
    # Добавили параметр qualities
    def __init__(self, voiceovers, seasons, episodes, qualities, is_movie=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Параметры загрузки")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.download_all = False

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Выберите качество:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(qualities)
        if qualities:
            self.quality_combo.setCurrentText(qualities[0])  # Ставим лучшее по умолчанию
        layout.addWidget(self.quality_combo)

        layout.addWidget(QLabel("Выберите озвучку:"))
        self.voiceover_combo = QComboBox()
        self.voiceover_combo.addItems(voiceovers)
        layout.addWidget(self.voiceover_combo)

        self.season_combo = QComboBox()
        self.season_combo.addItems(seasons)

        self.episode_combo = QComboBox()
        self.episode_combo.addItems(episodes)

        if not is_movie:
            layout.addWidget(QLabel("Выберите сезон:"))
            layout.addWidget(self.season_combo)
            layout.addWidget(QLabel("Выберите серию:"))
            layout.addWidget(self.episode_combo)

        btn_layout = QHBoxLayout()

        self.ok_btn = QPushButton("Скачать серию")
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)

        if not is_movie:
            self.all_btn = QPushButton("Скачать ВЕСЬ сезон")
            self.all_btn.setStyleSheet("background-color: #0078D7; color: white;")
            self.all_btn.clicked.connect(self.accept_all)
            btn_layout.addWidget(self.all_btn)

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

    def accept_all(self):
        self.download_all = True
        self.accept()


# ==================================

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
        self.max_thumbnail_workers = 5
        self.active_thumbnail_workers = 0
        self.thumbnail_queue = []

    def _update_summary(self):
        total = len(self.tasks)
        done = len([t for t in self.tasks if t.status == DownloadTask.Status.COMPLETED])
        errs = len([t for t in self.tasks if t.status == DownloadTask.Status.ERROR])
        self.summary_updated.emit(f"{done}/{total} ✓ • {errs} ⚠")
        self.active_threads_changed.emit(self.active_downloads, int(self.settings.value('parallel_downloads', 2)))

    def _clean_stream_url(self, stream_url: str) -> str:
        if ":hls:seg-" in stream_url:
            stream_url = re.sub(r':hls:seg-[^/]+\.ts.*', '', stream_url)
        elif ".ts" in stream_url and "seg-" in stream_url:
            stream_url = re.sub(r':?seg-[^/]+\.ts.*', '', stream_url)
        stream_url = stream_url.replace(':hls:manifest.m3u8', '')
        return stream_url.strip('; "\'')

    def _normalize_url(self, url: str) -> str:
        u = url.strip()
        if ":hls:seg-" in u or (".ts" in u and "seg-" in u):
            return self._clean_stream_url(u)
        m = re.search(r"https?://(?:www\.)?kick\.com/[^/]+/videos/([0-9a-fA-F-]{6,})", u)
        if m: return f"https://kick.com/video/{m.group(1)}"
        rezka_match = re.search(r"https?://(?:www\.)?(?:hdrezka|rezka)\.[a-z]+/(.*)", u)
        if rezka_match: return f"https://hdrezka.ag/{rezka_match.group(1)}"
        return u

    def add_urls(self, urls):
        for url in urls:
            url = self._normalize_url(url)

            if "vi3000" in url or "cub" in url or "lampa" in url:
                self.status_updated.emit("Ожидаю включения плеера в браузере...")
                results = self._parse_lampa(url)

                if results:
                    for res in results:
                        task = DownloadTask(res['url'])
                        task.custom_title = res['title']
                        task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
                        self.tasks.append(task)
                        self.task_added.emit(task)
                        self.fetch_video_info(task)
                else:
                    task = DownloadTask(url)
                    task.set_error("Видео не включено или браузер закрыт.")
                    self.tasks.append(task)
                    self.task_added.emit(task)
                continue

            elif "kinopub" in url or "kino.pub" in url or "rezka" in url:
                self.status_updated.emit("Обход защиты сайта и поиск серий...")
                results = self._parse_kinopub(url)

                if results is None:
                    continue
                elif len(results) > 0:
                    for res in results:
                        task = DownloadTask(res['url'])
                        task.custom_title = res['title']
                        task.thumbnail_load_requested.connect(self.queue_thumbnail_load)
                        self.tasks.append(task)
                        self.task_added.emit(task)
                        self.fetch_video_info(task)
                else:
                    task = DownloadTask(url)
                    task.set_error("Видео не найдено.")
                    self.tasks.append(task)
                    self.task_added.emit(task)
                continue

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
        if hasattr(task, 'custom_title') and task.custom_title:
            info['title'] = task.custom_title
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

    def start_task(self, task):
        max_concurrent = int(self.settings.value('parallel_downloads', 2))
        if self.active_downloads >= max_concurrent: return
        self.active_downloads += 1
        task.set_status(DownloadTask.Status.DOWNLOADING)
        worker = DownloadWorker(task, self.settings, self.ffmpeg_path, self.translator)
        self._workers[task] = worker
        worker.signals.finished.connect(lambda t=task: self.on_task_finished(t))
        worker.signals.error.connect(lambda error, t=task: self.on_task_error(t, error))
        self.thread_pool.start(worker)
        self._update_summary()

    def on_task_finished(self, task):
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
        if not streams_raw:
            return None

        if target_res is None:
            quality_setting = self.settings.value('quality_kinopub', '1080')
            target_res = 1080
            for q in [360, 480, 720, 1080, 1440, 2160]:
                if str(q) in str(quality_setting): target_res = q

        links = re.findall(r'\[(\d+)p?[^\]]*\](https?://[^\s,\[\]]+)', streams_raw)
        if links:
            valid_links = []
            for res, link in links:
                clean_link = link.split(' or ')[0].strip()
                if int(res) <= target_res:
                    valid_links.append((int(res), clean_link))

            if valid_links:
                valid_links.sort(key=lambda x: x[0], reverse=True)
                return self._clean_stream_url(valid_links[0][1])

        urls = re.findall(r'(https?://[^\s,\[\]]+)', streams_raw)
        if urls:
            return self._clean_stream_url(urls[0].split(' or ')[0].strip())
        return None

    def _parse_lampa(self, url: str) -> list:
        driver = None
        try:
            options = Options()
            options.add_argument('--log-level=3')
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

            profile_dir = os.path.join(get_base_dir(), 'browser_profile')
            os.makedirs(profile_dir, exist_ok=True)
            options.add_argument(f"user-data-dir={profile_dir}")

            service = Service()
            service.creation_flags = subprocess.CREATE_NO_WINDOW

            try:
                driver = webdriver.Edge(service=service, options=options)
            except Exception as e:
                logger.warning(f"Профиль браузера заблокирован, запускаю без профиля: {e}")
                fallback_options = Options()
                fallback_options.add_argument('--log-level=3')
                driver = webdriver.Edge(service=service, options=fallback_options)

            driver.maximize_window()
            driver.get(url)

            stream_url = None
            custom_title = "Lampa Video"

            for _ in range(300):
                try:
                    if not driver.window_handles:
                        break

                    video_tags = driver.find_elements(By.CSS_SELECTOR, "video.player-video__video")
                    for tag in video_tags:
                        src = tag.get_attribute("src")
                        if src and src.startswith("http"):
                            stream_url = src
                            try:
                                title_el = driver.find_element(By.CSS_SELECTOR, ".player-info__name")
                                if title_el and title_el.text:
                                    custom_title = title_el.text
                            except:
                                pass
                            break

                    if stream_url:
                        break

                except Exception:
                    break

                time.sleep(1)
                QApplication.processEvents()

            try:
                driver.quit()
            except:
                pass

            if stream_url:
                safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title).strip()
                return [{'url': stream_url, 'title': safe_title}]

        except Exception as e:
            import traceback
            err = traceback.format_exc()
            logger.error(f"Ошибка Lampa сканера: {err}")
            try:
                if driver: driver.quit()
            except:
                pass

        return []

    def _parse_kinopub(self, url: str) -> list:
        driver = None
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--log-level=3')
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

            profile_dir = os.path.join(get_base_dir(), 'browser_profile')
            os.makedirs(profile_dir, exist_ok=True)
            options.add_argument(f"user-data-dir={profile_dir}")

            service = Service()
            service.creation_flags = subprocess.CREATE_NO_WINDOW

            try:
                driver = webdriver.Edge(service=service, options=options)
            except:
                fallback_options = Options()
                fallback_options.add_argument('--headless')
                fallback_options.add_argument('--disable-gpu')
                fallback_options.add_argument('--log-level=3')
                driver = webdriver.Edge(service=service, options=fallback_options)

            driver.get(url)
            time.sleep(4)

            page_source = driver.page_source

            session = requests.Session()
            for cookie in driver.get_cookies():
                session.cookies.set(cookie['name'], cookie['value'])

            try:
                driver.quit()
            except:
                pass

            soup = BeautifulSoup(page_source, 'html.parser')

            title_el = soup.select_one('.b-post__title h1')
            anime_title = title_el.text.strip() if title_el else "Видео"
            safe_anime_title = re.sub(r'[\\/*?:"<>|]', "", anime_title)

            post_id_el = soup.select_one('#post_id')
            post_id = post_id_el.get('value') if post_id_el else None
            if not post_id:
                post_id_match = re.search(r'data-id="(\d+)"', page_source)
                post_id = post_id_match.group(1) if post_id_match else None

            voiceovers = [{'name': el.text.strip(), 'id': el.get('data-translator_id')} for el in
                          soup.select('#translators-list li.b-translator__item')]
            seasons = [{'name': el.text.strip(), 'id': el.get('data-tab_id')} for el in
                       soup.select('#simple-seasons-tabs li.b-simple_season__item')]
            episodes = [
                {'name': el.text.strip(), 'id': el.get('data-episode_id'), 'season_id': el.get('data-season_id')} for el
                in soup.select('.b-simple_episodes__list li.b-simple_episode__item')]

            is_movie = len(episodes) == 0

            if not voiceovers: voiceovers = [{'name': 'По умолчанию', 'id': ''}]
            if not seasons: seasons = [{'name': '1 Сезон', 'id': '1'}]
            if not episodes: episodes = [{'name': 'Полный фильм', 'id': '1', 'season_id': '1'}]

            # --- ПРОБНЫЙ ЗАПРОС ДЛЯ ПАРСИНГА ДОСТУПНОГО КАЧЕСТВА ---
            available_qualities = ["1080", "720", "480", "360"]
            sample_streams_raw = None

            if post_id:
                sample_voice = voiceovers[0]['id'] if voiceovers else ''
                ajax_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}/ajax/get_cdn_series/"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': url,
                    'Origin': f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                }
                data = {'id': post_id, 'translator_id': sample_voice}

                if is_movie:
                    data['action'] = 'get_movie'
                else:
                    data['action'] = 'get_cdn_series'
                    data['season'] = seasons[0]['id'] if seasons else '1'
                    data['episode'] = episodes[0]['id'] if episodes else '1'

                try:
                    ajax_req = session.post(ajax_url, headers=headers, data=data, timeout=10)
                    if ajax_req.status_code == 200:
                        sample_streams_raw = ajax_req.json().get('url', '').replace('\\/', '/')
                except Exception as e:
                    logger.debug(f"Failed to fetch sample stream: {e}")

            if not sample_streams_raw:
                streams_match = re.search(r'"streams"\s*:\s*"([^"]+)"', page_source)
                if streams_match:
                    sample_streams_raw = streams_match.group(1).replace('\\/', '/')

            if sample_streams_raw:
                q_matches = re.findall(r'\[(\d+)p?[^\]]*\]', sample_streams_raw)
                if q_matches:
                    # Убираем дубликаты и сортируем по убыванию
                    unique_q = sorted(list(set(int(q) for q in q_matches)), reverse=True)
                    available_qualities = [str(q) for q in unique_q]
            # --------------------------------------------------------

            results = []

            if post_id:
                v_names = [v['name'] for v in voiceovers]
                s_names = [s['name'] for s in seasons]
                e_names = [e['name'] for e in episodes]

                dialog = EpisodeSelectionDialog(v_names, s_names, e_names, available_qualities, is_movie=is_movie)

                if dialog.exec():
                    v_index = dialog.voiceover_combo.currentIndex()
                    s_index = dialog.season_combo.currentIndex()
                    e_index = dialog.episode_combo.currentIndex()

                    selected_voice = voiceovers[v_index]['id']
                    selected_season = seasons[s_index]['id']
                    selected_quality = int(dialog.quality_combo.currentText())

                    safe_v_name = re.sub(r'[\\/*?:"<>|]', "", voiceovers[v_index]['name'])
                    safe_s_name = re.sub(r'[\\/*?:"<>|]', "", seasons[s_index]['name'])

                    parsed_uri = urlparse(url)
                    base_origin = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
                    ajax_url = f"{base_origin}/ajax/get_cdn_series/"
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                        'X-Requested-With': 'XMLHttpRequest',
                        'Referer': url,
                        'Origin': base_origin
                    }

                    targets = []
                    if dialog.download_all and not is_movie:
                        targets = [ep for ep in episodes if ep['season_id'] == selected_season]
                    else:
                        targets = [episodes[e_index]]

                    for idx, ep in enumerate(targets):
                        self.status_updated.emit(f"Получаю ссылки: {idx + 1} из {len(targets)}...")
                        QApplication.processEvents()

                        data = {
                            'id': post_id,
                            'translator_id': selected_voice,
                            'action': 'get_movie' if is_movie else 'get_episodes'
                        }
                        if not is_movie:
                            data['season'] = selected_season
                            data['episode'] = ep['id']

                        ajax_req = session.post(ajax_url, headers=headers, data=data, timeout=15)
                        if ajax_req.status_code == 200:
                            streams_raw = ajax_req.json().get('url', '').replace('\\/', '/')
                            best_link = self._extract_best_link(streams_raw, target_res=selected_quality)

                            if best_link:
                                safe_e_name = re.sub(r'[\\/*?:"<>|]', "", ep['name'])
                                if is_movie:
                                    custom_title = f"{safe_anime_title} ({safe_v_name})"
                                else:
                                    custom_title = f"{safe_anime_title} - {safe_s_name} {safe_e_name} ({safe_v_name})"

                                results.append({'url': best_link, 'title': custom_title})
                        time.sleep(0.5)

                    return results
                else:
                    logger.info("Выбор отменен пользователем.")
                    return None

            streams_match = re.search(r'"streams"\s*:\s*"([^"]+)"', page_source)
            if streams_match:
                streams_raw = streams_match.group(1).replace('\\/', '/')
                best_link = self._extract_best_link(streams_raw)
                if best_link:
                    return [{'url': best_link, 'title': safe_anime_title}]

        except Exception as e:
            import traceback
            err = traceback.format_exc()
            logger.error(f"Глобальная ошибка сканера: {err}")
            try:
                if driver: driver.quit()
            except:
                pass

        return []