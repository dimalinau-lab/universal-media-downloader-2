import os
import logging
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QMenu, QMessageBox
from PyQt6.QtGui import QPixmap, QAction, QIcon
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from qfluentwidgets import TransparentToolButton, FluentIcon, ProgressBar, StrongBodyLabel, BodyLabel, CaptionLabel
from .download_task import DownloadTask


logger = logging.getLogger(__name__)


class DownloadItemWidget(QWidget):
    remove_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    open_file_requested = pyqtSignal()
    copy_link_requested = pyqtSignal()
    start_or_retry_requested = pyqtSignal()

    def __init__(self, task: DownloadTask, translator):
        super().__init__()
        self.task = task
        self.translator = translator
        self.setObjectName('DownloadItem')
        self.initUI()
        self.connect_signals()
        self.update_ui()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(15)

        # Увеличили миниатюру до формата 16:9
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(144, 81)
        self.thumbnail_label.setObjectName('Thumbnail')
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("background-color: #2b2b2b; border-radius: 8px;")
        main_layout.addWidget(self.thumbnail_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        # Жирный и красивый шрифт для заголовка
        self.title_label = StrongBodyLabel(self.task.title)
        self.title_label.setObjectName('TitleLabel')
        self.title_label.setWordWrap(True)

        # Уменьшенный, приглушенный шрифт для ссылки
        self.url_label = CaptionLabel(self.task.url)
        self.url_label.setObjectName('UrlLabel')
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url_label.setStyleSheet("color: #888888;")

        # Тонкий и плавный прогресс-бар Windows 11
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setValue(0)

        status_layout = QHBoxLayout()

        self.status_label = BodyLabel()
        self.status_label.setObjectName('StatusLabelItem')

        self.size_label = StrongBodyLabel()
        self.size_label.setObjectName('SizeLabelItem')
        self.size_label.setStyleSheet("color: #007acc;")
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.size_label)

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.url_label)
        info_layout.addSpacing(4)
        info_layout.addWidget(self.progress_bar)
        info_layout.addLayout(status_layout)
        info_layout.addStretch()

        main_layout.addLayout(info_layout, 1)

        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(6)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.play_button = TransparentToolButton(FluentIcon.PLAY)
        self.play_button.setFixedSize(34, 34)
        self.play_button.setToolTip(self.translator.translate('play_video', 'Смотреть видео'))
        self.play_button.clicked.connect(self.open_file_requested.emit)

        self.download_button = TransparentToolButton(FluentIcon.DOWNLOAD)
        self.download_button.setFixedSize(34, 34)
        self.download_button.setToolTip("Скачать файл / Возобновить")
        self.download_button.clicked.connect(self.on_start_clicked)

        self.stop_button = TransparentToolButton(FluentIcon.PAUSE)
        self.stop_button.setFixedSize(34, 34)
        self.stop_button.setToolTip("Завершить стрим и СОБРАТЬ видео")
        self.stop_button.clicked.connect(self.task.request_stop)

        self.folder_button = TransparentToolButton(FluentIcon.FOLDER)
        self.folder_button.setFixedSize(34, 34)
        self.folder_button.setToolTip(self.translator.translate('show_in_folder', 'Показать в папке'))
        self.folder_button.clicked.connect(self.open_folder_requested.emit)

        self.remove_button = TransparentToolButton(FluentIcon.DELETE)
        self.remove_button.setFixedSize(34, 34)
        self.remove_button.setToolTip(self.translator.translate('remove_from_list', 'Убрать из списка'))
        self.remove_button.clicked.connect(self.remove_requested.emit)

        buttons_layout.addWidget(self.play_button)
        buttons_layout.addWidget(self.download_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.folder_button)
        buttons_layout.addWidget(self.remove_button)

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

    def show_context_menu(self, pos):
        menu = QMenu(self)
        act_open_file = QAction(self.translator.translate('open_file', 'Смотреть видео'), self)
        act_start = QAction("Скачать / Возобновить", self)
        act_open = QAction(self.translator.translate('open_save_folder', 'Открыть папку'), self)
        act_copy = QAction(self.translator.translate('copy_link', 'Копировать ссылку'), self)
        act_remove = QAction(self.translator.translate('remove_from_list', 'Убрать из списка'), self)

        act_open_file.triggered.connect(self.open_file_requested.emit)
        act_start.triggered.connect(self.on_start_clicked)
        act_open.triggered.connect(self.open_folder_requested.emit)
        act_copy.triggered.connect(self.copy_link_requested.emit)
        act_remove.triggered.connect(self.remove_requested.emit)

        is_startable = self.task.status in (
            DownloadTask.Status.PENDING, DownloadTask.Status.ERROR, DownloadTask.Status.STOPPED,
            DownloadTask.Status.COMPLETED)
        act_start.setEnabled(is_startable)

        is_watchable = self.task.status in (DownloadTask.Status.COMPLETED, DownloadTask.Status.STOPPED)
        act_open_file.setEnabled(is_watchable)
        act_open.setEnabled(True)

        menu.addAction(act_open_file)
        menu.addAction(act_start)
        menu.addAction(act_open)
        menu.addAction(act_copy)
        menu.addSeparator()
        menu.addAction(act_remove)
        menu.exec(self.mapToGlobal(pos))

    def connect_signals(self):
        self.task.info_updated.connect(self.update_ui)
        self.task.status_changed.connect(self.update_ui)
        self.task.progress_updated.connect(self.on_progress_update)
        self.task.thumbnail_loaded.connect(self.set_thumbnail)
        self.task.size_updated.connect(self.on_size_update)

    def on_size_update(self, size_str):
        self.size_label.setText(size_str)

    def on_progress_update(self, percent, text):
        if percent == 0 and "🔴" in text:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)
        self.status_label.setText(text)

    def set_thumbnail(self, pixmap):
        scaled_pixmap = pixmap.scaled(self.thumbnail_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        self.thumbnail_label.setPixmap(scaled_pixmap)

    def update_ui(self):
        self.title_label.setText(self.task.title)
        self.size_label.setText(self.task.file_size_str)

        status = self.task.status
        self.progress_bar.setVisible(
            status == DownloadTask.Status.DOWNLOADING or status == DownloadTask.Status.PROCESSING)

        is_active = status in (DownloadTask.Status.FETCHING_INFO, DownloadTask.Status.DOWNLOADING,
                               DownloadTask.Status.PROCESSING)
        is_stopped = status == DownloadTask.Status.STOPPED
        is_completed = status == DownloadTask.Status.COMPLETED
        is_pending_or_err = status in (DownloadTask.Status.PENDING, DownloadTask.Status.ERROR)

        self.stop_button.setVisible(is_active)
        self.play_button.setVisible(is_completed or is_stopped)
        self.download_button.setVisible(is_pending_or_err or is_stopped or is_completed)
        self.folder_button.setVisible(True)

        status_text_map = {
            DownloadTask.Status.PENDING: self.translator.translate('status_pending', 'Ожидание...'),
            DownloadTask.Status.FETCHING_INFO: self.translator.translate('status_fetching_info', 'Получение данных...'),
            DownloadTask.Status.DOWNLOADING: self.translator.translate('status_downloading', 'Скачивание...'),
            DownloadTask.Status.PROCESSING: self.translator.translate('status_processing', 'Обработка...'),
            DownloadTask.Status.COMPLETED: f"{self.translator.translate('status_completed', 'Скачано')} ✓",
            DownloadTask.Status.ERROR: f"{self.translator.translate('status_error', 'Ошибка')}: {self.task.error_message}",
            DownloadTask.Status.STOPPED: "Стрим завершен и сохранен ✓",
        }

        base_text = status_text_map.get(status, "")

        if self.is_stream_active():
            base_text = "🔴 Идет запись..."

        self.status_label.setText(base_text)
        self.setProperty('status', status.value)
        self.style().polish(self)