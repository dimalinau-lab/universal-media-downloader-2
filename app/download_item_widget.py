import logging
import os
import re
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QMenu,
                             QMessageBox, QApplication, QToolTip, QDialog, QGridLayout,
                             QPushButton)
from PyQt6.QtGui import QAction, QKeySequence, QCursor
from PyQt6.QtCore import QSize, Qt, pyqtSignal, QRect, QObject, QEvent
from qfluentwidgets import (TransparentToolButton, FluentIcon, ProgressBar,
                            StrongBodyLabel, BodyLabel, CaptionLabel,
                            PushButton, PrimaryPushButton, LineEdit,
                            RoundMenu, Action)
from .download_task import DownloadTask
from .stream_helper import StreamResolverHelper


logger = logging.getLogger(__name__)


class TimeRangeDialog(QDialog):
    def __init__(self, task: DownloadTask, translator, parent=None, is_pre_download=False):
        super().__init__(parent)
        self.task = task
        self.translator = translator
        self.is_pre_download = is_pre_download
        self.setWindowTitle(self.translator.translate('time_range_title', "Указать отрезок времени для скачивания"))
        self.setMinimumWidth(430)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = StrongBodyLabel(self.task.title)
        title.setWordWrap(True)
        layout.addWidget(title)

        desc = CaptionLabel(self.translator.translate('time_range_desc', "Будет скачан только выбранный фрагмент (без загрузки всего видео):"))
        desc.setStyleSheet("color: #888888;")
        layout.addWidget(desc)

        duration = self.task.info.get('duration') if isinstance(self.task.info, dict) else None
        if duration:
            dur_m, dur_s = divmod(int(duration), 60)
            dur_h, dur_m = divmod(dur_m, 60)
            dur_str = f"{dur_h:02d}:{dur_m:02d}:{dur_s:02d}"
            dur_lbl = CaptionLabel(f"Длительность оригинала: {dur_str}")
            dur_lbl.setStyleSheet("color: #29b6f6; font-weight: bold;")
            layout.addWidget(dur_lbl)

        grid = QGridLayout()
        grid.setSpacing(10)

        lbl_start = BodyLabel(self.translator.translate('time_range_start', "Начало (ЧЧ:ММ:СС):"))
        self.input_start = LineEdit()
        self.input_start.setPlaceholderText("00:00:00")

        lbl_end = BodyLabel(self.translator.translate('time_range_end', "Конец (ЧЧ:ММ:СС):"))
        self.input_end = LineEdit()
        self.input_end.setPlaceholderText("00:00:00")

        if self.task.time_range:
            s_sec, e_sec = self.task.time_range
            self.input_start.setText(self._sec_to_str(s_sec))
            self.input_end.setText(self._sec_to_str(e_sec))
        elif duration:
            self.input_start.setText("00:00:00")
            dur_m, dur_s = divmod(int(duration), 60)
            dur_h, dur_m = divmod(dur_m, 60)
            self.input_end.setText(f"{dur_h:02d}:{dur_m:02d}:{dur_s:02d}")
        else:
            self.input_start.setText("00:00:00")
            self.input_end.setText("00:05:00")

        grid.addWidget(lbl_start, 0, 0)
        grid.addWidget(self.input_start, 0, 1)
        grid.addWidget(lbl_end, 1, 0)
        grid.addWidget(self.input_end, 1, 1)
        layout.addLayout(grid)

        btn_box = QHBoxLayout()
        if self.is_pre_download:
            btn_full = PushButton(self.translator.translate('download_full_video', "Скачать целиком"))
            btn_full.clicked.connect(self.on_full_download)

            btn_cancel = PushButton(self.translator.translate('cancel_action', "Отмена"))
            btn_cancel.clicked.connect(self.reject)

            btn_apply = PrimaryPushButton(self.translator.translate('download_time_range', "Скачать отрезок"))
            btn_apply.clicked.connect(self.on_apply)

            btn_box.addWidget(btn_full)
            btn_box.addStretch()
            btn_box.addWidget(btn_cancel)
            btn_box.addWidget(btn_apply)
        else:
            btn_reset = PushButton(self.translator.translate('time_range_reset', "Сбросить"))
            btn_reset.clicked.connect(self.on_reset)

            btn_cancel = PushButton(self.translator.translate('cancel_action', "Отмена"))
            btn_cancel.clicked.connect(self.reject)

            btn_apply = PrimaryPushButton(self.translator.translate('time_range_apply', "Применить"))
            btn_apply.clicked.connect(self.on_apply)

            btn_box.addWidget(btn_reset)
            btn_box.addStretch()
            btn_box.addWidget(btn_cancel)
            btn_box.addWidget(btn_apply)
        layout.addLayout(btn_box)

    def on_full_download(self):
        self.task.clear_time_range()
        self.accept()

    @staticmethod
    def _sec_to_str(sec):
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _parse_time(t_str):
        parts = t_str.strip().split(':')
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1 and parts[0]:
            return float(parts[0])
        return 0.0

    def on_apply(self):
        try:
            start_s = self._parse_time(self.input_start.text())
            end_s = self._parse_time(self.input_end.text())
            if end_s <= start_s:
                QMessageBox.warning(self, "Ошибка", "Время окончания должно быть больше времени начала.")
                return
            label = f"{self._sec_to_str(start_s)} - {self._sec_to_str(end_s)}"
            self.task.set_time_range(start_s, end_s, label)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Неверный формат времени: {e}")

    def on_reset(self):
        self.task.clear_time_range()
        self.accept()


class UrlCopyFilter(QObject):
    """Фильтр событий для гарантированного копирования полной ссылки при нажатии Ctrl+C"""
    def __init__(self, url_getter, parent=None):
        super().__init__(parent)
        self.url_getter = url_getter

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.matches(QKeySequence.StandardKey.Copy):
                url = self.url_getter()
                if url:
                    QApplication.clipboard().setText(url)
                    return True
        return super().eventFilter(obj, event)


class DownloadItemWidget(QWidget):
    remove_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    open_file_requested = pyqtSignal()
    copy_link_requested = pyqtSignal()
    start_or_retry_requested = pyqtSignal()
    media_info_requested = pyqtSignal()
    convert_audio_requested = pyqtSignal()
    move_top_requested = pyqtSignal()
    move_up_requested = pyqtSignal()
    move_down_requested = pyqtSignal()
    move_bottom_requested = pyqtSignal()
    interactive_sniff_requested = pyqtSignal()

    def __init__(self, task: DownloadTask, translator):
        super().__init__()
        self.task = task
        self.translator = translator
        self.setObjectName('DownloadItem')
        self.initUI()
        self.connect_signals()
        self.update_ui()

    @staticmethod
    def format_display_url(url: str, max_len: int = 65) -> str:
        """Ограничивает отображаемую длину ссылки в карточке интерфейса"""
        if not url:
            return ""
        if len(url) <= max_len:
            return url
        head_len = 42
        tail_len = max(max_len - head_len - 3, 16)
        return f"{url[:head_len]}...{url[-tail_len:]}"

    def copy_full_url(self):
        """Копирует полную ссылку в буфер обмена и показывает всплывающую подсказку"""
        QApplication.clipboard().setText(self.task.url)
        self.copy_link_requested.emit()
        copied_text = self.translator.translate('copied', 'Ссылка скопирована')
        QToolTip.showText(QCursor.pos(), copied_text, self.btn_copy_url, QRect(), 1500)

    def initUI(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(15)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(144, 81)
        self.thumbnail_label.setObjectName('Thumbnail')
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.thumbnail_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        self.title_label = StrongBodyLabel(self.task.title)
        self.title_label.setObjectName('TitleLabel')
        self.title_label.setWordWrap(True)

        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(6)

        display_url = self.format_display_url(self.task.url)
        self.url_label = CaptionLabel(display_url)
        self.url_label.setObjectName('UrlLabel')
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url_label.setToolTip(self.task.url)
        self.url_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_label.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(self.url_label.mapTo(self, pos))
        )
        self._url_copy_filter = UrlCopyFilter(lambda: self.task.url, self.url_label)
        self.url_label.installEventFilter(self._url_copy_filter)

        self.btn_copy_url = TransparentToolButton(FluentIcon.COPY)
        self.btn_copy_url.setFixedSize(22, 22)
        self.btn_copy_url.setIconSize(QSize(13, 13))
        self.btn_copy_url.setToolTip(self.translator.translate('copy_link', 'Копировать ссылку'))
        self.btn_copy_url.clicked.connect(self.copy_full_url)

        self.badge_quality = QPushButton()
        self.badge_quality.setObjectName('BadgeQuality')
        self.badge_quality.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge_quality.setFixedHeight(22)
        self.badge_quality.setToolTip("Нажмите для выбора качества видео или MP3")
        self.badge_quality.clicked.connect(self.show_quality_selection_menu)
        self.badge_quality.hide()

        self.badge_timerange = CaptionLabel()
        self.badge_timerange.setObjectName('BadgeTimeRange')
        self.badge_timerange.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge_timerange.setToolTip("Нажмите для изменения отрезка времени")
        self.badge_timerange.mousePressEvent = lambda _e: self.open_time_range_dialog()
        self.badge_timerange.hide()

        url_row.addWidget(self.url_label)
        url_row.addWidget(self.btn_copy_url)
        url_row.addWidget(self.badge_quality)
        url_row.addWidget(self.badge_timerange)
        url_row.addStretch()

        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setValue(0)

        status_layout = QHBoxLayout()

        self.status_label = BodyLabel()
        self.status_label.setObjectName('StatusLabelItem')

        self.size_label = StrongBodyLabel()
        self.size_label.setObjectName('SizeLabelItem')
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.size_label)

        info_layout.addWidget(self.title_label)
        info_layout.addLayout(url_row)
        info_layout.addSpacing(4)
        info_layout.addWidget(self.progress_bar)
        info_layout.addLayout(status_layout)
        info_layout.addStretch()

        main_layout.addLayout(info_layout, 1)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(6)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.play_button = TransparentToolButton(FluentIcon.PLAY)
        self.play_button.setFixedSize(34, 34)
        self.play_button.setToolTip(self.translator.translate('play_video', 'Смотреть видео'))
        self.play_button.clicked.connect(self.open_file_requested.emit)

        self.download_button = TransparentToolButton(FluentIcon.DOWNLOAD)
        self.download_button.setFixedSize(34, 34)
        self.download_button.setToolTip("Скачать файл / Возобновить")
        self.download_button.clicked.connect(self.on_start_clicked)

        self.sniff_browser_button = TransparentToolButton(FluentIcon.GLOBE)
        self.sniff_browser_button.setFixedSize(34, 34)
        self.sniff_browser_button.setToolTip(
            self.translator.translate('interactive_sniff_tooltip', 'Открыть страницу в браузере и перехватить поток вручную')
        )
        self.sniff_browser_button.clicked.connect(self.interactive_sniff_requested.emit)
        self.sniff_browser_button.hide()

        self.timerange_button = TransparentToolButton(FluentIcon.HISTORY)
        self.timerange_button.setFixedSize(34, 34)
        self.timerange_button.setToolTip(self.translator.translate('time_range', 'Скачать отрезок / таймкоды'))
        self.timerange_button.clicked.connect(self.open_time_range_dialog)
        self.timerange_button.hide()

        self.stop_button = TransparentToolButton(FluentIcon.PAUSE)
        self.stop_button.setFixedSize(34, 34)
        self.stop_button.setToolTip("Завершить стрим и СОБРАТЬ видео")
        self.stop_button.clicked.connect(self.task.request_stop)

        self.folder_button = TransparentToolButton(FluentIcon.FOLDER)
        self.folder_button.setFixedSize(34, 34)
        self.folder_button.setToolTip(self.translator.translate('show_in_folder', 'Показать в папке'))
        self.folder_button.clicked.connect(self.open_folder_requested.emit)

        self.more_button = TransparentToolButton(FluentIcon.MORE)
        self.more_button.setFixedSize(34, 34)
        self.more_button.setToolTip(self.translator.translate('more_actions', 'Другие действия'))
        self.more_button.clicked.connect(self.show_more_menu)

        self.remove_button = TransparentToolButton(FluentIcon.DELETE)
        self.remove_button.setFixedSize(34, 34)
        self.remove_button.setToolTip(self.translator.translate('remove_from_list', 'Убрать из списка'))
        self.remove_button.clicked.connect(self.remove_requested.emit)

        buttons_layout.addWidget(self.play_button)
        buttons_layout.addWidget(self.download_button)
        buttons_layout.addWidget(self.sniff_browser_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.folder_button)
        buttons_layout.addWidget(self.more_button)
        buttons_layout.addWidget(self.remove_button)

        order_layout = QVBoxLayout()
        order_layout.setSpacing(2)
        order_layout.setContentsMargins(2, 0, 0, 0)
        order_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.move_up_button = TransparentToolButton(FluentIcon.UP)
        self.move_up_button.setFixedSize(24, 18)
        self.move_up_button.setIconSize(QSize(10, 10))
        self.move_up_button.setToolTip(self.translator.translate('move_up_queue', 'Поднять выше в очереди'))
        self.move_up_button.clicked.connect(self.move_up_requested.emit)

        self.move_down_button = TransparentToolButton(FluentIcon.DOWN)
        self.move_down_button.setFixedSize(24, 18)
        self.move_down_button.setIconSize(QSize(10, 10))
        self.move_down_button.setToolTip(self.translator.translate('move_down_queue', 'Опустить ниже в очереди'))
        self.move_down_button.clicked.connect(self.move_down_requested.emit)

        order_layout.addWidget(self.move_up_button)
        order_layout.addWidget(self.move_down_button)
        buttons_layout.addLayout(order_layout)

        main_layout.addLayout(buttons_layout)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def is_stream_active(self):
        is_stream = getattr(self.task, 'is_stream_mode', False)
        is_running = self.task.status in (DownloadTask.Status.DOWNLOADING, DownloadTask.Status.PROCESSING)
        is_stopped = self.task.is_stop_requested()
        return is_stream and is_running and not is_stopped

    def on_start_clicked(self):
        if hasattr(self.task, '_stop_event'):
            self.task._stop_event.clear()

        is_live = False

        if hasattr(self.task, 'info') and isinstance(self.task.info, dict):
            live_status = self.task.info.get('live_status')
            duration = self.task.info.get('duration')

            if live_status in ('is_live', 'is_upcoming') or self.task.info.get('is_live') is True:
                is_live = True
            elif live_status in ('was_live', 'post_live'):
                is_live = False
            elif duration in (0, None):
                is_live = True

        if not is_live and 'twitch.tv' in self.task.url.lower() and '/videos/' not in self.task.url.lower() and '/clip/' not in self.task.url.lower():
            if hasattr(self.task, 'info') and isinstance(self.task.info, dict) and not self.task.info.get('is_live'):
                QMessageBox.warning(self, "Канал Оффлайн",
                                    "Этот Twitch канал сейчас не в эфире. Скачивание невозможно.")
                return
            is_live = True
        if is_live:
            self.task.stream_mode_choice = 'from_now'

        self.start_or_retry_requested.emit()

    def show_more_menu(self):
        self.show_context_menu(self.more_button.rect().bottomLeft(), parent_widget=self.more_button)

    def show_context_menu(self, pos, parent_widget=None):
        menu = QMenu(self)
        act_open_file = QAction(self.translator.translate('open_file', 'Смотреть видео'), self)
        act_start = QAction("Скачать / Возобновить", self)
        act_interactive_sniff = QAction(
            self.translator.translate('interactive_sniff_menu', 'Открыть в браузере (перехватить поток)...'), self
        )
        act_timerange = QAction(self.translator.translate('time_range', 'Скачать отрезок (таймкоды)...'), self)
        act_mediainfo = QAction(self.translator.translate('media_info', 'Свойства медиа (MediaInfo)...'), self)
        act_convert_audio = QAction(self.translator.translate('convert_audio', 'Извлечь / Конвертировать аудио...'), self)
        act_open = QAction(self.translator.translate('open_save_folder', 'Открыть папку'), self)
        act_copy = QAction(self.translator.translate('copy_link', 'Копировать ссылку'), self)
        act_remove = QAction(self.translator.translate('remove_from_list', 'Убрать из списка'), self)

        act_open_file.triggered.connect(self.open_file_requested.emit)
        act_start.triggered.connect(self.on_start_clicked)
        act_interactive_sniff.triggered.connect(self.interactive_sniff_requested.emit)
        act_timerange.triggered.connect(self.open_time_range_dialog)
        act_mediainfo.triggered.connect(self.media_info_requested.emit)
        act_convert_audio.triggered.connect(self.convert_audio_requested.emit)
        act_open.triggered.connect(self.open_folder_requested.emit)
        act_copy.triggered.connect(self.copy_full_url)
        act_remove.triggered.connect(self.remove_requested.emit)

        is_incomplete = self.task.status in (DownloadTask.Status.STOPPED, DownloadTask.Status.ERROR)
        is_completed = self.task.status == DownloadTask.Status.COMPLETED
        is_startable = self.task.status in (
            DownloadTask.Status.PENDING, DownloadTask.Status.ERROR, DownloadTask.Status.STOPPED)
        act_start.setEnabled(is_startable)
        act_interactive_sniff.setEnabled(not is_completed)
        act_timerange.setEnabled(self.task.status in (DownloadTask.Status.PENDING, DownloadTask.Status.COMPLETED))

        act_open_file.setEnabled(is_completed)
        act_mediainfo.setEnabled(is_completed)
        act_convert_audio.setEnabled(is_completed)
        act_open.setEnabled(is_completed)
        act_copy.setEnabled(not is_incomplete)

        menu.addAction(act_open_file)
        menu.addAction(act_start)
        menu.addAction(act_interactive_sniff)
        menu.addAction(act_timerange)
        menu.addSeparator()

        act_move_top = QAction(self.translator.translate('move_top_queue', 'В начало очереди'), self)
        act_move_up = QAction(self.translator.translate('move_up_queue', 'Поднять выше'), self)
        act_move_down = QAction(self.translator.translate('move_down_queue', 'Опустить ниже'), self)
        act_move_bottom = QAction(self.translator.translate('move_bottom_queue', 'В конец очереди'), self)
        can_reorder = not is_incomplete
        for act in (act_move_top, act_move_up, act_move_down, act_move_bottom):
            act.setEnabled(can_reorder)
        act_move_top.triggered.connect(self.move_top_requested.emit)
        act_move_up.triggered.connect(self.move_up_requested.emit)
        act_move_down.triggered.connect(self.move_down_requested.emit)
        act_move_bottom.triggered.connect(self.move_bottom_requested.emit)
        menu.addAction(act_move_top)
        menu.addAction(act_move_up)
        menu.addAction(act_move_down)
        menu.addAction(act_move_bottom)
        menu.addSeparator()

        menu.addAction(act_mediainfo)
        menu.addAction(act_convert_audio)
        menu.addSeparator()
        menu.addAction(act_open)
        menu.addAction(act_copy)
        menu.addSeparator()
        menu.addAction(act_remove)

        target_pos = parent_widget.mapToGlobal(pos) if parent_widget is not None else self.mapToGlobal(pos)
        menu.exec(target_pos)

    def connect_signals(self):
        self.task.info_updated.connect(self.update_ui)
        self.task.status_changed.connect(self.update_ui)
        self.task.progress_updated.connect(self.on_progress_update)
        self.task.thumbnail_loaded.connect(self.set_thumbnail)
        self.task.size_updated.connect(self.on_size_update)
        self.task.time_range_updated.connect(self.on_time_range_update)

    def disconnect_signals(self):
        for sig, slot in (
            (self.task.info_updated, self.update_ui),
            (self.task.status_changed, self.update_ui),
            (self.task.progress_updated, self.on_progress_update),
            (self.task.thumbnail_loaded, self.set_thumbnail),
            (self.task.size_updated, self.on_size_update),
            (self.task.time_range_updated, self.on_time_range_update),
        ):
            try:
                sig.disconnect(slot)
            except Exception:
                pass

    def on_time_range_update(self, text):
        if text:
            self.badge_timerange.setText(text)
            self.badge_timerange.show()
        else:
            self.badge_timerange.hide()

    def open_time_range_dialog(self):
        dialog = TimeRangeDialog(self.task, self.translator, self)
        dialog.exec()

    def on_size_update(self, size_str):
        self.size_label.setText(size_str)

    def on_progress_update(self, percent, text):
        if percent == 0 and ("запис" in text.lower() or "record" in text.lower() or getattr(self.task, "is_stream", False)):
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)
        clean_text = re.sub(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?(?:\x07|\x1b\\)', '', text or '')
        clean_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean_text).strip()
        self.status_label.setText(clean_text)

    def set_thumbnail(self, pixmap):
        scaled_pixmap = pixmap.scaled(self.thumbnail_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        self.thumbnail_label.setPixmap(scaled_pixmap)

    def update_ui(self):
        self.title_label.setText(self.task.title)
        display_url = self.format_display_url(self.task.url)
        self.url_label.setText(display_url)
        self.url_label.full_url = self.task.url
        self.url_label.setToolTip(self.task.url)
        self.size_label.setText(self.task.file_size_str)

        badge_text = getattr(self.task, 'quality_badge', '')
        if badge_text:
            clean_badge = badge_text.replace(' ▾', '').strip()
            self.badge_quality.setText(f"{clean_badge} ▾")
            self.badge_quality.show()
        else:
            self.badge_quality.hide()

        tr_text = getattr(self.task, 'time_range_str', '')
        if tr_text:
            self.badge_timerange.setText(tr_text)
            self.badge_timerange.show()
        else:
            self.badge_timerange.hide()

        status = self.task.status
        self.progress_bar.setVisible(
            status == DownloadTask.Status.DOWNLOADING or status == DownloadTask.Status.PROCESSING)

        is_active = status in (DownloadTask.Status.FETCHING_INFO, DownloadTask.Status.DOWNLOADING,
                               DownloadTask.Status.PROCESSING)
        is_completed = status == DownloadTask.Status.COMPLETED
        is_incomplete = status in (DownloadTask.Status.STOPPED, DownloadTask.Status.ERROR)
        is_pending = status == DownloadTask.Status.PENDING

        self.stop_button.setVisible(is_active)
        self.play_button.setVisible(is_completed)
        self.download_button.setVisible(is_pending or is_incomplete)
        self.sniff_browser_button.setVisible(status == DownloadTask.Status.ERROR)
        self.timerange_button.setVisible(False)
        self.folder_button.setVisible(is_completed)
        self.more_button.setVisible(True)
        self.move_up_button.setVisible(is_pending)
        self.move_down_button.setVisible(is_pending)
        self.btn_copy_url.setVisible(not is_incomplete)
        self.badge_quality.setEnabled(not is_incomplete and not is_active)

        raw_err = self.task.error_message or ""
        clean_err = re.sub(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?(?:\x07|\x1b\\)', '', raw_err)
        clean_err = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean_err)
        clean_err = re.sub(r'^(?:Ошибка загрузчика:\s*)+(?:ERROR:\s*)+', '', clean_err, flags=re.IGNORECASE).strip()

        err_prefix = self.translator.translate('status_error', 'Ошибка')
        err_display = clean_err if clean_err.lower().startswith(err_prefix.lower()) else f"{err_prefix}: {clean_err}"

        status_text_map = {
            DownloadTask.Status.PENDING: self.translator.translate('status_pending', 'Ожидание...'),
            DownloadTask.Status.FETCHING_INFO: self.translator.translate('status_fetching_info', 'Получение данных...'),
            DownloadTask.Status.DOWNLOADING: self.translator.translate('status_downloading', 'Скачивание...'),
            DownloadTask.Status.PROCESSING: self.translator.translate('status_processing', 'Обработка...'),
            DownloadTask.Status.COMPLETED: self.translator.translate('status_completed', 'Скачано'),
            DownloadTask.Status.ERROR: err_display,
            DownloadTask.Status.STOPPED: self.translator.translate('status_stopped', 'Стрим завершен и сохранен'),
        }

        base_text = status_text_map.get(status, "")

        if self.is_stream_active():
            base_text = self.translator.translate('status_recording', 'Идет запись потока...')

        self.status_label.setText(base_text)
        self.setProperty('status', status.value)
        self.style().polish(self)
        if hasattr(self.task, 'list_item') and self.task.list_item:
            self.task.list_item.setSizeHint(self.sizeHint())

    def get_available_qualities_with_sizes(self) -> list:
        info = getattr(self.task, 'info', None)
        if not info or not isinstance(info, dict):
            info = {}

        formats = info.get('formats', [])
        duration = info.get('duration', 0)
        curr_sz = getattr(self.task, 'file_size', 0) or 0

        # 1. Check for available_streams (e.g. Voidboost / KinoPub / Rezka)
        av_streams = getattr(self.task, 'available_streams', None) or info.get('available_streams')
        if av_streams and isinstance(av_streams, dict):
            curr_badge = (getattr(self.task, 'quality_badge', '') or getattr(self.task, 'custom_quality', '') or '720p').replace(' ▾', '').strip()
            curr_h_m = re.search(r'(\d+)', curr_badge)
            curr_h = int(curr_h_m.group(1)) if curr_h_m else 720

            results = []
            for label, s_url in av_streams.items():
                m_label = re.search(r'(\d+)', label)
                h = int(m_label.group(1)) if m_label else 720
                is_ultra = 'ultra' in label.lower()
                res_score = h * 10 + (5 if is_ultra else 0)

                est_sz = int(curr_sz * ((h / curr_h) ** 1.3)) if (curr_sz > 0 and curr_h > 0) else 0

                desc = label
                if is_ultra:
                    desc = f"{h}p Ultra"
                elif h >= 2160:
                    desc = "2160p (4K)"
                elif h >= 1440:
                    desc = "1440p (2K)"
                elif h >= 1080:
                    desc = "1080p (Full HD)"
                elif h >= 720:
                    desc = "720p (HD)"
                elif h >= 480:
                    desc = "480p (SD)"
                elif h >= 360:
                    desc = "360p (SD)"

                results.append({
                    'key': label,
                    'badge': label,
                    'label': desc,
                    'size_bytes': est_sz,
                    'is_audio': False,
                    'direct_url': s_url,
                    '_score': res_score
                })

            results.sort(key=lambda x: x['_score'], reverse=True)

            mp3_size = int((320 * 1000 / 8) * duration) if duration else (int(curr_sz * 0.15) if curr_sz > 0 else 0)
            results.append({
                'key': 'audio_mp3',
                'badge': 'MP3',
                'label': 'MP3 (320 kbps)',
                'size_bytes': mp3_size,
                'is_audio': True
            })
            return results

        # 2. Best audio format
        best_audio = None
        for f in formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                if not best_audio or (f.get('abr') or 0) > (best_audio.get('abr') or 0):
                    best_audio = f

        audio_size = 0
        if best_audio:
            audio_size = best_audio.get('filesize') or best_audio.get('filesize_approx') or 0
            if not audio_size and duration and best_audio.get('abr'):
                audio_size = int((best_audio['abr'] * 1000 / 8) * duration)

        # 3. Group formats by height
        by_height = {}
        for f in formats:
            h = f.get('height')
            if not h:
                continue
            if f.get('ext') in ('mhtml', 'sb3') or f.get('format_note') == 'storyboard':
                continue
            if h not in by_height:
                by_height[h] = f
            else:
                old_val = by_height[h].get('filesize') or by_height[h].get('tbr') or 0
                new_val = f.get('filesize') or f.get('tbr') or 0
                if new_val > old_val:
                    by_height[h] = f

        # If by_height has <= 1 resolution, expand with standard resolutions so user is never trapped
        if len(by_height) <= 1:
            base_h = list(by_height.keys())[0] if by_height else 720
            base_sz = curr_sz
            if by_height and base_h in by_height:
                base_sz = by_height[base_h].get('filesize') or by_height[base_h].get('filesize_approx') or curr_sz

            is_kodik = any(d in self.task.url for d in ('solodcdn', 'kodik')) and re.search(r'/\d{3,4}\.mp4', self.task.url)
            for alt_h in (1080, 720, 480, 360):
                if alt_h not in by_height:
                    approx_sz = int(base_sz * ((alt_h / base_h) ** 1.3)) if (base_sz > 0 and base_h > 0) else 0
                    direct_u = re.sub(r'/\d{3,4}\.mp4', f'/{alt_h}.mp4', self.task.url) if is_kodik else None
                    by_height[alt_h] = {
                        'format_id': f"{alt_h}p",
                        'height': alt_h,
                        'filesize_approx': approx_sz,
                        'url': direct_u
                    }

        results = []
        if by_height:
            for h in sorted(by_height.keys(), reverse=True):
                vf = by_height[h]
                v_size = vf.get('filesize') or vf.get('filesize_approx') or 0
                if not v_size and duration and (vf.get('tbr') or vf.get('vbr')):
                    bitrate = vf.get('tbr') or vf.get('vbr')
                    v_size = int((bitrate * 1000 / 8) * duration)

                total_size = v_size + (audio_size if vf.get('acodec') == 'none' else 0)

                label = f"{h}p"
                if h >= 2160:
                    label = "2160p (4K)"
                elif h >= 1440:
                    label = "1440p (2K)"
                elif h >= 1080:
                    label = "1080p (Full HD)"
                elif h >= 720:
                    label = "720p (HD)"
                elif h >= 480:
                    label = "480p (SD)"
                elif h >= 360:
                    label = "360p (SD)"

                results.append({
                    'key': f"{h}p",
                    'badge': f"{h}p",
                    'label': label,
                    'size_bytes': total_size,
                    'is_audio': False,
                })
        elif info.get('available_qualities'):
            for q in info.get('available_qualities', []):
                results.append({
                    'key': q,
                    'badge': q,
                    'label': q,
                    'size_bytes': 0,
                    'is_audio': False
                })

        # Add MP3 option
        mp3_size = audio_size
        if not mp3_size and duration:
            mp3_size = int((320 * 1000 / 8) * duration)
        elif not mp3_size and curr_sz:
            mp3_size = int(curr_sz * 0.15)

        results.append({
            'key': 'audio_mp3',
            'badge': 'MP3',
            'label': 'MP3 (320 kbps)',
            'size_bytes': mp3_size,
            'is_audio': True
        })

        return results

    def show_quality_selection_menu(self):
        items = self.get_available_qualities_with_sizes()
        if not items:
            return

        menu = RoundMenu(parent=self)
        curr_badge = getattr(self.task, 'quality_badge', '').replace(' ▾', '').strip().lower()
        curr_override = getattr(self.task, 'quality_override', '') or ''

        for it in items:
            sz_str = ""
            if it.get('size_bytes', 0) > 0:
                b = float(it['size_bytes'])
                for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                    if b < 1024.0:
                        sz_str = f"{b:.1f} {unit}"
                        break
                    b /= 1024.0

            label_text = f"{it['label']} ({sz_str})" if sz_str else it['label']
            action = Action(label_text, self)

            is_active = (curr_badge and curr_badge == it['badge'].lower()) or (curr_override and curr_override == it['key'])
            if is_active:
                action.setIcon(FluentIcon.ACCEPT)

            action.triggered.connect(lambda _chk, item=it: self.apply_quality_selection(item))
            menu.addAction(action)

        menu.exec(self.badge_quality.mapToGlobal(self.badge_quality.rect().bottomLeft()))

    def apply_quality_selection(self, it: dict):
        curr_badge = getattr(self.task, 'quality_badge', '').replace(' ▾', '').strip().lower()
        curr_override = str(getattr(self.task, 'quality_override', '') or '').lower()
        is_same = (curr_badge and curr_badge == it['badge'].lower()) or (curr_override and curr_override == str(it['key']).lower())
        if self.task.status == DownloadTask.Status.COMPLETED and is_same:
            return

        downloaded_map = getattr(self.task, 'downloaded_files', None)
        if downloaded_map is None:
            downloaded_map = {}
            self.task.downloaded_files = downloaded_map

        if self.task.status == DownloadTask.Status.COMPLETED and self.task.final_filepath:
            if curr_badge:
                downloaded_map[curr_badge] = self.task.final_filepath
            if curr_override:
                downloaded_map[curr_override] = self.task.final_filepath

        self.task.quality_override = it['key']
        self.task.quality_badge = it['badge']
        self.task.custom_quality = it['badge']
        orig_u = (getattr(self.task, 'original_url', '') or self.task.url).lower()
        is_web_media = any(d in orig_u for d in ('twitch.tv', 'youtube.com', 'youtu.be', 'kick.com', 'rutube.ru', 'vk.com', 'tiktok.com', 'instagram.com'))
        if it.get('direct_url') and not is_web_media:
            self.task.url = it['direct_url']
        elif getattr(self.task, 'available_streams', None) and it['badge'] in self.task.available_streams:
            self.task.url = self.task.available_streams[it['badge']]
        elif StreamResolverHelper.is_kodik_stream(self.task.url):
            self.task.url = StreamResolverHelper.replace_quality(
                self.task.url, it['badge'], is_audio=bool(it.get('is_audio'))
            )

        if it.get('is_audio'):
            self.task.audio_only = True
        else:
            self.task.audio_only = False

        # Проверяем, не был ли этот вариант качества уже скачан ранее
        target_badge_key = it['badge'].replace(' ▾', '').strip().lower()
        target_ov_key = str(it['key']).lower()
        saved_path = downloaded_map.get(target_badge_key) or downloaded_map.get(target_ov_key)
        if saved_path and os.path.exists(saved_path):
            self.task.error_message = ""
            self.task.set_completed(saved_path)
            self.update_ui()
            return

        sz_bytes = it.get('size_bytes', 0)
        if sz_bytes > 0:
            self.task.set_file_size(sz_bytes)

        # If task was COMPLETED, reset to PENDING so user can immediately download in new quality
        if self.task.status == DownloadTask.Status.COMPLETED:
            self.task.set_status(DownloadTask.Status.PENDING)
            self.task.progress = 0
            self.task.progress_text = ""
            self.task.error_message = ""
            self.task.final_filepath = ""

        self.update_ui()

    def sizeHint(self):
        base_h = super().sizeHint().height()
        return QSize(800, max(105, base_h))