import sys
import os
import subprocess
import logging
import json
from qfluentwidgets import (LineEdit, TransparentToolButton, PrimaryPushButton,
                            PushButton, SubtitleLabel, BodyLabel, CaptionLabel,
                            FluentIcon, setTheme, Theme)
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QProgressBar, QLabel,
                             QFileDialog, QMessageBox, QComboBox,
                             QListWidget, QListWidgetItem, QStackedWidget,
                             QToolButton, QFrame, QApplication, QDialog,
                             QSystemTrayIcon, QMenu)
from PyQt6.QtCore import Qt, QSettings, QSize, QThreadPool, QUrl, QTimer
from PyQt6.QtGui import QFont, QIcon, QDropEvent, QMovie, QDesktopServices, QAction
from PyQt6.QtGui import QFont, QIcon, QDropEvent, QMovie, QDesktopServices

from .settings_tab import SettingsTab
from .about_tab import AboutTab
from .history_tab import HistoryTab
from .download_item_widget import DownloadItemWidget
from .download_manager import DownloadManager
from .translation import Translator
from .theme_manager import ThemeManager
from .flow_layout import FlowLayout
from .update_checker import UpdateChecker
from .files_tab import FilesTab
from .telegram_bot import TelegramBotManager
from .telegram_tab import TelegramTab
logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, translator: Translator, settings: QSettings):
        super().__init__()
        self.translator = translator
        self.settings = settings
        self.ffmpeg_path = self.check_ffmpeg()
        self.thread_pool = QThreadPool()
        parallel_downloads = int(self.settings.value('parallel_downloads', 2))
        self.thread_pool.setMaxThreadCount(max(parallel_downloads + 6, 8))
        self.download_manager = DownloadManager(self.settings, self.ffmpeg_path, self.thread_pool, self.translator)
        self.update_checker = UpdateChecker(self, self.translator, self.settings, self.thread_pool)
        self.bot_manager = TelegramBotManager(self.settings)
        self.bot_manager.signals.url_received.connect(self._on_bot_url_received)

        # --- ЗАЩИТА ОТ КРИВОГО ТОКЕНА ---
        saved_token = self.settings.value('tg_bot_token', '')
        if saved_token:
            try:
                self.bot_manager.start_bot(saved_token)
            except Exception as e:
                logger.error(f"Ошибка запуска бота (кривой токен): {e}")
                self.settings.remove('tg_bot_token')  # Удаляем сломанный токен из памяти
        # --------------------------------
        self.initUI()
        self.connect_signals()
        self.setAcceptDrops(True)
        self.translator.language_changed.connect(self.update_translations)

        QTimer.singleShot(500, self._check_first_launch)
        QTimer.singleShot(1000, self._startup_checks)

    def check_ffmpeg(self):
        project_root = os.path.dirname(os.path.abspath(__file__))
        ffmpeg_folder = os.path.join(project_root, '..', 'assets', 'ffmpeg', 'bin')
        ffmpeg_executable = os.path.join(ffmpeg_folder, 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
        if not os.path.exists(ffmpeg_executable):
            QMessageBox.critical(self,
                                 self.translator.translate('error'),
                                 f"{self.translator.translate('ffmpeg_not_found')}: {ffmpeg_executable}")
            sys.exit(1)
        try:
            subprocess.run([ffmpeg_executable, '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return ffmpeg_executable
        except Exception as e:
            QMessageBox.critical(self,
                                 self.translator.translate('error'),
                                 f"{self.translator.translate('ffmpeg_run_error')}\n{str(e)}")
            sys.exit(1)

    def initUI(self):
        self.setObjectName('MainWindow')
        self.setWindowTitle(self.translator.translate('app_title'))
        self.resize(1200, 800)

        current_theme = self.settings.value('theme', 'dark')
        setTheme(Theme.DARK if current_theme == 'dark' else Theme.LIGHT)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setObjectName('TopBar')
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(15, 10, 15, 10)

        self.url_input = LineEdit()
        self.url_input.setObjectName('UrlInput')
        self.url_input.setMinimumHeight(35)
        self.url_input.setPlaceholderText(self.translator.translate('enter_link_and_press_add'))
        self.url_input.setClearButtonEnabled(True)

        self.btn_add = TransparentToolButton(FluentIcon.ADD)
        self.btn_add.setFixedSize(35, 35)
        self.btn_add.setToolTip(self.translator.translate('add_link'))

        self.btn_file = TransparentToolButton(FluentIcon.FOLDER)
        self.btn_file.setFixedSize(35, 35)
        self.btn_file.setToolTip(self.translator.translate('load_from_file'))

        self.btn_notes = TransparentToolButton(FluentIcon.EDIT)
        self.btn_notes.setFixedSize(35, 35)
        self.btn_notes.setToolTip(self.translator.translate('notes', 'Примечания'))

        top_bar_layout.addWidget(self.url_input)
        top_bar_layout.addWidget(self.btn_add)
        top_bar_layout.addWidget(self.btn_file)
        top_bar_layout.addWidget(self.btn_notes)
        main_layout.addWidget(top_bar)


        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.nav_bar = QWidget()
        self.nav_bar.setObjectName('NavBar')
        nav_layout = QVBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(10, 20, 10, 10)
        nav_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.btn_downloads = QPushButton(self.translator.translate('loader_tab_title'))
        self.btn_downloads.setIcon(FluentIcon.DOWNLOAD.icon())
        self.btn_downloads.setObjectName('NavButton')

        self.btn_history = QPushButton(self.translator.translate('history', 'History'))
        self.btn_history.setIcon(FluentIcon.HISTORY.icon())
        self.btn_history.setObjectName('NavButton')

        self.btn_files = QPushButton(self.translator.translate('files_tab', 'Файлы'))
        self.btn_files.setIcon(FluentIcon.FOLDER.icon())
        self.btn_files.setObjectName('NavButton')

        self.btn_settings = QPushButton(self.translator.translate('settings'))
        self.btn_settings.setIcon(FluentIcon.SETTING.icon())
        self.btn_settings.setObjectName('NavButton')

        self.btn_about = QPushButton(self.translator.translate('about'))
        self.btn_about.setIcon(FluentIcon.INFO.icon())
        self.btn_about.setObjectName('NavButton')

        self.btn_telegram = QPushButton(self.translator.translate('tg_tab_title', 'Telegram Бот'))
        self.btn_telegram.setIcon(FluentIcon.MESSAGE.icon())
        self.btn_telegram.setObjectName('NavButton')
        self.btn_telegram.setFixedSize(160, 40)
        self.btn_telegram.setStyleSheet("text-align: left; padding-left: 15px;")
        for btn in [self.btn_downloads, self.btn_history, self.btn_files, self.btn_settings, self.btn_about]:
            btn.setFixedSize(160, 40)
            btn.setStyleSheet("text-align: left; padding-left: 15px;")

        nav_layout.addWidget(self.btn_downloads)
        nav_layout.addWidget(self.btn_history)
        nav_layout.addWidget(self.btn_files)
        nav_layout.addWidget(self.btn_telegram)
        nav_layout.addWidget(self.btn_settings)
        nav_layout.addWidget(self.btn_about)
        nav_layout.addStretch()

        self.language_combo = QComboBox()
        self.language_combo.setObjectName('LanguageCombo')
        self.language_combo.addItems(['English', 'Русский', 'Українська'])
        saved_language = self.settings.value('language', 'ru')
        language_map = {'en': 0, 'ru': 1, 'uk': 2}
        self.language_combo.setCurrentIndex(language_map.get(saved_language, 1))
        nav_layout.addWidget(self.language_combo)

        self.quick_theme_combo = QComboBox()
        self.quick_theme_combo.addItems(['Dark', 'Light'])
        theme = self.settings.value('theme', 'dark')
        self.quick_theme_combo.setCurrentIndex(0 if theme == 'dark' else 1)
        nav_layout.addWidget(self.quick_theme_combo)

        self.page_stack = QStackedWidget()
        self.downloads_page_stack = QStackedWidget()

        self.downloads_list = QListWidget()
        self.downloads_list.setObjectName('DownloadsList')
        self.downloads_list.setSpacing(5)

        self.empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_card = QFrame()
        empty_card.setObjectName('EmptyCard')
        empty_card.setMinimumWidth(550)
        card_layout = QVBoxLayout(empty_card)
        card_layout.setContentsMargins(30, 30, 30, 30)
        card_layout.setSpacing(15)

        title_row = QHBoxLayout()
        title_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.rocket_label = QLabel()
        self.rocket_label.setObjectName('RocketEmoji')
        rocket_gif = os.path.join(os.path.dirname(__file__), '..', 'assets', 'animations', 'rocket.gif')
        if os.path.exists(rocket_gif):
            self.rocket_movie = QMovie(rocket_gif)
            self.rocket_label.setMovie(self.rocket_movie)
            self.rocket_label.setFixedSize(32, 32)
            self.rocket_movie.start()
        else:
            self.rocket_label.setText('🚀')
            self.rocket_label.setStyleSheet("font-size: 24px;")

        self.empty_title = SubtitleLabel(
            self.translator.translate('no_downloads_placeholder', 'Add links to start downloading'))
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title_row.addWidget(self.rocket_label)
        title_row.addSpacing(10)
        title_row.addWidget(self.empty_title)

        bullets_layout = QVBoxLayout()
        bullets_layout.setContentsMargins(0, 5, 0, 5)
        bullets_layout.setSpacing(8)
        bullets_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.empty_b1 = BodyLabel(
            '• ' + self.translator.translate('empty_tip_dragdrop', 'Drag & drop links or .txt file here'))
        self.empty_b2 = BodyLabel('• ' + self.translator.translate('empty_tip_paste', 'Paste from clipboard'))
        self.empty_b3 = BodyLabel(
            '• ' + self.translator.translate('empty_tip_support', 'Supported: YouTube, TikTok, Instagram, VK, RuTube…'))
        for l in (self.empty_b1, self.empty_b2, self.empty_b3):
            l.setStyleSheet("color: #888888;")
            bullets_layout.addWidget(l)

        self.quick_actions = QWidget()
        self.quick_actions.setObjectName('QuickActions')
        qa_layout = QHBoxLayout(self.quick_actions)
        qa_layout.setContentsMargins(0, 15, 0, 0)
        qa_layout.setSpacing(12)
        qa_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.btn_paste = PushButton(self.translator.translate('paste_from_clipboard', 'Paste'))
        self.btn_paste.setIcon(FluentIcon.PASTE.icon())
        self.btn_import = PushButton(self.translator.translate('load_from_file'))
        self.btn_import.setIcon(FluentIcon.FOLDER.icon())
        self.btn_quality = PushButton(self.translator.translate('open_quality_settings', 'Quality settings'))
        self.btn_quality.setIcon(FluentIcon.SETTING.icon())

        qa_layout.addWidget(self.btn_paste)
        qa_layout.addWidget(self.btn_import)
        qa_layout.addWidget(self.btn_quality)

        self.recent_container = QWidget()
        rc_layout = QVBoxLayout(self.recent_container)
        rc_layout.setContentsMargins(0, 15, 0, 0)
        rc_layout.setSpacing(10)
        recent_label_layout = QHBoxLayout()
        self.recent_label = BodyLabel(self.translator.translate('recent', 'Recent') + ':')

        self.btn_clear_recent = TransparentToolButton(FluentIcon.DELETE)
        self.btn_clear_recent.setFixedSize(32, 32)
        self.btn_clear_recent.setToolTip(self.translator.translate('clear_history'))

        recent_label_layout.addWidget(self.recent_label)
        recent_label_layout.addStretch(1)
        recent_label_layout.addWidget(self.btn_clear_recent)

        rc_layout.addLayout(recent_label_layout)
        self.recent_buttons_layout = FlowLayout(h_spacing=8, v_spacing=8)
        rc_layout.addLayout(self.recent_buttons_layout)

        self.hint_label = CaptionLabel(self.translator.translate('empty_hint', "Press Enter or ➕ to add"))
        self.hint_label.setStyleSheet("color: #666666;")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        card_layout.addLayout(title_row)
        card_layout.addLayout(bullets_layout)
        card_layout.addWidget(self.quick_actions)
        card_layout.addWidget(self.recent_container)
        card_layout.addSpacing(10)
        card_layout.addWidget(self.hint_label)

        empty_layout.addWidget(empty_card, 0, Qt.AlignmentFlag.AlignCenter)

        self.downloads_page_stack.addWidget(self.empty_widget)
        self.downloads_page_stack.addWidget(self.downloads_list)

        self.settings_page = SettingsTab(self.translator, self)
        self.history_page = HistoryTab(self.translator, self)
        self.files_page = FilesTab(self.translator, self)
        self.telegram_page = TelegramTab(self.translator, self.bot_manager, self.settings, self)  # <---
        self.about_page = AboutTab(self.translator, self)

        self.page_stack.addWidget(self.downloads_page_stack)  # 0
        self.page_stack.addWidget(self.history_page)  # 1
        self.page_stack.addWidget(self.files_page)  # 2
        self.page_stack.addWidget(self.telegram_page)  # 3 <---
        self.page_stack.addWidget(self.settings_page)  # 4
        self.page_stack.addWidget(self.about_page)  # 5

        self.update_placeholder_visibility()
        self._rebuild_recent_buttons()

        content_layout.addWidget(self.nav_bar)
        content_layout.addWidget(self.page_stack, 1)
        main_layout.addLayout(content_layout)

        bottom_bar = QWidget()
        bottom_bar.setObjectName('BottomBar')
        bottom_bar_layout = QHBoxLayout(bottom_bar)
        bottom_bar_layout.setContentsMargins(15, 5, 15, 5)

        self.download_button = QPushButton(self.translator.translate('download_all'))
        self.download_button.setIcon(FluentIcon.DOWNLOAD.icon())
        self.download_button.setObjectName('ActionButton')

        self.threads_label = QLabel("")
        self.threads_label.setObjectName('StatusLabel')

        self.stop_button = QPushButton(self.translator.translate('stop'))
        self.stop_button.setIcon(FluentIcon.PAUSE.icon())
        self.stop_button.setObjectName('SecondaryButton')
        self.stop_button.setEnabled(False)

        self.clear_button = QPushButton(self.translator.translate('clear_completed'))
        self.clear_button.setIcon(FluentIcon.DELETE.icon())
        self.clear_button.setObjectName('SecondaryButton')

        self.btn_open_save = TransparentToolButton(FluentIcon.FOLDER)
        self.btn_open_save.setFixedSize(36, 36)
        self.btn_open_save.setToolTip(self.translator.translate('open_save_folder'))

        self.btn_open_logs = TransparentToolButton(FluentIcon.DOCUMENT)
        self.btn_open_logs.setFixedSize(36, 36)
        self.btn_open_logs.setToolTip(self.translator.translate('open_logs'))

        self.summary_info = QLabel("")
        self.summary_info.setObjectName('StatusLabel')

        self.status_label = QLabel(self.translator.translate('waiting'))
        self.status_label.setObjectName('StatusLabel')

        bottom_bar_layout.addWidget(self.download_button)
        bottom_bar_layout.addWidget(self.stop_button)
        bottom_bar_layout.addWidget(self.clear_button)
        bottom_bar_layout.addWidget(self.threads_label)
        bottom_bar_layout.addWidget(self.btn_open_save)
        bottom_bar_layout.addWidget(self.btn_open_logs)
        bottom_bar_layout.addStretch()
        bottom_bar_layout.addWidget(self.summary_info)
        bottom_bar_layout.addSpacing(10)
        bottom_bar_layout.addWidget(self.status_label)

        main_layout.addWidget(bottom_bar)

        self.init_tray()


    def connect_signals(self):
        self.btn_add.clicked.connect(self.on_add_link)
        self.url_input.returnPressed.connect(self.on_add_link)
        self.btn_file.clicked.connect(self.on_load_from_file)
        self.btn_notes.clicked.connect(self.on_notes_clicked)
        self.language_combo.currentIndexChanged.connect(self.on_language_change)
        self.quick_theme_combo.currentIndexChanged.connect(self.on_quick_theme_change)
        self.download_button.clicked.connect(self.download_manager.start_all)
        self.stop_button.clicked.connect(self.download_manager.stop_all)
        self.clear_button.clicked.connect(self.clear_completed_items)
        self.btn_paste.clicked.connect(self.on_paste_from_clipboard)
        self.btn_import.clicked.connect(self.on_load_from_file)

        self.btn_downloads.clicked.connect(lambda: self.page_stack.setCurrentIndex(0))
        self.btn_history.clicked.connect(lambda: self.page_stack.setCurrentIndex(1))
        self.btn_files.clicked.connect(self._show_files_tab)  # 2
        self.btn_telegram.clicked.connect(lambda: self.page_stack.setCurrentIndex(3))  # 3
        self.btn_settings.clicked.connect(lambda: self.page_stack.setCurrentIndex(4))  # 4
        self.btn_about.clicked.connect(lambda: self.page_stack.setCurrentIndex(5))  # 5


        self.history_page.redownload_requested.connect(self._redownload_from_history)
        self.btn_open_save.clicked.connect(self.open_save_folder)
        self.btn_open_logs.clicked.connect(self.open_logs_folder)
        self.btn_clear_recent.clicked.connect(self._clear_recent_history)

        self.download_manager.task_added.connect(self.add_download_item_widget)
        self.download_manager.download_started.connect(self.on_download_started)
        self.download_manager.all_downloads_finished.connect(self.on_all_downloads_finished)
        self.download_manager.status_updated.connect(lambda msg: self.status_label.setText(msg))
        self.download_manager.summary_updated.connect(self.on_summary_update)
        self.download_manager.active_threads_changed.connect(self.on_threads_update)

    def update_translations(self):
        self.setWindowTitle(self.translator.translate('app_title'))
        self.url_input.setPlaceholderText(self.translator.translate('enter_link_and_press_add'))
        self.download_button.setText(self.translator.translate('download_all'))
        self.stop_button.setText(self.translator.translate('stop'))
        self.clear_button.setText(self.translator.translate('clear_completed'))
        self.status_label.setText(self.translator.translate('waiting'))
        self.btn_downloads.setText(self.translator.translate('loader_tab_title'))
        self.btn_settings.setText(self.translator.translate('settings'))
        self.btn_history.setText(self.translator.translate('history', 'History'))
        self.btn_files.setText(self.translator.translate('files_tab', 'Файлы'))
        self.btn_about.setText(self.translator.translate('about'))
        self.btn_telegram.setText(self.translator.translate('tg_tab_title', 'Telegram Бот'))

        self.btn_add.setToolTip(self.translator.translate('add_link'))
        self.btn_file.setToolTip(self.translator.translate('load_from_file'))
        self.btn_notes.setToolTip(self.translator.translate('notes', 'Примечания'))
        self.empty_title.setText(
            self.translator.translate('no_downloads_placeholder', 'Add links to start downloading'))
        self.empty_b1.setText(
            '• ' + self.translator.translate('empty_tip_dragdrop', 'Drag & drop links or .txt file here'))
        self.empty_b2.setText('• ' + self.translator.translate('empty_tip_paste', 'Paste from clipboard'))
        self.empty_b3.setText(
            '• ' + self.translator.translate('empty_tip_support', 'Supported: YouTube, TikTok, Instagram, VK, RuTube…'))
        self.btn_paste.setText(self.translator.translate('paste_from_clipboard', 'Paste'))
        self.btn_import.setText(self.translator.translate('load_from_file'))
        self.btn_quality.setText(self.translator.translate('open_quality_settings', 'Quality settings'))
        self.hint_label.setText(self.translator.translate('empty_hint', "Press Enter or ➕ to add"))
        self.btn_open_save.setToolTip(self.translator.translate('open_save_folder'))
        self.btn_open_logs.setToolTip(self.translator.translate('open_logs'))
        self.recent_label.setText(self.translator.translate('recent', 'Recent') + ':')
        self.btn_clear_recent.setToolTip(self.translator.translate('clear_history'))

        self.language_combo.blockSignals(True)
        self.language_combo.setItemText(0, 'English')
        self.language_combo.setItemText(1, 'Русский')
        self.language_combo.setItemText(2, 'Українська')
        self.language_combo.blockSignals(False)
        self.settings_page.update_translations()
        self.history_page.update_translations()
        self.about_page.update_translations()

        if hasattr(self, 'files_page') and hasattr(self.files_page, 'update_translations'):
            self.files_page.update_translations()

        if hasattr(self, 'telegram_page') and hasattr(self.telegram_page, 'update_translations'):
            self.telegram_page.update_translations()

    def on_language_change(self, index):
        language_map = {0: 'en', 1: 'ru', 2: 'uk'}
        selected_lang = language_map.get(index, 'ru')
        self.translator.set_language(selected_lang)
        self.settings.setValue('language', selected_lang)
        self.settings.sync()
        self._rebuild_recent_buttons()

    def on_quick_theme_change(self, idx):
        theme = 'dark' if idx == 0 else 'light'
        self.settings.setValue('theme', theme)
        self.settings.sync()
        ThemeManager(self.settings).apply_theme()

    def _on_bot_url_received(self, url):
        """Обработчик ссылок, присланных из Telegram бота"""
        # Создаем список ожидания, если его еще нет
        if not hasattr(self, '_bot_pending_urls'):
            self._bot_pending_urls = []

        self._bot_pending_urls.append(url)  # Запоминаем, что ссылка от бота

        self.download_manager.add_urls([url])
        self._add_recent(url)
        self._rebuild_recent_buttons()

    def on_add_link(self):
        url = self.url_input.text().strip()
        if url:
            self.url_input.clear()
            if 'list=' in url or '/playlist' in url:
                self.status_label.setText("Анализ плейлиста...")
                from .threads import PlaylistCheckWorker
                worker = PlaylistCheckWorker(url)
                worker.signals.info_fetched.connect(lambda info: self._handle_link_info(info, url))
                worker.signals.error.connect(lambda err: self._handle_link_error(err, url))
                self.thread_pool.start(worker)

            else:
                self.status_label.setText(self.translator.translate('waiting'))
                self.download_manager.add_urls([url])
                self._add_recent(url)
                self._rebuild_recent_buttons()
        else:
            QMessageBox.warning(self, self.translator.translate('warning'), self.translator.translate('enter_link'))

    def _handle_link_info(self, info, original_url):
        self.status_label.setText(self.translator.translate('waiting'))

        if info and info.get('_type') == 'playlist':
            raw_entries = info.get('entries')
            if raw_entries is not None:
                entries = [e for e in list(raw_entries) if e is not None]

                if len(entries) > 0:
                    from .playlist_dialog import PlaylistDialog
                    dialog = PlaylistDialog(entries, self)
                    if dialog.exec():
                        urls_to_add = dialog.selected_urls
                        if urls_to_add:
                            self.download_manager.add_urls(urls_to_add)
                            self._add_recent(original_url)
                            self._rebuild_recent_buttons()
                    return

        self.download_manager.add_urls([original_url])
        self._add_recent(original_url)
        self._rebuild_recent_buttons()

    def _handle_link_error(self, err, original_url):
        self.status_label.setText(self.translator.translate('waiting'))
        self.download_manager.add_urls([original_url])
        self._add_recent(original_url)
        self._rebuild_recent_buttons()

    def on_paste_from_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        parts = [p.strip() for p in text.replace('\r', '\n').split('\n')]
        urls = [p for p in parts if p]
        if urls:
            self.download_manager.add_urls(urls)
            for u in urls:
                self._add_recent(u)
            self._rebuild_recent_buttons()

    def on_load_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.translate('load_from_file'), '',
                                                   'Text Files (*.txt);;All Files (*)')
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    urls = [line.strip() for line in f if line.strip()]
                if not urls:
                    QMessageBox.warning(self, self.translator.translate('warning'),
                                        self.translator.translate('file_empty_or_invalid'))
                    return
                self.download_manager.add_urls(urls)
                for u in urls:
                    self._add_recent(u)
                self._rebuild_recent_buttons()
            except Exception as e:
                logger.error(f'Error reading file {file_path}: {e}')
                QMessageBox.critical(self, self.translator.translate('error'),
                                     f"{self.translator.translate('error_reading_file')}: {e}")

    def update_placeholder_visibility(self):
        if self.downloads_list.count() > 0:
            self.downloads_page_stack.setCurrentWidget(self.downloads_list)
        else:
            self.downloads_page_stack.setCurrentWidget(self.empty_widget)

    def add_download_item_widget(self, task):
        item_widget = DownloadItemWidget(task, self.translator)
        task.is_from_bot = getattr(self, '_is_adding_from_bot', False)
        list_item = QListWidgetItem(self.downloads_list)
        list_item.setSizeHint(item_widget.sizeHint())
        self.downloads_list.addItem(list_item)
        self.downloads_list.setItemWidget(list_item, item_widget)
        task.list_item = list_item
        item_widget.remove_requested.connect(lambda: self.remove_download_item(task))
        item_widget.open_folder_requested.connect(self.open_save_folder)

        item_widget.open_file_requested.connect(lambda: self.open_downloaded_file(task))

        item_widget.copy_link_requested.connect(lambda: QApplication.clipboard().setText(task.url))
        item_widget.start_or_retry_requested.connect(lambda: self.download_manager.start_or_retry_task(task))

        task.status_changed.connect(lambda status, t=task: self._on_task_status_changed(t, status))
        self.update_placeholder_visibility()

    def remove_download_item(self, task):
        self.download_manager.remove_task(task)
        if task.list_item:
            row = self.downloads_list.row(task.list_item)
            self.downloads_list.takeItem(row)
        self.update_placeholder_visibility()

    def clear_completed_items(self):
        tasks_to_remove = self.download_manager.get_completed_tasks()
        for task in tasks_to_remove:
            self.remove_download_item(task)
        self.status_label.setText(self.translator.translate('completed_cleared'))
        self.update_placeholder_visibility()

    def on_download_started(self):
        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.clear_button.setEnabled(False)

    def on_all_downloads_finished(self):
        self.download_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)
        self.status_label.setText(self.translator.translate('downloads_completed'))

    def on_summary_update(self, text):
        self.summary_info.setText(text)

    def on_threads_update(self, active, maxc):
        if maxc <= 0:
            self.threads_label.setText("")
        else:
            self.threads_label.setText(f"{active}/{maxc}")

    def open_save_folder(self):
        folder = self.settings.value('save_path', '')
        if not folder or not os.path.isdir(folder):
            folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self._open_path(folder)

    def open_logs_folder(self):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        folder = os.path.join(project_root, 'logs')
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        self._open_path(folder)

    def _open_path(self, path):
        if sys.platform.startswith('win'):
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])

    def open_downloaded_file(self, task):
        actual_path = task.final_filepath

        if not actual_path or not os.path.exists(actual_path):
            actual_path = task.current_filename

        if actual_path and os.path.exists(actual_path):
            self._open_path(actual_path)
        else:
            QMessageBox.warning(self, self.translator.translate('warning', 'Внимание'),
                                self.translator.translate('file_not_found',
                                                          'Файл не найден! Возможно, он еще конвертируется или был удален.'))

    def _check_first_launch(self):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        data_dir = os.path.join(project_root, 'data')
        os.makedirs(data_dir, exist_ok=True)
        counter_file = os.path.join(data_dir, 'launch_count.json')

        launch_count = 0
        if os.path.exists(counter_file):
            try:
                with open(counter_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    launch_count = data.get('count', 0)
            except Exception as e:
                logger.error(f"Error reading launch count: {e}")

        if launch_count == 0:
            self.on_notes_clicked()

        launch_count += 1
        try:
            with open(counter_file, 'w', encoding='utf-8') as f:
                json.dump({'count': launch_count}, f)
        except Exception as e:
            logger.error(f"Error saving launch count: {e}")

    def on_notes_clicked(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel
        from PyQt6.QtCore import QTimer, Qt

        dialog = QDialog(self)
        dialog.setWindowTitle(self.translator.translate('notes', 'Примечания'))

        dialog.resize(450, 150)
        dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        layout = QVBoxLayout(dialog)

        lang = self.settings.value('language', 'ru')
        if lang == 'en':
            warning_text = "⚠️ <b>Note:</b> For KinoPub, you must first play the video in your browser for 5 seconds, and only then copy the link to download!"
            close_btn_text = "Understood / Close"
        elif lang == 'uk':
            warning_text = "⚠️ <b>Увага:</b> На KinoPub потрібно спочатку запустити відео в браузері на 5 секунд, і тільки потім копіювати посилання для завантаження!"
            close_btn_text = "Зрозуміло / Закрити"
        else:
            warning_text = "⚠️ <b>Внимание:</b> На KinoPub нужно сначала запустить видео в браузере на 5 секунд, и только потом копировать ссылку для скачивания!"
            close_btn_text = "Понятно / Закрыть"

        warning_label = QLabel(warning_text)
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("color: #ff9800; font-size: 15px; margin-bottom: 15px;")
        layout.addWidget(warning_label)

        close_btn = QPushButton(f"{close_btn_text} (5)")
        close_btn.setObjectName('ActionButton')
        close_btn.setFixedHeight(40)
        close_btn.setEnabled(False)
        layout.addWidget(close_btn)

        time_left = [5]

        def update_timer():
            time_left[0] -= 1
            if time_left[0] > 0:
                close_btn.setText(f"{close_btn_text} ({time_left[0]})")
            else:
                timer.stop()
                close_btn.setText(close_btn_text)
                close_btn.setEnabled(True)

        timer = QTimer(dialog)
        timer.timeout.connect(update_timer)
        timer.start(1000)

        def on_close():
            dialog.accept()

        close_btn.clicked.connect(on_close)

        dialog.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls_to_add = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                file_path = url.toLocalFile()
                if file_path.lower().endswith('.txt'):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            urls_to_add.extend([line.strip() for line in f if line.strip()])
                    except Exception as e:
                        logger.error(f'Error reading dropped file {file_path}: {e}')
            else:
                urls_to_add.append(url.toString())
        if urls_to_add:
            self.download_manager.add_urls(urls_to_add)
            for u in urls_to_add:
                self._add_recent(u)
            self._rebuild_recent_buttons()

    def closeEvent(self, event):
        close_to_tray = self.settings.value('close_to_tray', True, type=bool)

        if close_to_tray:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                self.translator.translate('app_title', 'Universal Media Downloader'),
                "Программа свернута в трей и продолжает работу",
                QSystemTrayIcon.MessageIcon.Information,
            )
        else:
            self.quit_app()

    def _get_recent(self):
        raw = self.settings.value('recent_urls', '')
        items = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, str) and raw:
            try:
                if raw.strip().startswith('['):
                    items = json.loads(raw)
                else:
                    items = [p for p in raw.split('|') if p]
            except Exception:
                items = []
        return items[:5]

    def _add_recent(self, url):
        items = [u for u in self._get_recent() if u != url]
        items.insert(0, url)
        items = items[:5]
        self.settings.setValue('recent_urls', '|'.join(items))
        self.settings.sync()

    def _rebuild_recent_buttons(self):
        while self.recent_buttons_layout.count():
            item = self.recent_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        recent = self._get_recent()
        if not recent:
            self.recent_container.setVisible(False)
            return
        self.recent_container.setVisible(True)
        for url in recent:
            max_len = 60
            text = url if len(url) <= max_len else f"{url[:max_len - 3]}..."
            b = QPushButton(text)
            b.setObjectName('SecondaryButton')
            b.setToolTip(url)
            b.clicked.connect(lambda _, u=url: self._add_recent_and_queue(u))
            self.recent_buttons_layout.addWidget(b)

    def _add_recent_and_queue(self, url):
        self.download_manager.add_urls([url])
        self._add_recent(url)
        self._rebuild_recent_buttons()

    def _clear_recent_history(self):
        self.settings.remove('recent_urls')
        self.settings.sync()
        self._rebuild_recent_buttons()

    def _startup_checks(self):
        if not self.update_checker.check_deno_installed():
            self.update_checker.show_deno_warning()

        self.update_checker.check_for_updates(silent=True)

    def _redownload_from_history(self, url):
        self.download_manager.add_urls([url])
        self._add_recent(url)
        self._rebuild_recent_buttons()
        self.page_stack.setCurrentIndex(0)

    def _save_to_history(self, task):
        self.history_page.add_to_history(
            url=task.url,
            title=task.title,
            platform=task.platform,
            status=task.status.value,
            file_path=task.final_filepath
        )

    def _on_bot_url_received(self, url):
        """Обработчик ссылок, присланных из Telegram бота"""
        self._is_adding_from_bot = True  # Ставим железный флаг
        self.download_manager.add_urls([url])
        self._is_adding_from_bot = False  # Снимаем флаг

        self._add_recent(url)
        self._rebuild_recent_buttons()

        if self.isHidden() and hasattr(self, 'tray_icon'):
            self.tray_icon.showMessage(
                "Ссылка от бота",
                f"Получена ссылка, начинаю анализ:\n{url}",
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )

    def _show_files_tab(self):
        self.files_page.load_files()
        self.page_stack.setCurrentIndex(2)

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        icon_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'icon.png')
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            icon_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'icons', 'download.svg')
            self.tray_icon.setIcon(QIcon(icon_path))

        tray_menu = QMenu()

        show_action = QAction("Показать / Скрыть", self)
        show_action.triggered.connect(self.toggle_window)

        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()

    def toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_window()

    def quit_app(self):
        self.download_manager.stop_all()
        self.thread_pool.waitForDone()
        self.settings.sync()
        QApplication.quit()

    def _on_task_status_changed(self, task, status):
        from .download_task import DownloadTask

        # 1. Данные получены -> Автоматически начинаем скачивать
        if status == DownloadTask.Status.PENDING:
            if getattr(task, 'is_from_bot', False):
                if hasattr(self, 'bot_manager'):
                    self.bot_manager.send_message(f"🔄 Данные получены! Начинаю скачивание:\n{task.title}")
                self.download_manager.start_or_retry_task(task)

        # 2. Произошла ошибка -> Пишем в Телеграм
        elif status == DownloadTask.Status.ERROR:
            if getattr(task, 'is_from_bot', False) and hasattr(self, 'bot_manager'):
                self.bot_manager.send_message(
                    f"❌ Ошибка скачивания:\n{task.title or task.url}\nПричина: {task.error_message}")
            self._save_to_history(task)

        # 3. Скачивание завершено -> Радуем пользователя
        elif status == DownloadTask.Status.COMPLETED:
            if getattr(task, 'is_from_bot', False) and hasattr(self, 'bot_manager'):
                self.bot_manager.send_message(f"✅ Успешно скачано на ПК:\n{task.title}")
            self._save_to_history(task)

        # 4. Остановлено вручную
        elif status == DownloadTask.Status.STOPPED:
            self._save_to_history(task)