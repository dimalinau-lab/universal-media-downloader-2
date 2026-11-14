import os
import re
import threading
from enum import Enum
from PyQt6.QtCore import QObject, pyqtSignal
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
        self.available_streams = {}
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
        if getattr(self, 'available_streams', None) and not info.get('available_streams'):
            self.info['available_streams'] = self.available_streams
        elif info.get('available_streams'):
            self.available_streams = info['available_streams']
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

        # Smart size estimation based on selected quality / badge
        calc_size = None
        formats = info.get('formats', [])
        duration = info.get('duration', 0)
        is_audio_mode = badge in ('MP3', 'AUDIO') or getattr(self, 'quality_override', '') in ('audio_only', 'audio_mp3') or getattr(self, 'audio_only', False)

        if formats:
            if is_audio_mode:
                best_a = None
                for f in formats:
                    if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                        if not best_a or (f.get('abr') or 0) > (best_a.get('abr') or 0):
                            best_a = f
                if best_a:
                    calc_size = best_a.get('filesize') or best_a.get('filesize_approx')
                    if not calc_size and duration and best_a.get('abr'):
                        calc_size = int((best_a['abr'] * 1000 / 8) * duration)
                if not calc_size and duration:
                    calc_size = int((320 * 1000 / 8) * duration)
            elif badge and badge.rstrip('p').isdigit():
                target_h = int(badge.rstrip('p'))
                audio_sz = 0
                for f in formats:
                    if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                        audio_sz = max(audio_sz, f.get('filesize') or f.get('filesize_approx') or 0)
                cand_vf = None
                for f in formats:
                    if f.get('height') == target_h:
                        if not cand_vf or (f.get('filesize') or f.get('tbr') or 0) > (cand_vf.get('filesize') or cand_vf.get('tbr') or 0):
                            cand_vf = f
                if cand_vf:
                    v_sz = cand_vf.get('filesize') or cand_vf.get('filesize_approx') or 0
                    if not v_sz and duration and (cand_vf.get('tbr') or cand_vf.get('vbr')):
                        v_sz = int(((cand_vf.get('tbr') or cand_vf.get('vbr')) * 1000 / 8) * duration)
                    calc_size = v_sz + (audio_sz if cand_vf.get('acodec') == 'none' else 0)

        filesize = calc_size or info.get('filesize') or info.get('filesize_approx')
        if filesize:
            self.set_file_size(filesize)

        self.info_updated.emit()
        self.set_status(self.Status.PENDING)
        if self.thumbnail_url and not self.thumbnail_loading:
            self.thumbnail_loading = True
            self.thumbnail_load_requested.emit(self.thumbnail_url, self)

    def set_file_size(self, bytes_val, force=False):
        if not bytes_val:
            return
        try:
            b = float(bytes_val)
            if not force and self._status == self.Status.DOWNLOADING and hasattr(self, '_raw_file_size_bytes'):
                if b < self._raw_file_size_bytes * 0.7:
                    # Защита от сброса веса видеопотока при начале скачивания меньшего аудиопотока
                    return
            self._raw_file_size_bytes = b
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
        from .threads import clean_ansi
        self.progress = percent
        cleaned = clean_ansi(text)
        self.progress_text = cleaned
        self.progress_updated.emit(percent, cleaned)

    def set_error(self, message):
        from .threads import clean_ansi
        cleaned = clean_ansi(message)
        self.error_message = cleaned
        self.set_status(self.Status.ERROR)

    def set_completed(self, filepath):
        self.final_filepath = filepath
        if filepath and os.path.exists(filepath):
            try:
                self.set_file_size(os.path.getsize(filepath))
            except Exception:
                pass
        self.set_status(self.Status.COMPLETED)
        self.update_progress(100, "")

    def request_stop(self, *_args, **kwargs):
        self.is_removed = kwargs.get('is_removed', False)
        self._stop_event.set()

        if not self.is_removed and self.status == self.Status.DOWNLOADING:
            self.set_status(self.Status.PROCESSING)
            self.update_progress(95, "Остановлена запись. Беру файлы и начинаю склейку...")

    def is_stop_requested(self):
        return self._stop_event.is_set()