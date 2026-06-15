import os
import logging
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMenu
from PyQt6.QtGui import QPixmap, QIcon, QAction
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from .download_task import DownloadTask

logger = logging.getLogger(__name__)


class DownloadItemWidget(QWidget):
    remove_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    open_file_requested = pyqtSignal()  # <--- НОВЫЙ СИГНАЛ ДЛЯ ОТКРЫТИЯ ФАЙЛА
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
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(128, 72)
        self.thumbnail_label.setObjectName('Thumbnail')
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setText("...")
        main_layout.addWidget(self.thumbnail_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)

        self.title_label = QLabel(self.task.title)
        self.title_label.setObjectName('TitleLabel')
        self.title_label.setWordWrap(True)

        self.url_label = QLabel(self.task.url)
        self.url_label.setObjectName('UrlLabel')
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setObjectName('ItemProgressBar')

        status_layout = QHBoxLayout()

        self.status_label = QLabel()
        self.status_label.setObjectName('StatusLabelItem')

        self.size_label = QLabel()
        self.size_label.setObjectName('SizeLabelItem')
        self.size_label.setStyleSheet("color: #007acc; font-weight: bold; font-size: 13px;")
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.size_label)

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.url_label)
        info_layout.addWidget(self.progress_bar)
        info_layout.addLayout(status_layout)

        main_layout.addLayout(info_layout, 1)

        self.remove_button = QPushButton()
        self.remove_button.setFixedSize(24, 24)
        self.remove_button.setIconSize(QSize(14, 14))
        self.remove_button.setObjectName('RemoveButton')
        self.remove_button.setToolTip(self.translator.translate('status_stopped'))

        close_icon_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'icons', 'close.svg')
        if os.path.exists(close_icon_path):
            icon = QIcon(close_icon_path)
            if not icon.isNull():
                self.remove_button.setIcon(icon)
            else:
                logger.warning(f"Не удалось загрузить иконку: {close_icon_path}")
                self.remove_button.setText('X')
        else:
            logger.warning(f"Файл иконки не найден: {close_icon_path}")
            self.remove_button.setText('X')

        main_layout.addWidget(self.remove_button)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        act_start = QAction(self.translator.translate('download_this_video'), self)

        # --- НОВАЯ КНОПКА В МЕНЮ ---
        act_open_file = QAction(self.translator.translate('open_file', 'Открыть видео'), self)

        act_open = QAction(self.translator.translate('open_save_folder'), self)
        act_copy = QAction(self.translator.translate('copy_link'), self)
        act_remove = QAction(self.translator.translate('remove_from_list'), self)

        act_start.triggered.connect(self.start_or_retry_requested.emit)
        act_open_file.triggered.connect(self.open_file_requested.emit)  # <--- ПОДКЛЮЧАЕМ
        act_open.triggered.connect(self.open_folder_requested.emit)
        act_copy.triggered.connect(self.copy_link_requested.emit)
        act_remove.triggered.connect(self.remove_requested.emit)

        is_startable = self.task.status in (
            DownloadTask.Status.PENDING, DownloadTask.Status.ERROR, DownloadTask.Status.STOPPED)
        act_start.setEnabled(is_startable)

        is_completed = self.task.status == DownloadTask.Status.COMPLETED
        act_open_file.setEnabled(is_completed)  # <--- АКТИВНО ТОЛЬКО ЕСЛИ СКАЧАНО
        act_open.setEnabled(is_completed)

        menu.addAction(act_start)
        menu.addAction(act_open_file)  # <--- ДОБАВЛЯЕМ В МЕНЮ
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
        self.remove_button.clicked.connect(self.remove_requested.emit)

    def on_size_update(self, size_str):
        self.size_label.setText(size_str)

    def on_progress_update(self, percent, text):
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

        status_text_map = {
            DownloadTask.Status.PENDING: self.translator.translate('status_pending'),
            DownloadTask.Status.FETCHING_INFO: self.translator.translate('status_fetching_info'),
            DownloadTask.Status.DOWNLOADING: self.translator.translate('status_downloading'),
            DownloadTask.Status.PROCESSING: self.translator.translate('status_processing'),
            DownloadTask.Status.COMPLETED: f"{self.translator.translate('status_completed')} ✓",
            DownloadTask.Status.ERROR: f"{self.translator.translate('status_error')}: {self.task.error_message}",
            DownloadTask.Status.STOPPED: self.translator.translate('status_stopped'),
        }
        self.status_label.setText(status_text_map.get(status, ""))

        self.setProperty('status', status.value)
        self.style().polish(self)