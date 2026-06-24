import os
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
        self.info = {}
        # Флаг для корзины
        self.is_removed = False

    @property
    def status(self):
        return self._status

    def set_status(self, new_status):
        if self._status != new_status:
            self._status = new_status
            self.status_changed.emit(new_status)

    def update_info(self, info):
        self.info = info
        self.title = info.get('title', 'Unknown Title')
        self.thumbnail_url = info.get('thumbnail')
        self.platform = info.get('extractor_key', 'Unknown')
        self.video_id = info.get('id')

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

    def set_thumbnail(self, pixmap):
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

    # --- БРОНЕБОЙНЫЙ ФИКС КНОПКИ СТОП ---
    def request_stop(self, *args, **kwargs):
        # args перехватывает скрытый сигнал от кнопки интерфейса PyQt
        # kwargs ловит команду от Корзины, если мы решили удалить файл
        self.is_removed = kwargs.get('is_removed', False)
        self._stop_event.set()

        # Мгновенный отклик интерфейса!
        if not self.is_removed and self.status == self.Status.DOWNLOADING:
            self.set_status(self.Status.PROCESSING)
            self.update_progress(95, "Остановлена запись. Беру файлы и начинаю склейку...")

    def is_stop_requested(self):
        return self._stop_event.is_set()