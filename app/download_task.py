import os
import re
import threading
from enum import Enum
from PyQt6.QtCore import QObject, pyqtSignal, QUrl
from PyQt6.QtGui import QPixmap, QImage


class DownloadTask(QObject):
    class Status(Enum):
        PENDING = "pending"
        FETCHING_INFO = "fetching_info"
        DOWNLOADING = "downloading"
        PROCESSING = "processing"
        COMPLETED = "completed"
        ERROR = "error"
        STOPPED = "stopped"

    info_updated = pyqtSignal()
    status_changed = pyqtSignal(Status)
    progress_updated = pyqtSignal(int, str)
    thumbnail_loaded = pyqtSignal(QPixmap)
    thumbnail_load_requested = pyqtSignal(str, object)
    size_updated = pyqtSignal(str)
    time_range_updated = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.title = "..."
        self.thumbnail_url = None
        self.thumbnail = None
        self.platform = "Unknown"
        self._status = self.Status.FETCHING_INFO
        self.progress = 0
        self.progress_text = ""
        self.error_message = ""
        self.list_item = None
        self._stop_event = threading.Event()
        self.output_path = ""
        self.temp_path = ""
        self.video_id = None
        self.current_tmpfilename = None
        self.current_filename = None
        self.final_filepath = None
        self.thumbnail_loading = False
        self.file_size_str = ""
        self.quality_badge = ""
        self.custom_quality = None
        self.custom_title = None
        self.time_range = None  # tuple (start_sec, end_sec)
        self.time_range_str = ""  # string label e.g. "00:01:20 - 00:03:45"
        self.info = {}
        self.is_removed = False

    def set_time_range(self, start_sec: float, end_sec: float, label: str = ""):
        self.time_range = (start_sec, end_sec)
        self.time_range_str = label
        self.time_range_updated.emit(self.time_range_str)

    def clear_time_range(self):
        self.time_range = None
        self.time_range_str = ""
        self.time_range_updated.emit("")

    @property
    def status(self):
        return self._status

    def set_status(self, new_status):
        if self._status != new_status:
            self._status = new_status
            self.status_changed.emit(new_status)

    def update_info(self, info):
        self.info = info
        if hasattr(self, 'custom_title') and self.custom_title:
            self.title = self.custom_title
        else:
            raw_title = info.get('title', 'Unknown Title')
            if raw_title in ('720', '1080', '480', '360', 'master', 'manifest', 'index') or (isinstance(raw_title, str) and raw_title.isdigit()):
                if any(d in self.url for d in ('solodcdn', 'kodik')):
                    raw_title = f"Kodik Video ({raw_title}p)" if raw_title.isdigit() else "Kodik Video"
                elif any(d in self.url for d in ('ya-ligh', 'aniboom')):
                    raw_title = "AniBoom Video"
            self.title = raw_title

        new_thumb = info.get('thumbnail')
        if new_thumb:
            self.thumbnail_url = new_thumb

        self.platform = info.get('extractor_key', 'Unknown')
        self.video_id = info.get('id')

        # Определение значка качества / формата
        badge = ""
        if hasattr(self, 'custom_quality') and self.custom_quality:
            badge = self.custom_quality
        elif hasattr(self, 'quality_badge') and self.quality_badge:
            badge = self.quality_badge
        elif info.get('height'):
            height = info.get('height')
            badge = f"{height}p"
            fps = info.get('fps')
            if fps and int(fps) >= 50:
                badge += f"{int(fps)}"
        elif info.get('resolution'):
            badge = str(info.get('resolution'))
        elif info.get('format_note'):
            badge = str(info.get('format_note'))
        elif info.get('acodec') and (not info.get('vcodec') or info.get('vcodec') == 'none'):
            badge = "AUDIO"
        else:
            # Попробуем извлечь разрешение из URL (например, /1080/ или _720p. или [1080p])
            url_match = re.search(r'[/_\[](\d{3,4})p?[\._/\]]', self.url)
            if url_match:
                badge = f"{url_match.group(1)}p"

        self.quality_badge = badge

        filesize = info.get('filesize') or info.get('filesize_approx')
        if filesize:
            self.set_file_size(filesize)

        self.info_updated.emit()
        self.set_status(self.Status.PENDING)
        if self.thumbnail_url and not self.thumbnail_loading:
            self.thumbnail_loading = True
            self.thumbnail_load_requested.emit(self.thumbnail_url, self)

    def set_file_size(self, bytes_val):
        if not bytes_val:
            return
        try:
            b = float(bytes_val)
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if b < 1024.0:
                    new_str = f"{b:.1f} {unit}"
                    if self.file_size_str != new_str:
                        self.file_size_str = new_str
                        self.size_updated.emit(self.file_size_str)
                    return
                b /= 1024.0
        except ValueError:
            pass

    def update_current_paths(self, tmpfilename=None, filename=None):
        if tmpfilename:
            self.current_tmpfilename = tmpfilename
        if filename:
            self.current_filename = filename

    def set_thumbnail(self, image_or_pixmap):
        if isinstance(image_or_pixmap, QImage):
            pixmap = QPixmap.fromImage(image_or_pixmap)
        elif isinstance(image_or_pixmap, QPixmap):
            pixmap = image_or_pixmap
        else:
            return
        self.thumbnail = pixmap
        self.thumbnail_loaded.emit(pixmap)
        self.thumbnail_loading = False

    def update_progress(self, percent, text):
        self.progress = percent
        self.progress_text = text
        self.progress_updated.emit(percent, text)

    def set_error(self, message):
        self.error_message = message
        self.set_status(self.Status.ERROR)

    def set_completed(self, filepath):
        self.final_filepath = filepath
        self.set_status(self.Status.COMPLETED)
        self.update_progress(100, "")

    def request_stop(self, *args, **kwargs):
        self.is_removed = kwargs.get('is_removed', False)
        self._stop_event.set()

        if not self.is_removed and self.status == self.Status.DOWNLOADING:
            self.set_status(self.Status.PROCESSING)
            self.update_progress(95, "Остановлена запись. Беру файлы и начинаю склейку...")

    def is_stop_requested(self):
        return self._stop_event.is_set()