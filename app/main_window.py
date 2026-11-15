import sys
import os
import re
import datetime
import subprocess
import logging
import json
import shutil
from qfluentwidgets import (LineEdit, TransparentToolButton, PrimaryPushButton,
                            PushButton, TransparentToggleToolButton, SubtitleLabel, BodyLabel, CaptionLabel,
                            StrongBodyLabel, FluentIcon, setTheme, Theme, SearchLineEdit,
                            TransparentPushButton, RoundMenu, Action, ComboBox, IconWidget)
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel,
                             QFileDialog, QMessageBox, QComboBox,
                             QListWidget, QListWidgetItem, QStackedWidget,
                             QFrame, QApplication, QDialog,
                             QSystemTrayIcon, QMenu, QButtonGroup)
from PyQt6.QtCore import Qt, QSettings, QThreadPool, QTimer, QSize
from PyQt6.QtGui import (QIcon, QDropEvent, QMovie, QAction,
                         QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent,
                         QShortcut, QKeySequence)

from .download_item_widget import DownloadItemWidget
from .download_manager import DownloadManager
from .translation import Translator
from .theme_manager import ThemeManager
from .flow_layout import FlowLayout
from .update_checker import UpdateChecker
from .telegram_bot import TelegramBotManager
from .__version__ import __version__ as APP_VERSION
logger = logging.getLogger(__name__)


class CountdownShutdownDialog(QDialog):
    def __init__(self, action: str, translator, parent=None):
        super().__init__(parent)
        self.action = action
        self.translator = translator
        self.remaining_seconds = 30
        self.cancelled = False
        self.setWindowTitle(
            "Автовыключение ПК" if action == "shutdown" else ("Переход в спящий режим" if action == "sleep" else "Завершение работы")
        )
        self.setFixedSize(420, 190)
        self.initUI()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start(1000)

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        action_name = "выключится" if self.action == "shutdown" else "перейдет в спящий режим"
        self.lbl_title = StrongBodyLabel("Все загрузки в очереди завершены!")
        self.lbl_msg = BodyLabel(f"Компьютер {action_name} через {self.remaining_seconds} сек.")
        self.lbl_msg.setStyleSheet("color: #ffa726; font-size: 14px; font-weight: bold;")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_msg)
        layout.addStretch()

        btn_box = QHBoxLayout()
        self.btn_cancel = PrimaryPushButton("Отменить действие")
        self.btn_cancel.clicked.connect(self.on_cancel)
        self.btn_now = PushButton("Выполнить сейчас")
        self.btn_now.clicked.connect(self.accept)

        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(self.btn_now)
        layout.addLayout(btn_box)

    def _on_tick(self):
        self.remaining_seconds -= 1
        action_name = "выключится" if self.action == "shutdown" else "перейдет в спящий режим"
        self.lbl_msg.setText(f"Компьютер {action_name} через {self.remaining_seconds} сек.")
        if self.remaining_seconds <= 0:
            self.timer.stop()
            self.accept()

    def on_cancel(self):
        self.cancelled = True
        self.timer.stop()
        self.reject()


class DragOverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("""
            QWidget#DragOverlay {
                background-color: rgba(18, 24, 38, 0.92);
                border: 3px dashed #0078d4;
                border-radius: 14px;
            }
        """)
        self.setObjectName("DragOverlay")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon = IconWidget(FluentIcon.FOLDER_ADD)
        icon.setFixedSize(54, 54)

        lbl_title = SubtitleLabel("Отпустите ссылки или .txt файлы здесь")
        lbl_title.setStyleSheet("font-size: 19px; font-weight: bold; color: #ffffff;")

        lbl_sub = CaptionLabel("Ссылки будут проверены и добавлены в очередь загрузки")
        lbl_sub.setStyleSheet("font-size: 13px; color: #60cdff;")

        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_sub, 0, Qt.AlignmentFlag.AlignCenter)
        self.hide()


class MainWindow(QMainWindow):
    def __init__(self, translator: Translator, settings: QSettings):
        super().__init__()
        self.translator = translator
        self.settings = settings
        self.ffmpeg_path = self.check_ffmpeg()
        self.ffprobe_path = self.check_ffprobe()
        self._schedule = {'active': False}
        self._schedule_timer = QTimer(self)
        self._schedule_timer.timeout.connect(self._check_schedule_tick)

        self.thread_pool = QThreadPool()
        parallel_downloads = int(self.settings.value('parallel_downloads', 2))
        self.thread_pool.setMaxThreadCount(max(parallel_downloads + 6, 8))
        self.download_manager = DownloadManager(self.settings, self.ffmpeg_path, self.thread_pool, self.translator, parent=self)
        self.update_checker = UpdateChecker(self, self.translator, self.settings, self.thread_pool)
        self.bot_manager = TelegramBotManager(self.settings)
        self.download_manager.bot_manager = self.bot_manager
        self.bot_manager.signals.url_received.connect(self._on_bot_url_received)

        self.current_filter_mode = 'all'

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
        self.update_theme_icons()
        self.setAcceptDrops(True)
        self.translator.language_changed.connect(self.update_translations)

        self.clipboard = QApplication.clipboard()
        self._last_clipboard_url = ""
        self.clipboard.dataChanged.connect(self._on_clipboard_changed)

        QTimer.singleShot(500, self._check_first_launch)
        QTimer.singleShot(1000, self._startup_checks)

    def check_ffprobe(self):
        if hasattr(self, 'ffmpeg_path') and self.ffmpeg_path:
            probe_cand = os.path.join(os.path.dirname(self.ffmpeg_path), 'ffprobe.exe' if os.name == 'nt' else 'ffprobe')
            if os.path.exists(probe_cand):
                return probe_cand
        return shutil.which('ffprobe')

    def check_ffmpeg(self):
        project_root = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(project_root, '..', 'assets', 'ffmpeg', 'bin', 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'),
            os.path.join(project_root, 'assets', 'ffmpeg', 'bin', 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'),
        ]
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
            candidates.insert(0, os.path.join(base_dir, 'assets', 'ffmpeg', 'bin', 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'))
            candidates.insert(1, os.path.join(base_dir, 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'))
            if hasattr(sys, '_MEIPASS'):
                candidates.insert(0, os.path.join(sys._MEIPASS, 'assets', 'ffmpeg', 'bin', 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'))

        system_ffmpeg = shutil.which('ffmpeg')
        if system_ffmpeg:
            candidates.append(system_ffmpeg)

        ffmpeg_executable = None
        for c in candidates:
            if c and os.path.exists(c):
                ffmpeg_executable = os.path.abspath(c)
                break

        if not ffmpeg_executable:
            QMessageBox.critical(self,
                                 self.translator.translate('error'),
                                 f"{self.translator.translate('ffmpeg_not_found')}")
            sys.exit(1)
        cached_verified = self.settings.value('verified_ffmpeg_path', '')
        if cached_verified == ffmpeg_executable and os.path.isfile(ffmpeg_executable):
            return ffmpeg_executable

        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run([ffmpeg_executable, '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, creationflags=flags)
            self.settings.setValue('verified_ffmpeg_path', ffmpeg_executable)
            return ffmpeg_executable
        except Exception as e:
            QMessageBox.critical(self,
                                 self.translator.translate('error'),
                                 f"{self.translator.translate('ffmpeg_run_error')}\n{str(e)}")
            sys.exit(1)

    def initUI(self):
        self.setObjectName('MainWindow')
        self.setWindowTitle(self.translator.translate('app_title'))

        # Адаптивный размер и позиционирование под экран (включая Full HD ноутбуки с масштабом 100%, 125%, 150%)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            # На ноутбуках FHD (1920x1080) при 125% (1536x864) или 150% (1280x720)
            # высота рабочего стола за вычетом панели задач ~640-810px
            w = min(1160, int(avail.width() * 0.90))
            h = min(720, int(avail.height() * 0.88))
            self.resize(max(920, w), max(560, h))

            # Центрируем окно на экране
            geo = self.frameGeometry()
            geo.moveCenter(avail.center())
            self.move(geo.topLeft())
        else:
            self.resize(1080, 680)

        self.setMinimumSize(940, 520)

        current_theme = self.settings.value('theme', 'dark')
        setTheme(Theme.DARK if current_theme == 'dark' else Theme.LIGHT)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.drag_overlay = DragOverlayWidget(central_widget)
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

        self.btn_timerange_mode = TransparentToggleToolButton(FluentIcon.CUT)
        self.btn_timerange_mode.setObjectName("TimerangeButton")
        self.btn_timerange_mode.setFixedSize(35, 35)
        is_tr_active = self.settings.value('timerange_mode_active', False, type=bool)
        self.btn_timerange_mode.setChecked(is_tr_active)
        self._update_timerange_btn_style(is_tr_active)
        self.btn_timerange_mode.toggled.connect(self._on_timerange_mode_toggled)

        self.btn_batch = TransparentToolButton(FluentIcon.FOLDER_ADD)
        self.btn_batch.setFixedSize(35, 35)
        self.btn_batch.setToolTip(self.translator.translate('batch_add_tooltip', 'Пакетное добавление ссылок'))
        self.btn_batch.clicked.connect(self.open_batch_dialog)

        self.btn_file = TransparentToolButton(FluentIcon.FOLDER)
        self.btn_file.setFixedSize(35, 35)
        self.btn_file.setToolTip(self.translator.translate('load_from_file'))

        self.btn_notes = TransparentToolButton(FluentIcon.EDIT)
        self.btn_notes.setFixedSize(35, 35)
        self.btn_notes.setToolTip(self.translator.translate('notes', 'Примечания'))

        top_bar_layout.addWidget(self.url_input)
        top_bar_layout.addWidget(self.btn_add)
        top_bar_layout.addWidget(self.btn_timerange_mode)
        top_bar_layout.addWidget(self.btn_batch)
        top_bar_layout.addWidget(self.btn_file)
        top_bar_layout.addWidget(self.btn_notes)
        main_layout.addWidget(top_bar)


        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.nav_bar = QWidget()
        self.nav_bar.setObjectName('NavBar')
        self.nav_bar.setFixedWidth(180)
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
            title_row.addWidget(self.rocket_label)
        else:
            self.empty_icon = IconWidget(FluentIcon.DOWNLOAD)
            self.empty_icon.setFixedSize(32, 32)
            title_row.addWidget(self.empty_icon)

        self.empty_title = SubtitleLabel(
            self.translator.translate('no_downloads_placeholder', 'Add links to start downloading'))
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
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

        self.hint_label = CaptionLabel(self.translator.translate('empty_hint', "Press Enter or '+' button to add"))
        self.hint_label.setStyleSheet("color: #666666;")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        card_layout.addLayout(title_row)
        card_layout.addLayout(bullets_layout)
        card_layout.addWidget(self.quick_actions)
        card_layout.addWidget(self.recent_container)
        card_layout.addSpacing(10)
        card_layout.addWidget(self.hint_label)

        empty_layout.addWidget(empty_card, 0, Qt.AlignmentFlag.AlignCenter)

        # Контейнер списка загрузок с панелью фильтрации и поиска
        self.downloads_container = QWidget()
        dl_container_layout = QVBoxLayout(self.downloads_container)
        dl_container_layout.setContentsMargins(10, 8, 10, 6)
        dl_container_layout.setSpacing(8)

        self.filter_toolbar = QWidget()
        ft_layout = QHBoxLayout(self.filter_toolbar)
        ft_layout.setContentsMargins(0, 0, 0, 0)
        ft_layout.setSpacing(6)

        self.btn_filter_all = PushButton(self.translator.translate('filter_all', 'Все'))
        self.btn_filter_downloading = PushButton(self.translator.translate('filter_downloading', 'Скачиваются'))
        self.btn_filter_completed = PushButton(self.translator.translate('filter_completed', 'Завершенные'))
        self.btn_filter_errors = PushButton(self.translator.translate('filter_errors', 'Ошибки'))

        for btn in (self.btn_filter_all, self.btn_filter_downloading, self.btn_filter_completed, self.btn_filter_errors):
            btn.setFixedHeight(30)
            btn.setCheckable(True)
            ft_layout.addWidget(btn)

        self.filter_btn_group = QButtonGroup(self)
        self.filter_btn_group.addButton(self.btn_filter_all, 0)
        self.filter_btn_group.addButton(self.btn_filter_downloading, 1)
        self.filter_btn_group.addButton(self.btn_filter_completed, 2)
        self.filter_btn_group.addButton(self.btn_filter_errors, 3)
        self.btn_filter_all.setChecked(True)

        ft_layout.addStretch()

        self.platform_filter_combo = ComboBox()
        self.platform_filter_combo.setFixedHeight(30)
        self.platform_filter_combo.setMinimumWidth(165)
        self._populate_platform_filter()
        ft_layout.addWidget(self.platform_filter_combo)

        self.search_downloads_input = SearchLineEdit()
        self.search_downloads_input.setPlaceholderText(self.translator.translate('search_placeholder', 'Поиск по названию...'))
        self.search_downloads_input.setFixedWidth(230)
        self.search_downloads_input.setFixedHeight(30)
        ft_layout.addWidget(self.search_downloads_input)

        dl_container_layout.addWidget(self.filter_toolbar)
        dl_container_layout.addWidget(self.downloads_list, 1)

        self.downloads_page_stack.addWidget(self.empty_widget)
        self.downloads_page_stack.addWidget(self.downloads_container)

        self._history_page = None
        self._files_page = None
        self._telegram_page = None
        self._settings_page = None
        self._about_page = None

        self._placeholder_history = QWidget()
        self._placeholder_files = QWidget()
        self._placeholder_telegram = QWidget()
        self._placeholder_settings = QWidget()
        self._placeholder_about = QWidget()

        self.page_stack.addWidget(self.downloads_page_stack)  # 0
        self.page_stack.addWidget(self._placeholder_history)   # 1
        self.page_stack.addWidget(self._placeholder_files)     # 2
        self.page_stack.addWidget(self._placeholder_telegram)  # 3
        self.page_stack.addWidget(self._placeholder_settings)  # 4
        self.page_stack.addWidget(self._placeholder_about)     # 5

        self.update_placeholder_visibility()
        self._rebuild_recent_buttons()

        content_layout.addWidget(self.nav_bar)
        content_layout.addWidget(self.page_stack, 1)
        main_layout.addLayout(content_layout)

        bottom_bar = QWidget()
        bottom_bar.setObjectName('BottomBar')
        bottom_bar_layout = QHBoxLayout(bottom_bar)
        bottom_bar_layout.setContentsMargins(12, 6, 12, 6)
        bottom_bar_layout.setSpacing(6)

        self.download_button = PrimaryPushButton(FluentIcon.DOWNLOAD, self.translator.translate('download_all'))
        self.download_button.setFixedHeight(32)

        self.threads_label = QLabel("")
        self.threads_label.setObjectName('StatusLabel')

        self.stop_button = PushButton(FluentIcon.CANCEL_MEDIUM, self.translator.translate('stop'))
        self.stop_button.setFixedHeight(32)
        self.stop_button.setEnabled(False)

        self.clear_button = PushButton(FluentIcon.DELETE, self.translator.translate('clear_all', 'Очистить'))
        self.clear_button.setFixedHeight(32)
        self.clear_button.setToolTip(self.translator.translate('clear_completed', 'Очистить завершенные'))

        self.btn_open_save = TransparentToolButton(FluentIcon.FOLDER)
        self.btn_open_save.setFixedSize(32, 32)
        self.btn_open_save.setIconSize(QSize(16, 16))
        self.btn_open_save.setToolTip(self.translator.translate('open_save_folder'))

        self.btn_open_logs = TransparentToolButton(FluentIcon.DOCUMENT)
        self.btn_open_logs.setFixedSize(32, 32)
        self.btn_open_logs.setIconSize(QSize(16, 16))
        self.btn_open_logs.setToolTip(self.translator.translate('open_logs'))

        self.btn_quick_speed = TransparentPushButton()
        self.btn_quick_speed.setIcon(FluentIcon.SPEED_HIGH)
        self.btn_quick_speed.setIconSize(QSize(16, 16))
        self.btn_quick_speed.setFixedHeight(32)
        self.btn_quick_speed.setToolTip(self.translator.translate('speed_quick_menu', 'Лимит скорости'))

        self.btn_disk_space = TransparentPushButton()
        self.btn_disk_space.setIcon(FluentIcon.SAVE)
        self.btn_disk_space.setIconSize(QSize(16, 16))
        self.btn_disk_space.setFixedHeight(32)
        self.btn_disk_space.setToolTip(self.translator.translate('open_save_folder', 'Открыть папку загрузок'))
        self.btn_disk_space.clicked.connect(self.open_save_folder)

        self.btn_scheduler = TransparentToolButton(FluentIcon.DATE_TIME)
        self.btn_scheduler.setFixedSize(32, 32)
        self.btn_scheduler.setIconSize(QSize(16, 16))
        self.btn_scheduler.setToolTip(self.translator.translate('scheduler_tooltip', 'Планировщик загрузок (Ночной таймер)'))
        self.btn_scheduler.clicked.connect(self.show_scheduler_dialog)

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
        bottom_bar_layout.addWidget(self.btn_quick_speed)
        bottom_bar_layout.addWidget(self.btn_disk_space)
        bottom_bar_layout.addWidget(self.btn_scheduler)
        bottom_bar_layout.addStretch()
        bottom_bar_layout.addWidget(self.summary_info)
        bottom_bar_layout.addSpacing(10)
        bottom_bar_layout.addWidget(self.status_label)

        main_layout.addWidget(bottom_bar)

        self.init_tray()
        self.update_quick_speed_display()
        self.update_disk_space()

    @property
    def history_page(self):
        if self._history_page is None:
            from .history_tab import HistoryTab
            self._history_page = HistoryTab(self.translator, self)
            self._history_page.redownload_requested.connect(self._redownload_from_history)
            self._history_page.redownload_timerange_requested.connect(lambda u: self._redownload_from_history(u, force_timerange=True))
            self.page_stack.removeWidget(self._placeholder_history)
            self.page_stack.insertWidget(1, self._history_page)
        return self._history_page

    @property
    def files_page(self):
        if self._files_page is None:
            from .files_tab import FilesTab
            self._files_page = FilesTab(self.translator, self)
            self.page_stack.removeWidget(self._placeholder_files)
            self.page_stack.insertWidget(2, self._files_page)
        return self._files_page

    @property
    def telegram_page(self):
        if self._telegram_page is None:
            from .telegram_tab import TelegramTab
            self._telegram_page = TelegramTab(self.translator, self.bot_manager, self.settings, self)
            self.page_stack.removeWidget(self._placeholder_telegram)
            self.page_stack.insertWidget(3, self._telegram_page)
        return self._telegram_page

    @property
    def settings_page(self):
        if self._settings_page is None:
            from .settings_tab import SettingsTab
            self._settings_page = SettingsTab(self.translator, self)
            self.page_stack.removeWidget(self._placeholder_settings)
            self.page_stack.insertWidget(4, self._settings_page)
        return self._settings_page

    @property
    def about_page(self):
        if self._about_page is None:
            from .about_tab import AboutTab
            self._about_page = AboutTab(self.translator, self)
            self.page_stack.removeWidget(self._placeholder_about)
            self.page_stack.insertWidget(5, self._about_page)
        return self._about_page

    def _show_history_tab(self):
        _ = self.history_page
        self.page_stack.setCurrentIndex(1)

    def _show_files_tab(self):
        self.files_page.load_files()
        self.page_stack.setCurrentIndex(2)

    def _show_telegram_tab(self):
        _ = self.telegram_page
        self.page_stack.setCurrentIndex(3)

    def _show_settings_tab(self):
        _ = self.settings_page
        self.page_stack.setCurrentIndex(4)

    def _open_quality_settings(self):
        self._show_settings_tab()
        if hasattr(self.settings_page, 'scroll_to_quality_settings'):
            QTimer.singleShot(60, self.settings_page.scroll_to_quality_settings)

    def _show_about_tab(self):
        _ = self.about_page
        self.page_stack.setCurrentIndex(5)

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
        self.btn_quality.clicked.connect(self._open_quality_settings)

        self.btn_downloads.clicked.connect(lambda: self.page_stack.setCurrentIndex(0))
        self.btn_history.clicked.connect(self._show_history_tab)
        self.btn_files.clicked.connect(self._show_files_tab)
        self.btn_telegram.clicked.connect(self._show_telegram_tab)
        self.btn_settings.clicked.connect(self._show_settings_tab)
        self.btn_about.clicked.connect(self._show_about_tab)
        self.btn_open_save.clicked.connect(self.open_save_folder)
        self.btn_open_logs.clicked.connect(self.open_logs_folder)
        self.btn_clear_recent.clicked.connect(self._clear_recent_history)
        self.filter_btn_group.idClicked.connect(self.on_filter_changed)
        self.platform_filter_combo.currentIndexChanged.connect(self.apply_downloads_filter)
        self.search_downloads_input.textChanged.connect(self.apply_downloads_filter)
        self.btn_quick_speed.clicked.connect(self.show_quick_speed_menu)

        self.download_manager.task_added.connect(self.add_download_item_widget)
        self.download_manager.download_started.connect(self.on_download_started)
        self.download_manager.all_downloads_finished.connect(self.on_all_downloads_finished)
        self.download_manager.status_updated.connect(lambda msg: self.status_label.setText(msg))
        self.download_manager.summary_updated.connect(self.on_summary_update)
        self.download_manager.active_threads_changed.connect(self.on_threads_update)

        # Горячие клавиши
        self.shortcut_paste = QShortcut(QKeySequence("Ctrl+V"), self)
        self.shortcut_paste.activated.connect(self._on_hotkey_paste)
        self.shortcut_clear = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self.shortcut_clear.activated.connect(self.clear_completed_items)

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
        if hasattr(self, 'btn_batch'):
            self.btn_batch.setToolTip(self.translator.translate('batch_add_tooltip', 'Пакетное добавление ссылок'))
        self.btn_file.setToolTip(self.translator.translate('load_from_file'))
        self.btn_notes.setToolTip(self.translator.translate('notes', 'Примечания'))
        if hasattr(self, 'btn_scheduler') and not self._schedule.get('active'):
            self.btn_scheduler.setToolTip(self.translator.translate('scheduler_tooltip', 'Планировщик загрузок (Ночной таймер)'))
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
        self.hint_label.setText(self.translator.translate('empty_hint', "Press Enter or '+' button to add"))
        self.btn_open_save.setToolTip(self.translator.translate('open_save_folder'))
        self.btn_open_logs.setToolTip(self.translator.translate('open_logs'))
        self.recent_label.setText(self.translator.translate('recent', 'Recent') + ':')
        self.btn_clear_recent.setToolTip(self.translator.translate('clear_history'))

        self.btn_filter_all.setText(self.translator.translate('filter_all', 'Все'))
        self.btn_filter_downloading.setText(self.translator.translate('filter_downloading', 'Скачиваются'))
        self.btn_filter_completed.setText(self.translator.translate('filter_completed', 'Завершенные'))
        self.btn_filter_errors.setText(self.translator.translate('filter_errors', 'Ошибки'))
        self._populate_platform_filter()
        self.search_downloads_input.setPlaceholderText(self.translator.translate('search_placeholder', 'Поиск по названию...'))
        self.btn_quick_speed.setToolTip(self.translator.translate('speed_quick_menu', 'Лимит скорости'))
        self.update_quick_speed_display()
        self.update_disk_space()

        if hasattr(self, 'btn_timerange_mode'):
            self._update_timerange_btn_style(self.btn_timerange_mode.isChecked())

        self.language_combo.blockSignals(True)
        self.language_combo.setItemText(0, 'English')
        self.language_combo.setItemText(1, 'Русский')
        self.language_combo.setItemText(2, 'Українська')
        self.language_combo.blockSignals(False)
        if self._settings_page:
            self._settings_page.update_translations()
        if self._history_page:
            self._history_page.update_translations()
        if self._about_page:
            self._about_page.update_translations()
        if self._files_page and hasattr(self._files_page, 'update_translations'):
            self._files_page.update_translations()
        if self._telegram_page and hasattr(self._telegram_page, 'update_translations'):
            self._telegram_page.update_translations()

    def _update_timerange_btn_style(self, checked: bool):
        if checked:
            self.btn_timerange_mode.setToolTip(self.translator.translate('timerange_mode_active_tip', 'Режим скачивания отрезка (таймкоды): ВКЛЮЧЕН (будет запрошен отрезок)'))
        else:
            self.btn_timerange_mode.setToolTip(self.translator.translate('timerange_mode_inactive_tip', 'Режим скачивания отрезка (таймкоды): ВЫКЛЮЧЕН (нажмите, чтобы включить)'))

    def _on_timerange_mode_toggled(self, checked: bool):
        self.settings.setValue('timerange_mode_active', checked)
        self._update_timerange_btn_style(checked)

    def on_language_change(self, index):
        language_map = {0: 'en', 1: 'ru', 2: 'uk'}
        selected_lang = language_map.get(index, 'ru')
        self.translator.set_language(selected_lang)
        self.settings.setValue('language', selected_lang)
        self.settings.sync()
        self._rebuild_recent_buttons()

    def update_theme_icons(self):
        theme_str = self.settings.value('theme', 'dark')
        theme = Theme.DARK if theme_str == 'dark' else Theme.LIGHT

        # Сайдбар кнопки навигации
        if hasattr(self, 'btn_downloads'):
            self.btn_downloads.setIcon(FluentIcon.DOWNLOAD.icon(theme))
        if hasattr(self, 'btn_history'):
            self.btn_history.setIcon(FluentIcon.HISTORY.icon(theme))
        if hasattr(self, 'btn_files'):
            self.btn_files.setIcon(FluentIcon.FOLDER.icon(theme))
        if hasattr(self, 'btn_telegram'):
            self.btn_telegram.setIcon(FluentIcon.MESSAGE.icon(theme))
        if hasattr(self, 'btn_settings'):
            self.btn_settings.setIcon(FluentIcon.SETTING.icon(theme))
        if hasattr(self, 'btn_about'):
            self.btn_about.setIcon(FluentIcon.INFO.icon(theme))

        # Быстрые кнопки над списком
        if hasattr(self, 'btn_timerange_mode'):
            self.btn_timerange_mode.setIcon(FluentIcon.CUT.icon(theme))
        if hasattr(self, 'btn_paste'):
            self.btn_paste.setIcon(FluentIcon.PASTE.icon(theme))
        if hasattr(self, 'btn_import'):
            self.btn_import.setIcon(FluentIcon.FOLDER.icon(theme))
        if hasattr(self, 'btn_quality'):
            self.btn_quality.setIcon(FluentIcon.SETTING.icon(theme))

        # Нижняя панель действий
        if hasattr(self, 'download_button'):
            self.download_button.setIcon(FluentIcon.DOWNLOAD)
        if hasattr(self, 'stop_button'):
            self.stop_button.setIcon(FluentIcon.CANCEL_MEDIUM)
        if hasattr(self, 'clear_button'):
            self.clear_button.setIcon(FluentIcon.DELETE)

        # Обновление иконок страницы настроек и о программе
        if hasattr(self, '_settings_page') and self._settings_page:
            if hasattr(self._settings_page, 'update_theme_icons'):
                self._settings_page.update_theme_icons()
        if hasattr(self, '_about_page') and self._about_page:
            if hasattr(self._about_page, 'update_theme_icons'):
                self._about_page.update_theme_icons()

    def on_quick_theme_change(self, idx):
        theme = 'dark' if idx == 0 else 'light'
        self.settings.setValue('theme', theme)
        self.settings.sync()
        ThemeManager(self.settings, self).apply_theme()
        self.update_theme_icons()
        if self._settings_page and hasattr(self._settings_page, 'theme_combo'):
            self._settings_page.theme_combo.blockSignals(True)
            self._settings_page.set_combo_by_data(self._settings_page.theme_combo, theme)
            self._settings_page.theme_combo.blockSignals(False)
            if hasattr(self._settings_page, 'update_status_indicators'):
                self._settings_page.update_status_indicators()

    def on_add_link(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, self.translator.translate('warning'), self.translator.translate('enter_link'))
            return

        self.url_input.clear()
        self.page_stack.setCurrentIndex(0)

        # Проверка на вставку сразу нескольких ссылок через пробел или перенос строки
        multiple_urls = re.findall(r'https?://[^\s<>"]+', url)
        if len(multiple_urls) > 1:
            clean_urls = []
            for u in multiple_urls:
                u = u.strip().rstrip('.,;)]}>')
                if u and u not in clean_urls:
                    clean_urls.append(u)
            self.download_manager.add_urls(clean_urls)
            for u in clean_urls:
                self._add_recent(u)
            self._rebuild_recent_buttons()
            try:
                from qfluentwidgets import InfoBar, InfoBarPosition
                InfoBar.success(
                    title=self.translator.translate('batch_added_title', "Пакетное добавление"),
                    content=f"Добавлено {len(clean_urls)} ссылок в очередь загрузки.",
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
            except Exception:
                pass
            return

        if 'list=' in url or '/playlist' in url:
            self.status_label.setText("Анализ плейлиста...")
            from .threads import PlaylistCheckWorker
            worker = PlaylistCheckWorker(url)
            worker.signals.info_fetched.connect(lambda info: self._handle_link_info(info, url))
            worker.signals.error.connect(lambda err: self._handle_link_error(err, url))
            self.thread_pool.start(worker)

        else:
            self.status_label.setText(self.translator.translate('waiting'))
            prompt_tr = self.btn_timerange_mode.isChecked() if hasattr(self, 'btn_timerange_mode') else False
            self.download_manager.add_urls([url], prompt_time_range=prompt_tr)
            self._add_recent(url)
            self._rebuild_recent_buttons()

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

    def _handle_link_error(self, _err, original_url):
        self.status_label.setText(self.translator.translate('waiting'))
        self.download_manager.add_urls([original_url])
        self._add_recent(original_url)
        self._rebuild_recent_buttons()

    def _on_hotkey_paste(self):
        focus_widget = QApplication.focusWidget()
        from PyQt6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit
        if isinstance(focus_widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
            if hasattr(focus_widget, 'paste'):
                focus_widget.paste()
            return
        self.on_paste_from_clipboard()

    def on_paste_from_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        self.page_stack.setCurrentIndex(0)
        parts = [p.strip() for p in text.replace('\r', '\n').split('\n')]
        urls = [p for p in parts if p]
        if urls:
            prompt_tr = (self.btn_timerange_mode.isChecked() if hasattr(self, 'btn_timerange_mode') else False) if len(urls) == 1 else False
            self.download_manager.add_urls(urls, prompt_time_range=prompt_tr)
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

    def open_batch_dialog(self):
        from .batch_dialog import BatchAddDialog
        dialog = BatchAddDialog(self.translator, self)
        if dialog.exec() and dialog.selected_urls:
            self.page_stack.setCurrentIndex(0)
            self.download_manager.add_urls(dialog.selected_urls, quality_override=dialog.quality_override)
            for u in dialog.selected_urls:
                self._add_recent(u)
            self._rebuild_recent_buttons()
            try:
                from qfluentwidgets import InfoBar, InfoBarPosition
                InfoBar.success(
                    title=self.translator.translate('batch_added_title', "Пакетное добавление"),
                    content=f"Добавлено {len(dialog.selected_urls)} ссылок в очередь загрузки.",
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
            except Exception:
                pass

    def show_scheduler_dialog(self):
        from .scheduler_dialog import SchedulerDialog
        dialog = SchedulerDialog(self._schedule, self.translator, self)
        if dialog.exec():
            res = dialog.result_schedule
            if res and res.get('active'):
                self._schedule = res
                self._schedule_timer.start(1000)
                self._check_schedule_tick()
                try:
                    from qfluentwidgets import InfoBar, InfoBarPosition
                    InfoBar.info(
                        title=self.translator.translate('scheduler_active_title', "Таймер активен"),
                        content=f"Запуск очереди назначен на {res.get('target_time_str')}.",
                        position=InfoBarPosition.TOP,
                        duration=3500,
                        parent=self
                    )
                except Exception:
                    pass
            else:
                self._schedule = {'active': False}
                self._schedule_timer.stop()
                self.btn_scheduler.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                self.btn_scheduler.setText("")
                self.btn_scheduler.setFixedSize(32, 32)
                self.btn_scheduler.setToolTip(self.translator.translate('scheduler_tooltip', 'Планировщик загрузок (Ночной таймер)'))

    def _check_schedule_tick(self):
        if not self._schedule.get('active'):
            self._schedule_timer.stop()
            self.btn_scheduler.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btn_scheduler.setText("")
            self.btn_scheduler.setFixedSize(32, 32)
            return

        now_ts = datetime.datetime.now().timestamp()
        target_ts = self._schedule.get('target_timestamp', 0)
        remaining = int(target_ts - now_ts)

        if remaining > 0:
            h = remaining // 3600
            m = (remaining % 3600) // 60
            s = remaining % 60
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            self.btn_scheduler.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.btn_scheduler.setMinimumWidth(0)
            self.btn_scheduler.setMaximumWidth(16777215)
            self.btn_scheduler.setFixedHeight(32)
            self.btn_scheduler.setText(f" {time_str}")
            self.btn_scheduler.setToolTip(f"Автозапуск в {self._schedule.get('target_time_str')} (осталось {time_str})")
        else:
            self._schedule_timer.stop()
            self.btn_scheduler.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btn_scheduler.setText("")
            self.btn_scheduler.setFixedSize(32, 32)
            self._schedule['active'] = False

            action = self._schedule.get('action')
            if action and action != 'none':
                self.settings.setValue('on_completion_action', action)

            self.download_manager.start_all()
            if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
                self.tray_icon.showMessage(
                    "Планировщик загрузок",
                    "Начато скачивание очереди по расписанию!",
                    QSystemTrayIcon.MessageIcon.Information,
                    5000
                )
            try:
                from qfluentwidgets import InfoBar, InfoBarPosition
                InfoBar.success(
                    title="Планировщик",
                    content="Старт загрузок по расписанию!",
                    position=InfoBarPosition.TOP,
                    duration=4000,
                    parent=self
                )
            except Exception:
                pass

    def update_placeholder_visibility(self):
        target = getattr(self, 'downloads_container', self.downloads_list)
        if self.downloads_list.count() > 0:
            self.downloads_page_stack.setCurrentWidget(target)
        else:
            self.downloads_page_stack.setCurrentWidget(self.empty_widget)

    def add_download_item_widget(self, task):
        item_widget = DownloadItemWidget(task, self.translator)
        if not getattr(task, 'is_from_bot', False):
            task.is_from_bot = getattr(self, '_is_adding_from_bot', False)
        list_item = QListWidgetItem(self.downloads_list)
        list_item.setSizeHint(item_widget.sizeHint())
        self.downloads_list.addItem(list_item)
        self.downloads_list.setItemWidget(list_item, item_widget)
        task.list_item = list_item
        item_widget.remove_requested.connect(lambda: self.remove_download_item(task))
        item_widget.open_folder_requested.connect(self.open_save_folder)

        item_widget.open_file_requested.connect(lambda: self.open_downloaded_file(task))
        item_widget.media_info_requested.connect(lambda: self.open_task_media_info(task))
        item_widget.convert_audio_requested.connect(lambda: self.open_task_convert_audio(task))

        item_widget.copy_link_requested.connect(lambda: QApplication.clipboard().setText(task.url))
        item_widget.start_or_retry_requested.connect(lambda: self.download_manager.start_or_retry_task(task))

        task.status_changed.connect(lambda status, t=task: self._on_task_status_changed(t, status))
        self.update_placeholder_visibility()
        self.apply_downloads_filter()
        self.update_disk_space()

    def remove_download_item(self, task):
        self.download_manager.remove_task(task)
        if task.list_item:
            row = self.downloads_list.row(task.list_item)
            self.downloads_list.takeItem(row)
        self.update_placeholder_visibility()
        self.apply_downloads_filter()
        self.update_disk_space()

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

        action = self.settings.value('on_completion_action', 'none')
        if action == 'exit_app':
            QTimer.singleShot(1500, self.quit_app)
        elif action in ('shutdown', 'sleep'):
            dlg = CountdownShutdownDialog(action, self.translator, self)
            res = dlg.exec()
            if res == QDialog.DialogCode.Accepted and not dlg.cancelled:
                if action == 'shutdown':
                    subprocess.run(["shutdown", "/s", "/t", "0"])
                elif action == 'sleep':
                    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])

    def on_summary_update(self, text):
        self.summary_info.setText(text)

    def on_threads_update(self, active, maxc):
        if maxc <= 0:
            self.threads_label.setText("")
        else:
            threads_word = self.translator.translate('threads_prefix', 'Потоки: ')
            self.threads_label.setText(f"{threads_word}{active}/{maxc}")

    def open_save_folder(self):
        folder = self.settings.value('save_path', '')
        if not folder or not os.path.isdir(folder):
            if getattr(sys, 'frozen', False):
                folder = os.path.dirname(sys.executable)
            else:
                folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self._open_path(folder)

    def open_logs_folder(self):
        from app.path_manager import get_logs_dir
        folder = get_logs_dir()
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception:
                pass
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

    def open_task_media_info(self, task):
        actual_path = task.final_filepath or task.current_filename
        if actual_path and os.path.exists(actual_path):
            from .media_info_dialog import MediaInfoDialog
            dlg = MediaInfoDialog(actual_path, self.ffprobe_path, self.translator, self)
            dlg.exec()
        else:
            QMessageBox.warning(self, self.translator.translate('warning', 'Внимание'),
                                self.translator.translate('file_not_found', 'Файл еще не скачан или не найден.'))

    def open_task_convert_audio(self, task):
        actual_path = task.final_filepath or task.current_filename
        if actual_path and os.path.exists(actual_path):
            from .audio_convert_dialog import AudioConvertDialog
            dlg = AudioConvertDialog(actual_path, self.ffmpeg_path, self.translator, self)
            dlg.exec()
        else:
            QMessageBox.warning(self, self.translator.translate('warning', 'Внимание'),
                                self.translator.translate('file_not_found', 'Файл еще не скачан или не найден.'))

    def _check_first_launch(self):
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen' or getattr(self, '_is_quitting', False):
            return

        from app.path_manager import get_data_dir
        data_dir = get_data_dir()
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            pass
        counter_file = os.path.join(data_dir, 'launch_count.json')

        launch_count = 0
        if os.path.exists(counter_file):
            try:
                with open(counter_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    launch_count = data.get('count', 0)
            except Exception as e:
                logger.error(f"Error reading launch count: {e}")

        launch_count += 1
        try:
            with open(counter_file, 'w', encoding='utf-8') as f:
                json.dump({'count': launch_count}, f)
        except Exception as e:
            logger.error(f"Error saving launch count: {e}")

        # Проверяем, не скрыл ли пользователь окно до следующего обновления
        current_app_version = APP_VERSION
        hidden_version = self.settings.value('notes_hidden_for_version', '')
        if hidden_version == current_app_version:
            logger.info(f"Notes dialog skipped on startup (hidden for version {current_app_version})")
            return

        # Запуск окна «Примечания» при старте приложения
        self.on_notes_clicked(is_first_launch=False)

    def on_notes_clicked(self, _checked=False, is_first_launch=False):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFrame, QFileDialog
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtGui import QColor
        from qfluentwidgets import (
            LineEdit, PushButton, PrimaryPushButton, CheckBox,
            SubtitleLabel, BodyLabel, CaptionLabel, IconWidget, FluentIcon
        )

        dialog = QDialog(self)
        dialog.setObjectName("NotesDialog")
        dialog.setStyleSheet(self.styleSheet())
        dialog_title = (
            self.translator.translate('welcome_title', 'Добро пожаловать в Universal Media Downloader!')
            if is_first_launch
            else self.translator.translate('notes', 'Примечания')
        )
        dialog.setWindowTitle(dialog_title)
        dialog.setFixedWidth(660)
        dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, not is_first_launch)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        lang = self.settings.value('language', 'ru')
        if lang == 'en':
            folder_title = "Download Destination"
            folder_desc = "Select a folder on your computer where downloaded videos and audio will be saved."
            btn_choose_text = "Browse..."
            not_set_text = "Folder not selected yet"
            kinopub_title = "KinoPub & HDRezka"
            kinopub_desc = "Selecting video quality, audio track, and seasons/episodes is available directly before downloading."
            dont_show_text = "Don't show until next update"
            close_btn_text = "Understood / Close"
            settings_btn_text = "Settings"
            choose_dialog_title = "Select save folder for videos"
        elif lang == 'uk':
            folder_title = "Місце збереження завантажень"
            folder_desc = "Вкажіть папку на комп'ютері, куди зберігатимуться завантажені відео та аудіофайли."
            btn_choose_text = "Огляд..."
            not_set_text = "Папку ще не обрано"
            kinopub_title = "KinoPub та HDRezka"
            kinopub_desc = "Вибір якості, озвучки, сезонів та серій доступний безпосередньо перед початком завантаження."
            dont_show_text = "Не показувати до наступного оновлення"
            close_btn_text = "Зрозуміло / Закрити"
            settings_btn_text = "Налаштування"
            choose_dialog_title = "Оберіть папку для збереження відео"
        else:
            folder_title = "Место сохранения загрузок"
            folder_desc = "Укажите папку на компьютере, куда будут сохраняться скачанные видео и аудиофайлы."
            btn_choose_text = "Обзор..."
            not_set_text = "Папка еще не выбрана"
            kinopub_title = "KinoPub и HDRezka"
            kinopub_desc = "Выбор качества видео, озвучки, сезонов и серий доступен прямо перед началом скачивания."
            dont_show_text = "Не показывать до следующего обновления"
            close_btn_text = "Понятно / Закрыть"
            settings_btn_text = "Настройки"
            choose_dialog_title = "Выберите папку для сохранения видео"

        # Единая Bento-карточка примечаний (1-A, 3-B)
        card = QFrame()
        card.setObjectName("NotesCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)

        # Секция 1: Папка сохранения
        sec1_header = QHBoxLayout()
        sec1_header.setSpacing(8)
        sec1_icon = IconWidget(FluentIcon.FOLDER.colored(QColor('#0078d4'), QColor('#60cdff')))
        sec1_icon.setFixedSize(18, 18)
        sec1_title = SubtitleLabel(folder_title)
        f1 = sec1_title.font()
        f1.setBold(True)
        sec1_title.setFont(f1)
        sec1_header.addWidget(sec1_icon)
        sec1_header.addWidget(sec1_title)
        sec1_header.addStretch(1)
        card_layout.addLayout(sec1_header)

        sec1_desc = CaptionLabel(folder_desc)
        sec1_desc.setWordWrap(True)
        sec1_desc.setStyleSheet("color: #888888;")
        card_layout.addWidget(sec1_desc)

        # 2-A: Строка пути + кнопка «Обзор» в одну строку
        path_row = QHBoxLayout()
        path_row.setSpacing(8)

        current_save = self.settings.value('save_path', '')
        path_display = current_save if (current_save and os.path.isdir(current_save)) else ""

        path_edit = LineEdit()
        path_edit.setReadOnly(True)
        path_edit.setText(path_display)
        path_edit.setPlaceholderText(not_set_text)
        path_edit.setFixedHeight(34)
        path_row.addWidget(path_edit, 1)

        choose_btn = PushButton(FluentIcon.FOLDER, btn_choose_text)
        choose_btn.setFixedHeight(34)
        path_row.addWidget(choose_btn)

        card_layout.addLayout(path_row)

        # Разделитель между пунктами
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: rgba(128, 128, 128, 0.2); max-height: 1px; border: none;")
        card_layout.addWidget(line)

        # Секция 2: Примечание по KinoPub / HDRezka (3-B)
        sec2_layout = QHBoxLayout()
        sec2_layout.setSpacing(10)
        sec2_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        sec2_icon = IconWidget(FluentIcon.INFO.colored(QColor('#0078d4'), QColor('#60cdff')))
        sec2_icon.setFixedSize(18, 18)
        sec2_layout.addWidget(sec2_icon, 0, Qt.AlignmentFlag.AlignTop)

        sec2_box = QVBoxLayout()
        sec2_box.setSpacing(2)

        sec2_title = BodyLabel(kinopub_title)
        f2 = sec2_title.font()
        f2.setBold(True)
        sec2_title.setFont(f2)

        sec2_desc = CaptionLabel(kinopub_desc)
        sec2_desc.setWordWrap(True)
        sec2_desc.setStyleSheet("color: #888888;")

        sec2_box.addWidget(sec2_title)
        sec2_box.addWidget(sec2_desc)
        sec2_layout.addLayout(sec2_box, 1)

        card_layout.addLayout(sec2_layout)

        layout.addWidget(card)

        # Нижняя панель: чекбокс слева, кнопки справа
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        current_app_version = APP_VERSION
        hidden_version = self.settings.value('notes_hidden_for_version', '')

        dont_show_cb = CheckBox(dont_show_text)
        dont_show_cb.setChecked(hidden_version == current_app_version)
        btn_layout.addWidget(dont_show_cb)

        btn_layout.addStretch(1)

        settings_btn = PushButton(FluentIcon.SETTING, settings_btn_text)
        settings_btn.setFixedHeight(34)

        close_btn = PrimaryPushButton(f"{close_btn_text} (3)" if is_first_launch else close_btn_text)
        close_btn.setFixedHeight(34)
        if is_first_launch:
            close_btn.setEnabled(False)

        btn_layout.addWidget(settings_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        timer = None
        if is_first_launch:
            time_left = [3]

            def update_timer():
                time_left[0] -= 1
                if time_left[0] > 0:
                    close_btn.setText(f"{close_btn_text} ({time_left[0]})")
                else:
                    if timer and timer.isActive():
                        timer.stop()
                    close_btn.setText(close_btn_text)
                    close_btn.setEnabled(True)

            timer = QTimer(dialog)
            timer.timeout.connect(update_timer)
            timer.start(1000)

        def on_dialog_finished(_result=None):
            if dont_show_cb.isChecked():
                self.settings.setValue('notes_hidden_for_version', current_app_version)
            else:
                self.settings.remove('notes_hidden_for_version')
            self.settings.sync()

        dialog.finished.connect(on_dialog_finished)

        def on_choose_folder():
            initial_dir = self.settings.value('save_path', '') or os.path.expanduser('~')
            selected_folder = QFileDialog.getExistingDirectory(dialog, choose_dialog_title, initial_dir)
            if selected_folder:
                self.settings.setValue('save_path', selected_folder)
                self.settings.sync()
                if self._settings_page and hasattr(self._settings_page, 'load_settings'):
                    self._settings_page.load_settings()
                path_edit.setText(selected_folder)
                if is_first_launch and timer and timer.isActive():
                    timer.stop()
                    close_btn.setText(close_btn_text)
                    close_btn.setEnabled(True)

        def on_open_settings():
            if is_first_launch and timer and timer.isActive():
                timer.stop()
            dialog.accept()
            self._show_settings_tab()

        choose_btn.clicked.connect(on_choose_folder)
        settings_btn.clicked.connect(on_open_settings)
        close_btn.clicked.connect(dialog.accept)

        dialog.exec()

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
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, u=url, btn=b: self._show_recent_context_menu(pos, u, btn))
            self.recent_buttons_layout.addWidget(b)

    def _show_recent_context_menu(self, pos, url, btn):
        menu = QMenu(btn)
        act_download = QAction(self.translator.translate('download_this_video', 'Скачать это видео'), self)
        act_download.triggered.connect(lambda: self._add_recent_and_queue(url, force_timerange=False))
        menu.addAction(act_download)

        act_range = QAction(self.translator.translate('redownload_timerange', 'Скачать отрезок...'), self)
        act_range.triggered.connect(lambda: self._add_recent_and_queue(url, force_timerange=True))
        menu.addAction(act_range)

        menu.addSeparator()

        act_copy = QAction(self.translator.translate('copy_link', 'Скопировать ссылку'), self)
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(url))
        menu.addAction(act_copy)

        act_del = QAction(self.translator.translate('remove_from_history', 'Удалить из недавних'), self)
        act_del.triggered.connect(lambda: self._remove_single_recent(url))
        menu.addAction(act_del)

        menu.exec(btn.mapToGlobal(pos))

    def _remove_single_recent(self, url):
        items = [u for u in self._get_recent() if u != url]
        self.settings.setValue('recent_urls', '|'.join(items))
        self.settings.sync()
        self._rebuild_recent_buttons()

    def _add_recent_and_queue(self, url, force_timerange=False):
        prompt_tr = force_timerange or (self.btn_timerange_mode.isChecked() if hasattr(self, 'btn_timerange_mode') else False)
        self.download_manager.add_urls([url], prompt_time_range=prompt_tr)
        self._add_recent(url)
        self._rebuild_recent_buttons()

    def _clear_recent_history(self):
        self.settings.remove('recent_urls')
        self.settings.sync()
        self._rebuild_recent_buttons()

    def _startup_checks(self):
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen' or getattr(self, '_is_quitting', False):
            return

        if not self.update_checker.check_deno_installed():
            self.update_checker.show_deno_warning()

        self.update_checker.check_for_updates(silent=True)

    def _redownload_from_history(self, url, force_timerange=False):
        prompt_tr = force_timerange or (self.btn_timerange_mode.isChecked() if hasattr(self, 'btn_timerange_mode') else False)
        self.download_manager.add_urls([url], prompt_time_range=prompt_tr)
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
        self.download_manager.add_urls([url], is_from_bot=True)
        self._is_adding_from_bot = False  # Снимаем флаг

        self._add_recent(url)
        self._rebuild_recent_buttons()

        if self.isHidden() and hasattr(self, 'tray_icon') and self.tray_icon:
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

        resume_action = QAction("Возобновить все", self)
        resume_action.triggered.connect(self.download_manager.start_all)

        pause_action = QAction("Пауза всех загрузок", self)
        pause_action.triggered.connect(self.download_manager.stop_all)

        folder_action = QAction(self.translator.translate('open_save_folder', "Открыть папку загрузок"), self)
        folder_action.triggered.connect(self.open_save_folder)

        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(resume_action)
        tray_menu.addAction(pause_action)
        tray_menu.addAction(folder_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()

    def _on_clipboard_changed(self):
        if not self.settings.value('clipboard_monitor', False, type=bool):
            return
        try:
            text = self.clipboard.text().strip()
        except Exception:
            return
        if not text or text == self._last_clipboard_url or text == self.url_input.text().strip():
            return

        supported_domains = (
            'youtube.com', 'youtu.be', 'rutube.ru', 'tiktok.com', 'instagram.com',
            'vk.com', 'vkvideo.ru', 'twitch.tv', 'kick.com', 'twitter.com', 'x.com',
            'facebook.com', 'fb.watch', 'pornhub.com', 'rezka', 'kinopub', 'kino.pub',
            'animego.me', 'animego.org', 'bilibili.com', 'bilibili.tv',
            'pinterest.com', 'pin.it', 'rumble.com', 'streamable.com',
            'vi3000.top', 'kinopoisk.ru', 'soundcloud.com', 'vimeo.com', 'dailymotion.com'
        )
        is_media_url = text.startswith(('http://', 'https://')) and any(d in text.lower() for d in supported_domains)
        if not is_media_url:
            return

        self._last_clipboard_url = text
        self.url_input.setText(text)

        if self.isHidden():
            if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
                self.tray_icon.showMessage(
                    self.translator.translate('clipboard_detected', "Ссылка в буфере обмена"),
                    f"Найдена ссылка на видео:\n{text}",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
        else:
            try:
                from qfluentwidgets import InfoBar, InfoBarPosition
                InfoBar.info(
                    title=self.translator.translate('clipboard_detected', "Ссылка в буфере"),
                    content=self.translator.translate('clipboard_ready_tip', "Ссылка подставлена в поле ввода. Нажмите «+» или Enter."),
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
            except Exception:
                pass

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
        if hasattr(self, 'bot_manager') and self.bot_manager:
            self.bot_manager.stop_bot()
        self.download_manager.stop_all()
        # Ожидаем завершения потоков не более 2 секунд во избежание зависания процесса
        self.thread_pool.waitForDone(2000)
        self.settings.sync()
        QApplication.quit()

    def _on_task_status_changed(self, task, status):
        from .download_task import DownloadTask

        # 1. Данные получены -> Проверяем необходимость автозапуска
        if status == DownloadTask.Status.PENDING:
            if getattr(task, 'prompt_time_range', False) and not getattr(task, 'is_from_bot', False):
                task.prompt_time_range = False
                from .download_item_widget import TimeRangeDialog
                dialog = TimeRangeDialog(task, self.translator, self, is_pre_download=True)
                res = dialog.exec()
                if res == 0 and not getattr(task, 'time_range', None):
                    self.remove_download_item(task)
                    return
            if getattr(task, 'is_from_bot', False) and hasattr(self, 'bot_manager'):
                self.bot_manager.send_message(f"🔄 Данные получены! Начинаю скачивание:\n{task.title}")
                self.download_manager.start_or_retry_task(task)
            elif self.settings.value('auto_start_downloads', False, type=bool):
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
                actual_file = task.final_filepath or task.current_filename
                if actual_file and os.path.exists(actual_file):
                    self.bot_manager.send_file(actual_file, caption=f"📁 {task.title}")
            self._save_to_history(task)
            self.update_disk_space()
            if hasattr(self, 'tray_icon') and self.tray_icon and self.tray_icon.isVisible():
                title = self.translator.translate('notification_download_finished', 'Загрузка завершена')
                self.tray_icon.showMessage(
                    title,
                    task.title or "",
                    QSystemTrayIcon.MessageIcon.Information,
                    3500
                )

        # 4. Остановлено вручную
        elif status == DownloadTask.Status.STOPPED:
            self._save_to_history(task)

        self.apply_downloads_filter()

    def on_filter_changed(self, button_id):
        filter_modes = {0: 'all', 1: 'downloading', 2: 'completed', 3: 'error'}
        self.current_filter_mode = filter_modes.get(button_id, 'all')
        self.apply_downloads_filter()

    def _populate_platform_filter(self):
        curr_data = self.platform_filter_combo.currentData() if hasattr(self, 'platform_filter_combo') and self.platform_filter_combo.count() > 0 else 'all'
        self.platform_filter_combo.blockSignals(True)
        self.platform_filter_combo.clear()

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logos_dir = os.path.join(base_dir, 'assets', 'logos')

        def get_logo_icon(name):
            p = os.path.join(logos_dir, name)
            return QIcon(p) if os.path.exists(p) else None

        platforms = [
            ('all', self.translator.translate('platform_all', 'Все платформы'), FluentIcon.GLOBE),
            ('youtube', 'YouTube', get_logo_icon('youtube.png')),
            ('kinopub', 'KinoPub / Rezka', get_logo_icon('hdrezka.png')),
            ('animego', 'AnimeGo / Kodik', get_logo_icon('animego.png') or FluentIcon.PLAY),
            ('lampa', 'Lampa (vi3000)', get_logo_icon('lampa.png') or FluentIcon.PLAY),
            ('vk', 'VK Video', get_logo_icon('vk.png')),
            ('tiktok', 'TikTok', get_logo_icon('tiktok.png')),
            ('rutube', 'RuTube', get_logo_icon('rutube.png')),
            ('instagram', 'Instagram', get_logo_icon('instagram.png')),
            ('pinterest', 'Pinterest', get_logo_icon('pinterest.png') or FluentIcon.PHOTO),
            ('stream', 'Twitch / Kick', get_logo_icon('twitch.png')),
            ('other', self.translator.translate('platform_other', 'Другие'), FluentIcon.MORE),
        ]
        target_idx = 0
        for idx, (p_id, p_name, p_icon) in enumerate(platforms):
            if p_icon:
                self.platform_filter_combo.addItem(p_name, icon=p_icon, userData=p_id)
            else:
                self.platform_filter_combo.addItem(p_name, userData=p_id)
            if p_id == curr_data:
                target_idx = idx
        self.platform_filter_combo.setCurrentIndex(target_idx)
        self.platform_filter_combo.blockSignals(False)

    def _get_task_platform_group(self, task):
        u = (getattr(task, 'url', '') or '').lower()
        p = (getattr(task, 'platform', '') or '').lower()
        ref = (getattr(task, 'referer', '') or '').lower()
        if 'youtube' in u or 'youtu.be' in u or 'youtube' in p:
            return 'youtube'
        if 'vi3000' in u or 'lampa' in u or 'cub' in u or 'vi3000' in ref or 'lampa' in ref:
            return 'lampa'
        if ('kinopub' in u or 'kino.pub' in u or 'rezka' in u or 'voidboost' in u or 
            'kinopub' in ref or 'rezka' in ref):
            return 'kinopub'
        if 'animego' in u or 'kodik' in u or 'animego' in p:
            return 'animego'
        if 'pinterest' in u or 'pin.it' in u or 'pinterest' in p:
            return 'pinterest'
        if 'vk.com' in u or 'vkvideo' in u or 'vk' in p:
            return 'vk'
        if 'tiktok.com' in u or 'tiktok' in p:
            return 'tiktok'
        if 'rutube.ru' in u or 'rutube' in p:
            return 'rutube'
        if 'instagram.com' in u or 'instagram' in p:
            return 'instagram'
        if 'twitch.tv' in u or 'kick.com' in u or 'twitch' in p or 'kick' in p:
            return 'stream'
        return 'other'

    def apply_downloads_filter(self):
        filter_mode = getattr(self, 'current_filter_mode', 'all')
        query = self.search_downloads_input.text().strip().lower() if hasattr(self, 'search_downloads_input') else ""
        selected_platform = self.platform_filter_combo.currentData() if hasattr(self, 'platform_filter_combo') else 'all'
        if not selected_platform:
            selected_platform = 'all'

        from .download_task import DownloadTask
        for i in range(self.downloads_list.count()):
            item = self.downloads_list.item(i)
            widget = self.downloads_list.itemWidget(item)
            if not widget:
                continue
            task = widget.task
            matches_filter = True
            if filter_mode == 'downloading':
                matches_filter = task.status in (DownloadTask.Status.DOWNLOADING, DownloadTask.Status.PROCESSING, DownloadTask.Status.FETCHING_INFO)
            elif filter_mode == 'completed':
                matches_filter = task.status == DownloadTask.Status.COMPLETED
            elif filter_mode == 'error':
                matches_filter = task.status in (DownloadTask.Status.ERROR, DownloadTask.Status.STOPPED)

            matches_search = True
            if query:
                title = (task.title or "").lower()
                url = (task.url or "").lower()
                matches_search = (query in title) or (query in url)

            matches_platform = True
            if selected_platform != 'all':
                matches_platform = (self._get_task_platform_group(task) == selected_platform)

            item.setHidden(not (matches_filter and matches_search and matches_platform))

    def show_quick_speed_menu(self):
        menu = RoundMenu(parent=self)
        speeds = [
            (0, self.translator.translate('speed_unlimited', 'Без ограничений')),
            (512 * 1024, "512 КБ/с"),
            (1024 * 1024, "1 МБ/с"),
            (3 * 1024 * 1024, "3 МБ/с"),
            (5 * 1024 * 1024, "5 МБ/с"),
            (10 * 1024 * 1024, "10 МБ/с"),
            (20 * 1024 * 1024, "20 МБ/с"),
            (50 * 1024 * 1024, "50 МБ/с"),
            (100 * 1024 * 1024, "100 МБ/с"),
        ]
        curr_speed = self.settings.value('speed_limit', 0, type=int)
        for s_bytes, s_label in speeds:
            action = Action(s_label, self)
            if s_bytes == curr_speed:
                action.setIcon(FluentIcon.ACCEPT)
            action.triggered.connect(lambda _checked, val=s_bytes: self.set_quick_speed_limit(val))
            menu.addAction(action)

        menu.addSeparator()
        act_more = Action(self.translator.translate('settings', 'Настройки...'), self)
        act_more.setIcon(FluentIcon.SETTING)
        act_more.triggered.connect(self._show_settings_tab)
        menu.addAction(act_more)

        menu.exec(self.btn_quick_speed.mapToGlobal(self.btn_quick_speed.rect().bottomLeft()))

    def set_quick_speed_limit(self, speed_bytes):
        self.settings.setValue('speed_limit', speed_bytes)
        self.settings.sync()
        self.update_quick_speed_display()
        if self._settings_page and hasattr(self._settings_page, 'load_settings'):
            self._settings_page.load_settings()

    def update_quick_speed_display(self):
        curr_speed = self.settings.value('speed_limit', 0, type=int)
        if curr_speed <= 0:
            text = self.translator.translate('speed_unlimited', 'Без ограничений')
        elif curr_speed >= 1024 * 1024:
            mb = curr_speed / (1024.0 * 1024.0)
            text = f"{mb:.1f} МБ/с" if mb % 1 != 0 else f"{int(mb)} МБ/с"
        else:
            kb = curr_speed / 1024.0
            text = f"{int(kb)} КБ/с"
        self.btn_quick_speed.setText(text)
        self.btn_quick_speed.setIcon(FluentIcon.SPEED_HIGH)

    def update_disk_space(self):
        save_path = self.settings.value('save_path', '')
        if not save_path or not os.path.exists(save_path):
            if getattr(sys, 'frozen', False):
                save_path = os.path.dirname(sys.executable)
            else:
                save_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        try:
            total, used, free = shutil.disk_usage(save_path)
            free_gb = free / (1024 ** 3)
            drive = os.path.splitdrive(os.path.abspath(save_path))[0]
            prefix = f"{drive} " if drive else ""
            free_word = self.translator.translate('free_space_suffix', 'свободно')
            self.btn_disk_space.setText(f"{prefix}{free_gb:.1f} GB")
            self.btn_disk_space.setIcon(FluentIcon.SAVE)
            self.btn_disk_space.setToolTip(f"{self.translator.translate('open_save_folder', 'Открыть папку загрузок')}: {prefix}{free_gb:.1f} GB {free_word} ({save_path})")
        except Exception:
            self.btn_disk_space.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'drag_overlay') and self.drag_overlay and self.centralWidget():
            self.drag_overlay.setGeometry(self.centralWidget().rect())

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
            if hasattr(self, 'drag_overlay') and self.drag_overlay and self.centralWidget():
                self.drag_overlay.setGeometry(self.centralWidget().rect())
                self.drag_overlay.show()
                self.drag_overlay.raise_()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        if hasattr(self, 'drag_overlay') and self.drag_overlay:
            self.drag_overlay.hide()
        event.accept()

    def dropEvent(self, event: QDropEvent):
        if hasattr(self, 'drag_overlay') and self.drag_overlay:
            self.drag_overlay.hide()

        urls_found = []
        # 1. Извлечение из файлов (например брошен .txt со ссылками)
        if event.mimeData().hasUrls():
            for qurl in event.mimeData().urls():
                if qurl.isLocalFile():
                    local_path = qurl.toLocalFile()
                    if os.path.exists(local_path) and (local_path.endswith('.txt') or not os.path.splitext(local_path)[1]):
                        try:
                            with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
                                for line in f:
                                    for u in re.findall(r'https?://[^\s<>"]+', line):
                                        u = u.strip().rstrip('.,;)]}>')
                                        if u and u not in urls_found:
                                            urls_found.append(u)
                        except Exception as e:
                            logger.error(f"Error reading dropped file {local_path}: {e}")
                else:
                    u_str = qurl.toString().strip()
                    if u_str.startswith(('http://', 'https://')) and u_str not in urls_found:
                        urls_found.append(u_str)

        # 2. Извлечение из текста (перетаскивание текста/ссылки из браузера)
        if event.mimeData().hasText():
            text = event.mimeData().text().strip()
            for u in re.findall(r'https?://[^\s<>"]+', text):
                u = u.strip().rstrip('.,;)]}>')
                if u and u not in urls_found:
                    urls_found.append(u)

        if urls_found:
            event.acceptProposedAction()
            self.page_stack.setCurrentIndex(0)
            prompt_tr = (self.btn_timerange_mode.isChecked() if hasattr(self, 'btn_timerange_mode') else False) if len(urls_found) == 1 else False
            self.download_manager.add_urls(urls_found, prompt_time_range=prompt_tr)
            for u in urls_found:
                self._add_recent(u)
            self._rebuild_recent_buttons()
            try:
                from qfluentwidgets import InfoBar, InfoBarPosition
                InfoBar.success(
                    title=self.translator.translate('batch_added_title', "Пакетное добавление"),
                    content=f"Добавлено {len(urls_found)} ссылок через Drag & Drop.",
                    position=InfoBarPosition.TOP,
                    duration=3500,
                    parent=self
                )
            except Exception:
                pass
        else:
            event.ignore()
