import os
import re
import logging
import subprocess
import platform
import urllib.parse
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QFileDialog, QGridLayout, QGroupBox, QLabel, QComboBox,
                             QMessageBox, QApplication)
from PyQt6.QtCore import Qt, QTimer, QSettings, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from qfluentwidgets import (SwitchButton, ComboBox, SpinBox, DoubleSpinBox, RadioButton,
                             PushButton, BodyLabel, CaptionLabel, FluentIcon, SingleDirectionScrollArea, LineEdit)
from .translation import Translator
from .theme_manager import ThemeManager

logger = logging.getLogger(__name__)

SPEED_PRESETS = [
    (0, "speed_unlimited", "Без ограничений"),
    (256 * 1024, None, "256 КБ/с"),
    (512 * 1024, None, "512 КБ/с"),
    (1024 * 1024, None, "1 МБ/с"),
    (2 * 1024 * 1024, None, "2 МБ/с"),
    (3 * 1024 * 1024, None, "3 МБ/с"),
    (5 * 1024 * 1024, None, "5 МБ/с"),
    (8 * 1024 * 1024, None, "8 МБ/с"),
    (10 * 1024 * 1024, None, "10 МБ/с"),
    (15 * 1024 * 1024, None, "15 МБ/с"),
    (20 * 1024 * 1024, None, "20 МБ/с"),
    (30 * 1024 * 1024, None, "30 МБ/с"),
    (50 * 1024 * 1024, None, "50 МБ/с"),
    (100 * 1024 * 1024, None, "100 МБ/с"),
    (200 * 1024 * 1024, None, "200 МБ/с"),
    (-1, "speed_custom", "Своё значение..."),
]


class CookieTestThread(QThread):
    result_ready = pyqtSignal(bool, str)

    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser

    def run(self):
        try:
            import yt_dlp.cookies
            jar = yt_dlp.cookies.extract_cookies_from_browser(self.browser)
            count = len(list(jar))
            if count > 0:
                self.result_ready.emit(True, f"Успешно! Найдено {count} cookies в {self.browser.capitalize()}.")
            else:
                self.result_ready.emit(True, f"Браузер {self.browser.capitalize()} доступен (активных cookies не найдено).")
        except Exception as e:
            err_str = str(e)
            if 'DPAPI' in err_str or 'decrypt' in err_str.lower():
                msg = f"Защита App-Bound Encryption (Chrome 127+) блокирует прямое чтение. Чтобы не закрывать браузер, выберите «Файл cookie» выше (через cookies.txt)."
            elif 'locked' in err_str.lower() or 'could not copy' in err_str.lower():
                msg = f"{self.browser.capitalize()} запущен и блокирует базу. Чтобы не закрывать браузер, выберите «Файл cookie» выше (через cookies.txt)."
            else:
                msg = f"Не удалось прочитать: {err_str}"
            self.result_ready.emit(False, msg)



class SettingsTab(QWidget):
    def __init__(self, translator: Translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.parent_window = parent
        self.settings = parent.settings
        self.available_browsers = []
        self.detect_available_browsers()
        self.initUI()
        self.translator.language_changed.connect(self.update_translations)

    def detect_available_browsers(self):
        browsers_to_check = {
            'chrome': ['Google Chrome', 'Chrome', 'google-chrome', 'chrome'],
            'firefox': ['Firefox', 'firefox'],
            'brave': ['Brave Browser', 'Brave', 'brave-browser', 'brave'],
            'edge': ['Microsoft Edge', 'msedge', 'microsoft-edge'],
            'opera': ['Opera', 'opera'],
            'vivaldi': ['Vivaldi', 'vivaldi'],
            'safari': ['Safari', 'safari'],
            'chromium': ['Chromium', 'chromium-browser', 'chromium']
        }

        self.available_browsers = ['none']
        system = platform.system()

        for browser_key, names in browsers_to_check.items():
            if system == 'Windows':
                if self._check_browser_windows(names):
                    self.available_browsers.append(browser_key)
            elif system == 'Darwin':
                if self._check_browser_macos(names):
                    self.available_browsers.append(browser_key)
            else:
                if self._check_browser_linux(names):
                    self.available_browsers.append(browser_key)

    def _check_browser_windows(self, names):
        import winreg
        paths_to_check = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
        ]

        for path in paths_to_check:
            for name in names:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{path}\\{name}.exe"):
                        return True
                except:
                    pass

        common_paths = [
            os.environ.get('PROGRAMFILES', ''),
            os.environ.get('PROGRAMFILES(X86)', ''),
            os.environ.get('LOCALAPPDATA', ''),
        ]

        for base_path in common_paths:
            if not base_path:
                continue
            for name in names:
                if os.path.exists(os.path.join(base_path, name)):
                    return True
                if os.path.exists(os.path.join(base_path, f"{name}.exe")):
                    return True
        return False

    def _check_browser_macos(self, names):
        for name in names:
            if os.path.exists(f"/Applications/{name}.app"):
                return True
            try:
                result = subprocess.run(['mdfind', f'kMDItemDisplayName == "{name}.app"'],
                                        capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except:
                pass
        return False

    def _check_browser_linux(self, names):
        for name in names:
            try:
                result = subprocess.run(['which', name], capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except:
                pass
        return False

    def initUI(self):
        # Внешний контейнер для страницы настроек
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Скролл-область Fluent UI: предотвращает сжатие и наложение элементов на экранах ноутбуков
        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Orientation.Vertical, parent=self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.enableTransparentBackground()
        self.scroll_area.setStyleSheet("SingleDirectionScrollArea, QScrollArea { border: none; background: transparent; }")

        # Внутренний виджет, растягивающийся на полную высоту содержимого
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName('SettingsScrollContent')
        self.scroll_content.setStyleSheet("#SettingsScrollContent { background: transparent; }")

        main_layout = QVBoxLayout(self.scroll_content)
        main_layout.setContentsMargins(20, 15, 20, 25)
        main_layout.setSpacing(18)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.create_general_settings(main_layout)
        self.create_download_settings(main_layout)
        self.create_quality_settings(main_layout)

        self.scroll_area.setWidget(self.scroll_content)
        outer_layout.addWidget(self.scroll_area)

        self.update_translations()
        self.connect_signals()
        self.load_settings()

    def create_general_settings(self, layout):
        group_box = QGroupBox()
        group_box.setProperty("title_key", "general_settings")
        group_box.setObjectName('SettingsGroup')
        v_layout = QVBoxLayout(group_box)
        v_layout.setSpacing(14)
        v_layout.setContentsMargins(16, 22, 16, 16)

        theme_layout = QHBoxLayout()
        self.theme_label = BodyLabel()
        self.theme_label.setProperty("text_key", "select_theme")
        self.theme_combo = ComboBox()
        self.theme_combo.addItem('Dark', userData='dark')
        self.theme_combo.addItem('Light', userData='light')
        self.theme_combo.setFixedWidth(160)
        theme_layout.addWidget(self.theme_label)
        theme_layout.addStretch()
        theme_layout.addWidget(self.theme_combo)
        v_layout.addLayout(theme_layout)

        parallel_layout = QHBoxLayout()
        self.parallel_label = BodyLabel()
        self.parallel_label.setProperty("text_key", "parallel_downloads")
        self.parallel_downloads_spin = SpinBox()
        self.parallel_downloads_spin.setRange(1, 10)
        self.parallel_downloads_spin.setFixedWidth(160)
        parallel_layout.addWidget(self.parallel_label)
        parallel_layout.addStretch()
        parallel_layout.addWidget(self.parallel_downloads_spin)
        v_layout.addLayout(parallel_layout)

        # Настройка работы в трее
        tray_layout = QHBoxLayout()
        self.tray_label = BodyLabel()
        self.tray_label.setProperty("text_key", "tray")
        self.tray_label.setText("Сворачивать в трей при закрытии")
        self.tray_checkbox = SwitchButton()
        self.tray_checkbox.setOnText("Вкл")
        self.tray_checkbox.setOffText("Выкл")
        tray_layout.addWidget(self.tray_label)
        tray_layout.addStretch()
        tray_layout.addWidget(self.tray_checkbox)
        v_layout.addLayout(tray_layout)

        # Портативный режим (data/settings.ini)
        portable_layout = QHBoxLayout()
        self.portable_label = BodyLabel()
        self.portable_label.setProperty("text_key", "portable_mode")
        self.portable_label.setText("Портативный режим (хранить настройки в data/)")
        self.portable_checkbox = SwitchButton()
        self.portable_checkbox.setOnText("Вкл")
        self.portable_checkbox.setOffText("Выкл")
        portable_layout.addWidget(self.portable_label)
        portable_layout.addStretch()
        portable_layout.addWidget(self.portable_checkbox)
        v_layout.addLayout(portable_layout)

        # Мониторинг буфера обмена
        clipboard_layout = QHBoxLayout()
        self.clipboard_label = BodyLabel()
        self.clipboard_label.setProperty("text_key", "clipboard_monitor")
        self.clipboard_label.setText("Отслеживать ссылки в буфере обмена")
        self.clipboard_checkbox = SwitchButton()
        self.clipboard_checkbox.setOnText("Вкл")
        self.clipboard_checkbox.setOffText("Выкл")
        clipboard_layout.addWidget(self.clipboard_label)
        clipboard_layout.addStretch()
        clipboard_layout.addWidget(self.clipboard_checkbox)
        v_layout.addLayout(clipboard_layout)

        # Действие по завершению всех загрузок
        completion_layout = QHBoxLayout()
        self.completion_label = BodyLabel()
        self.completion_label.setProperty("text_key", "on_completion_action")
        self.completion_label.setText("По завершению всех загрузок")
        self.completion_combo = ComboBox()
        self.completion_combo.setFixedWidth(180)
        self.completion_combo.addItem("Ничего не делать", userData="none")
        self.completion_combo.addItem("Выключить ПК", userData="shutdown")
        self.completion_combo.addItem("Спящий режим", userData="sleep")
        self.completion_combo.addItem("Закрыть программу", userData="exit_app")
        completion_layout.addWidget(self.completion_label)
        completion_layout.addStretch()
        completion_layout.addWidget(self.completion_combo)
        v_layout.addLayout(completion_layout)

        layout.addWidget(group_box)

    def create_download_settings(self, layout):
        group_box = QGroupBox()
        group_box.setProperty("title_key", "download_settings")
        group_box.setObjectName('SettingsGroup')
        v_layout = QVBoxLayout(group_box)
        v_layout.setSpacing(14)
        v_layout.setContentsMargins(16, 22, 16, 16)

        # Sponsorblock
        sb_layout = QHBoxLayout()
        sb_lbl = BodyLabel()
        sb_lbl.setProperty("text_key", "sponsorblock")
        self.sponsorblock_checkbox = SwitchButton()
        self.sponsorblock_checkbox.setOnText("Вкл")
        self.sponsorblock_checkbox.setOffText("Выкл")
        sb_layout.addWidget(sb_lbl)
        sb_layout.addStretch()
        sb_layout.addWidget(self.sponsorblock_checkbox)
        v_layout.addLayout(sb_layout)

        # Субтитры
        sub_layout = QHBoxLayout()
        sub_lbl = BodyLabel()
        sub_lbl.setProperty("text_key", "download_subtitles")
        self.subtitles_checkbox = SwitchButton()
        self.subtitles_checkbox.setOnText("Вкл")
        self.subtitles_checkbox.setOffText("Выкл")
        sub_layout.addWidget(sub_lbl)
        sub_layout.addStretch()
        sub_layout.addWidget(self.subtitles_checkbox)
        v_layout.addLayout(sub_layout)

        # Путь сохранения
        save_path_layout = QHBoxLayout()
        save_path_lbl_title = BodyLabel()
        save_path_lbl_title.setProperty("text_key", "select_save_folder")

        self.save_path_lbl = BodyLabel()
        self.save_path_lbl.setOpenExternalLinks(True)
        self.save_path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.save_path_lbl.setStyleSheet("color: #005fb8;")

        self.save_path_btn = PushButton("Изменить")
        self.save_path_btn.setIcon(FluentIcon.FOLDER.icon())

        save_path_layout.addWidget(save_path_lbl_title)
        save_path_layout.addSpacing(10)
        save_path_layout.addWidget(self.save_path_lbl, 1)
        save_path_layout.addWidget(self.save_path_btn)
        v_layout.addLayout(save_path_layout)

        # Куки
        cookies_layout = QHBoxLayout()
        cookies_lbl = BodyLabel()
        cookies_lbl.setProperty("text_key", "use_cookies")
        self.cookies_checkbox = SwitchButton()
        self.cookies_checkbox.setOnText("Вкл")
        self.cookies_checkbox.setOffText("Выкл")
        cookies_layout.addWidget(cookies_lbl)
        cookies_layout.addStretch()
        cookies_layout.addWidget(self.cookies_checkbox)
        v_layout.addLayout(cookies_layout)

        # Опции куки
        self.cookies_options_widget = QWidget()
        co_layout = QVBoxLayout(self.cookies_options_widget)
        co_layout.setContentsMargins(20, 0, 0, 0)
        co_layout.setSpacing(10)

        # Файл куки
        file_opt_layout = QHBoxLayout()
        self.rb_cookie_file = RadioButton()
        self.rb_cookie_file.setProperty("text_key", "cookie_file")
        self.cookies_lbl = BodyLabel()
        self.cookies_lbl.setStyleSheet("color: #005fb8;")
        self.cookies_btn = PushButton("Выбрать файл")
        self.cookies_btn.setIcon(FluentIcon.DOCUMENT.icon())

        file_opt_layout.addWidget(self.rb_cookie_file)
        file_opt_layout.addSpacing(10)
        file_opt_layout.addWidget(self.cookies_lbl, 1)
        file_opt_layout.addWidget(self.cookies_btn)
        co_layout.addLayout(file_opt_layout)

        # Браузер куки
        browser_opt_layout = QHBoxLayout()
        self.rb_cookie_browser = RadioButton()
        self.rb_cookie_browser.setProperty("text_key", "cookie_browser")
        self.cookie_browser_combo = ComboBox()
        self.cookie_browser_combo.setFixedWidth(200)
        for browser in self.available_browsers:
            display_name = browser.capitalize() if browser != 'none' else 'None'
            self.cookie_browser_combo.addItem(display_name, userData=browser)

        browser_opt_layout.addWidget(self.rb_cookie_browser)
        browser_opt_layout.addStretch()
        browser_opt_layout.addWidget(self.cookie_browser_combo)
        co_layout.addLayout(browser_opt_layout)

        # Тестирование чтения cookies
        cookie_test_layout = QHBoxLayout()
        self.btn_test_cookies = PushButton("Проверить cookies")
        self.btn_test_cookies.setIcon(FluentIcon.ACCEPT.icon())
        self.btn_cookie_help = PushButton("Без закрытия браузера")
        self.btn_cookie_help.setIcon(FluentIcon.HELP.icon())
        self.btn_cookie_help.clicked.connect(self.show_cookie_help_dialog)
        self.lbl_cookie_status = BodyLabel("")
        self.lbl_cookie_status.setWordWrap(True)
        self.lbl_cookie_status.setStyleSheet("color: #888888; font-size: 12px;")
        cookie_test_layout.addWidget(self.btn_test_cookies)
        cookie_test_layout.addWidget(self.btn_cookie_help)
        cookie_test_layout.addSpacing(10)
        cookie_test_layout.addWidget(self.lbl_cookie_status, 1)
        co_layout.addLayout(cookie_test_layout)

        v_layout.addWidget(self.cookies_options_widget)

        # Ограничение скорости
        speed_layout = QHBoxLayout()
        self.speed_label = BodyLabel()
        self.speed_label.setProperty("text_key", "speed_limit")
        self.speed_combo = ComboBox()
        self.speed_combo.setFixedWidth(170)
        self.populate_speed_presets()
        speed_layout.addWidget(self.speed_label)
        speed_layout.addStretch()
        speed_layout.addWidget(self.speed_combo)
        v_layout.addLayout(speed_layout)

        # Кастомная скорость (показывается при выборе "Своё значение...")
        self.custom_speed_widget = QWidget()
        custom_speed_layout = QHBoxLayout(self.custom_speed_widget)
        custom_speed_layout.setContentsMargins(20, 0, 0, 0)
        custom_speed_layout.setSpacing(10)

        custom_lbl = BodyLabel()
        custom_lbl.setProperty("text_key", "custom_speed_label")
        self.custom_speed_spin = DoubleSpinBox()
        self.custom_speed_spin.setRange(0.1, 9999.0)
        self.custom_speed_spin.setValue(10.0)
        self.custom_speed_spin.setSingleStep(1.0)
        self.custom_speed_spin.setDecimals(1)
        self.custom_speed_spin.setFixedWidth(110)

        self.custom_speed_unit = ComboBox()
        self.custom_speed_unit.setFixedWidth(90)
        self.custom_speed_unit.addItem("МБ/с", userData="MB")
        self.custom_speed_unit.addItem("КБ/с", userData="KB")

        custom_speed_layout.addWidget(custom_lbl)
        custom_speed_layout.addStretch()
        custom_speed_layout.addWidget(self.custom_speed_spin)
        custom_speed_layout.addWidget(self.custom_speed_unit)
        v_layout.addWidget(self.custom_speed_widget)
        self.custom_speed_widget.setVisible(False)

        # Параллельные фрагменты HLS/DASH (yt-dlp)
        frag_layout = QHBoxLayout()
        self.frag_label = BodyLabel()
        self.frag_label.setProperty("text_key", "concurrent_fragments_label")
        self.frag_spin = SpinBox()
        self.frag_spin.setRange(1, 16)
        self.frag_spin.setValue(8)
        self.frag_spin.setFixedWidth(110)
        frag_layout.addWidget(self.frag_label)
        frag_layout.addStretch()
        frag_layout.addWidget(self.frag_spin)
        v_layout.addLayout(frag_layout)

        # Формат извлечения аудио
        audio_fmt_layout = QHBoxLayout()
        self.audio_fmt_label = BodyLabel()
        self.audio_fmt_label.setProperty("text_key", "audio_format")
        self.audio_fmt_label.setText("Формат аудио (при извлечении)")
        self.audio_fmt_combo = ComboBox()
        self.audio_fmt_combo.setFixedWidth(170)
        for fmt_name in ["MP3", "M4A", "FLAC", "Opus", "WAV"]:
            self.audio_fmt_combo.addItem(fmt_name, userData=fmt_name.lower())
        audio_fmt_layout.addWidget(self.audio_fmt_label)
        audio_fmt_layout.addStretch()
        audio_fmt_layout.addWidget(self.audio_fmt_combo)
        v_layout.addLayout(audio_fmt_layout)

        # Качество аудио / битрейт
        audio_bitrate_layout = QHBoxLayout()
        self.audio_bitrate_label = BodyLabel()
        self.audio_bitrate_label.setProperty("text_key", "audio_bitrate")
        self.audio_bitrate_label.setText("Качество / битрейт аудио")
        self.audio_bitrate_combo = ComboBox()
        self.audio_bitrate_combo.setFixedWidth(170)
        self.audio_bitrate_combo.addItem("320 kbps (Высокое)", userData="320")
        self.audio_bitrate_combo.addItem("256 kbps", userData="256")
        self.audio_bitrate_combo.addItem("192 kbps (Стандарт)", userData="192")
        self.audio_bitrate_combo.addItem("128 kbps (Эконом)", userData="128")
        self.audio_bitrate_combo.addItem("VBR / Без сжатия", userData="VBR/Best")
        audio_bitrate_layout.addWidget(self.audio_bitrate_label)
        audio_bitrate_layout.addStretch()
        audio_bitrate_layout.addWidget(self.audio_bitrate_combo)
        v_layout.addLayout(audio_bitrate_layout)

        # Вшивание метаданных и тегов (ID3)
        meta_layout = QHBoxLayout()
        self.meta_lbl = BodyLabel()
        self.meta_lbl.setProperty("text_key", "embed_metadata")
        self.meta_lbl.setText("Вшивать метаданные и ID3-теги")
        self.embed_metadata_checkbox = SwitchButton()
        self.embed_metadata_checkbox.setOnText("Вкл")
        self.embed_metadata_checkbox.setOffText("Выкл")
        meta_layout.addWidget(self.meta_lbl)
        meta_layout.addStretch()
        meta_layout.addWidget(self.embed_metadata_checkbox)
        v_layout.addLayout(meta_layout)

        # Вшивание обложки в аудиофайлы
        thumb_layout = QHBoxLayout()
        self.thumb_lbl = BodyLabel()
        self.thumb_lbl.setProperty("text_key", "embed_thumbnail")
        self.thumb_lbl.setText("Вшивать обложку трека (Cover Art)")
        self.embed_thumbnail_checkbox = SwitchButton()
        self.embed_thumbnail_checkbox.setOnText("Вкл")
        self.embed_thumbnail_checkbox.setOffText("Выкл")
        thumb_layout.addWidget(self.thumb_lbl)
        thumb_layout.addStretch()
        thumb_layout.addWidget(self.embed_thumbnail_checkbox)
        v_layout.addLayout(thumb_layout)

        layout.addWidget(group_box)


    def create_quality_settings(self, layout):
        group_box = QGroupBox()
        group_box.setProperty("title_key", "quality_settings")
        group_box.setObjectName('SettingsGroup')

        grid_layout = QGridLayout(group_box)
        grid_layout.setContentsMargins(16, 22, 16, 16)
        grid_layout.setSpacing(12)
        grid_layout.setVerticalSpacing(10)
        grid_layout.setHorizontalSpacing(16)

        grid_layout.setColumnStretch(2, 1)
        grid_layout.setColumnStretch(5, 1)
        grid_layout.setColumnStretch(8, 1)

        platforms = ['YouTube', 'RuTube', 'TikTok', 'Instagram', 'VK', 'PornHub', 'Facebook', 'X (Twitter)',
                     'Kinopoisk', 'Twitch', 'Kick', 'KinoPub']
        self.quality_combos = {}

        row, col = 0, 0
        for platform in platforms:
            platform_label = self._platform_label(platform)
            combo = QComboBox()
            combo.setMinimumWidth(130)
            self.quality_combos[platform] = combo

            grid_col_offset = col * 3

            grid_layout.addWidget(platform_label, row, grid_col_offset)
            grid_layout.addWidget(combo, row, grid_col_offset + 1)

            col += 1
            if col > 2:
                col = 0
                row += 1

        layout.addWidget(group_box)

    def _platform_label(self, name):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        pic = QLabel()
        logos_dir = os.path.join(os.path.dirname(__file__), '..', 'assets', 'logos')
        fname_map = {
            'YouTube': 'youtube.png',
            'RuTube': 'rutube.png',
            'TikTok': 'tiktok.png',
            'Instagram': 'instagram.png',
            'VK': 'vk.png',
            'PornHub': 'pornhub.png',
            'Facebook': 'facebook.png',
            'X (Twitter)': 'x_(twitter).png',
            'Kinopoisk': 'kinopoisk.png',
            'Twitch': 'twitch.png',
            'Kick': 'kick.png',
            'KinoPub': 'hdrezka.png'
        }
        fpath = os.path.join(logos_dir, fname_map.get(name, ''))
        if os.path.exists(fpath):
            pm = QPixmap(fpath)
            if not pm.isNull():
                pic.setPixmap(pm.scaled(
                    18, 18,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                ))
        lbl = QLabel(f"{name}:")
        h.addWidget(pic)
        h.addWidget(lbl)
        return w

    def connect_signals(self):
        self.theme_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.parallel_downloads_spin.valueChanged.connect(self.on_setting_changed)
        self.save_path_btn.clicked.connect(self.on_select_save_path)
        self.subtitles_checkbox.checkedChanged.connect(self.on_setting_changed)
        self.sponsorblock_checkbox.checkedChanged.connect(self.on_setting_changed)
        self.cookies_checkbox.checkedChanged.connect(self.on_setting_changed)
        self.rb_cookie_file.toggled.connect(self.on_setting_changed)
        self.cookies_btn.clicked.connect(self.on_select_cookies_file)
        self.cookie_browser_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.tray_checkbox.checkedChanged.connect(self.on_setting_changed)
        self.clipboard_checkbox.checkedChanged.connect(self.on_setting_changed)
        self.completion_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.audio_fmt_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.audio_bitrate_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.embed_metadata_checkbox.checkedChanged.connect(self.on_setting_changed)
        self.embed_thumbnail_checkbox.checkedChanged.connect(self.on_setting_changed)
        self.speed_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.custom_speed_spin.valueChanged.connect(self.on_setting_changed)
        self.custom_speed_unit.currentIndexChanged.connect(self.on_setting_changed)
        self.frag_spin.valueChanged.connect(self.on_setting_changed)
        self.portable_checkbox.checkedChanged.connect(self.on_portable_toggled)
        self.btn_test_cookies.clicked.connect(self.on_test_cookies_clicked)
        for combo in self.quality_combos.values():
            combo.currentIndexChanged.connect(self.on_setting_changed)

    def disconnect_signals(self):
        signals_to_disconnect = [
            self.theme_combo.currentIndexChanged,
            self.parallel_downloads_spin.valueChanged,
            self.save_path_btn.clicked,
            self.subtitles_checkbox.checkedChanged,
            self.sponsorblock_checkbox.checkedChanged,
            self.cookies_checkbox.checkedChanged,
            self.rb_cookie_file.toggled,
            self.cookies_btn.clicked,
            self.cookie_browser_combo.currentIndexChanged,
            self.tray_checkbox.checkedChanged,
            self.clipboard_checkbox.checkedChanged,
            self.completion_combo.currentIndexChanged,
            self.audio_fmt_combo.currentIndexChanged,
            self.audio_bitrate_combo.currentIndexChanged,
            self.embed_metadata_checkbox.checkedChanged,
            self.embed_thumbnail_checkbox.checkedChanged,
            self.speed_combo.currentIndexChanged,
            self.custom_speed_spin.valueChanged,
            self.custom_speed_unit.currentIndexChanged,
            self.frag_spin.valueChanged,
            self.portable_checkbox.checkedChanged,
            self.btn_test_cookies.clicked,
        ]
        for s in signals_to_disconnect:
            try:
                s.disconnect()
            except Exception:
                pass
        for combo in self.quality_combos.values():
            try:
                combo.currentIndexChanged.disconnect()
            except Exception:
                pass

    def populate_youtube_qualities(self, cbox):
        cbox.addItem(self.translator.translate('video_best_quality'), userData='bestvideo+bestaudio/best')
        cbox.addItem(self.translator.translate('audio_only'), userData='bestaudio/best')
        cbox.addItem('144p', userData='bestvideo[height<=144]+bestaudio/best')
        cbox.addItem('240p', userData='bestvideo[height<=240]+bestaudio/best')
        cbox.addItem('360p', userData='bestvideo[height<=360]+bestaudio/best')
        cbox.addItem('480p', userData='bestvideo[height<=480]+bestaudio/best')
        cbox.addItem('720p (HD)', userData='bestvideo[height<=720]+bestaudio/best')
        cbox.addItem('1080p (Full HD)', userData='bestvideo[height<=1080]+bestaudio/best')
        cbox.addItem('1440p (2K)', userData='bestvideo[height<=1440]+bestaudio/best')
        cbox.addItem('2160p (4K)', userData='bestvideo[height<=2160]+bestaudio/best')

    def populate_generic_qualities(self, cbox):
        cbox.addItem(self.translator.translate('best_quality'), userData='best')
        cbox.addItem(self.translator.translate('audio_only'), userData='bestaudio/best')
        cbox.addItem(self.translator.translate('video_only'), userData='video_only_stripped')
        cbox.addItem(self.translator.translate('worst_quality'), userData='worst')

    def populate_speed_presets(self):
        curr_data = self.speed_combo.currentData() if self.speed_combo.count() > 0 else None
        self.speed_combo.clear()
        for bytes_val, key, default_text in SPEED_PRESETS:
            label = self.translator.translate(key, default_text) if key else default_text
            self.speed_combo.addItem(label, userData=bytes_val)
        if curr_data is not None:
            self.set_combo_by_data(self.speed_combo, curr_data)

    def update_translations(self):
        widgets_with_keys = self.findChildren(QWidget)
        for widget in widgets_with_keys:
            key = widget.property("text_key")
            if key and hasattr(widget, 'setText'):
                widget.setText(self.translator.translate(key))

            title_key = widget.property("title_key")
            if title_key and hasattr(widget, 'setTitle'):
                widget.setTitle(self.translator.translate(title_key))

        self.populate_speed_presets()

        for platform_name, combo in self.quality_combos.items():
            current_data = combo.currentData()
            combo.clear()
            if platform_name in ['YouTube', 'KinoPub']:
                self.populate_youtube_qualities(combo)
            else:
                self.populate_generic_qualities(combo)
            self.set_combo_by_data(combo, current_data)

        save_path = self.settings.value('save_path', '')
        if save_path:
            self.save_path_lbl.setText(f'<a href="file:///{save_path}">{save_path}</a>')
        else:
            self.save_path_lbl.setText(self.translator.translate('folder_not_selected'))

        cookies_path = self.settings.value('cookies_path', '')
        if cookies_path:
            self.cookies_lbl.setText(f'<a href="file:///{cookies_path}">{cookies_path}</a>')
        else:
            self.cookies_lbl.setText(self.translator.translate('file_not_selected'))

    def load_settings(self):
        self.disconnect_signals()

        theme = self.settings.value('theme', 'dark')
        self.set_combo_by_data(self.theme_combo, theme)

        self.parallel_downloads_spin.setValue(int(self.settings.value('parallel_downloads', 2)))

        save_path = self.settings.value('save_path', '')
        if save_path:
            self.save_path_lbl.setText(f'<a href="file:///{save_path}">{save_path}</a>')
        else:
            self.save_path_lbl.setText(self.translator.translate('folder_not_selected'))

        self.subtitles_checkbox.setChecked(self.settings.value('subtitles_enabled', False, type=bool))
        self.sponsorblock_checkbox.setChecked(self.settings.value('sponsorblock_enabled', False, type=bool))
        self.cookies_checkbox.setChecked(self.settings.value('use_cookies', False, type=bool))
        self.tray_checkbox.setChecked(self.settings.value('close_to_tray', True, type=bool))
        self.clipboard_checkbox.setChecked(self.settings.value('clipboard_monitor', False, type=bool))
        self.set_combo_by_data(self.completion_combo, self.settings.value('on_completion_action', 'none'))

        self.set_combo_by_data(self.audio_fmt_combo, self.settings.value('audio_format', 'mp3'))
        self.set_combo_by_data(self.audio_bitrate_combo, str(self.settings.value('audio_bitrate', '192')))
        self.embed_metadata_checkbox.setChecked(self.settings.value('embed_metadata', True, type=bool))
        self.embed_thumbnail_checkbox.setChecked(self.settings.value('embed_thumbnail', True, type=bool))

        cookie_source_type = self.settings.value('cookie_source_type', 'browser')
        self.rb_cookie_file.setChecked(cookie_source_type == 'file')
        self.rb_cookie_browser.setChecked(cookie_source_type != 'file')

        cookies_path = self.settings.value('cookies_path', '')
        if cookies_path:
            self.cookies_lbl.setText(f'<a href="file:///{cookies_path}">{cookies_path}</a>')
        else:
            self.cookies_lbl.setText(self.translator.translate('file_not_selected'))

        cookie_browser = self.settings.value('cookie_browser', 'none')
        self.set_combo_by_data(self.cookie_browser_combo, cookie_browser)

        self.update_cookie_widgets_state()

        # Portable
        self.portable_checkbox.setChecked(self.settings.value('portable_mode', False, type=bool))



        speed_val = self.settings.value('speed_limit', 0, type=int)
        matched = False
        for idx in range(self.speed_combo.count()):
            data = self.speed_combo.itemData(idx)
            if data == speed_val and data != -1:
                self.speed_combo.setCurrentIndex(idx)
                self.custom_speed_widget.setVisible(False)
                matched = True
                break
        if not matched and speed_val > 0:
            for idx in range(self.speed_combo.count()):
                if self.speed_combo.itemData(idx) == -1:
                    self.speed_combo.setCurrentIndex(idx)
                    break
            self.custom_speed_widget.setVisible(True)
            if speed_val >= 1024 * 1024:
                self.custom_speed_spin.setValue(round(speed_val / (1024.0 * 1024.0), 2))
                self.custom_speed_unit.setCurrentIndex(0)
            else:
                self.custom_speed_spin.setValue(round(speed_val / 1024.0, 1))
                self.custom_speed_unit.setCurrentIndex(1)
        elif not matched and speed_val <= 0:
            self.speed_combo.setCurrentIndex(0)
            self.custom_speed_widget.setVisible(False)

        concurrent_frags = self.settings.value('concurrent_fragments', 8, type=int)
        self.frag_spin.setValue(max(1, min(16, concurrent_frags)))

        for platform_name, combo in self.quality_combos.items():
            key = f"quality_{platform_name.lower().replace(' ', '_').replace('(', '').replace(')', '')}"
            default_quality = 'bestvideo+bestaudio/best' if platform_name == 'YouTube' else 'best'
            quality = self.settings.value(key, default_quality)
            self.set_combo_by_data(combo, quality)

        self.connect_signals()

    def on_setting_changed(self):
        self.settings.setValue('theme', self.theme_combo.currentData())
        self.settings.setValue('parallel_downloads', self.parallel_downloads_spin.value())
        self.parent_window.thread_pool.setMaxThreadCount(max(self.parallel_downloads_spin.value() + 8, 10))

        self.settings.setValue('subtitles_enabled', self.subtitles_checkbox.isChecked())
        self.settings.setValue('sponsorblock_enabled', self.sponsorblock_checkbox.isChecked())
        self.settings.setValue('use_cookies', self.cookies_checkbox.isChecked())
        self.settings.setValue('close_to_tray', self.tray_checkbox.isChecked())
        self.settings.setValue('clipboard_monitor', self.clipboard_checkbox.isChecked())
        self.settings.setValue('on_completion_action', self.completion_combo.currentData())
        self.settings.setValue('audio_format', self.audio_fmt_combo.currentData())
        self.settings.setValue('audio_bitrate', self.audio_bitrate_combo.currentData())
        self.settings.setValue('embed_metadata', self.embed_metadata_checkbox.isChecked())
        self.settings.setValue('embed_thumbnail', self.embed_thumbnail_checkbox.isChecked())

        selected_speed_data = self.speed_combo.currentData()
        if selected_speed_data == -1:
            self.custom_speed_widget.setVisible(True)
            unit = self.custom_speed_unit.currentData()
            val = self.custom_speed_spin.value()
            multiplier = (1024 * 1024) if unit == "MB" else 1024
            speed_in_bytes = int(val * multiplier)
            self.settings.setValue('speed_limit', speed_in_bytes)
        else:
            self.custom_speed_widget.setVisible(False)
            speed_in_bytes = selected_speed_data or 0
            self.settings.setValue('speed_limit', speed_in_bytes)

        self.settings.setValue('concurrent_fragments', self.frag_spin.value())
        if hasattr(self.parent_window, 'update_quick_speed_display'):
            self.parent_window.update_quick_speed_display()
        if self.rb_cookie_file.isChecked():
            self.settings.setValue('cookie_source_type', 'file')
            self.settings.setValue('cookie_source', 'file')
        else:
            self.settings.setValue('cookie_source_type', 'browser')
            browser_value = self.cookie_browser_combo.currentData()
            self.settings.setValue('cookie_source', browser_value)
            self.settings.setValue('cookie_browser', browser_value)

        for platform_name, combo in self.quality_combos.items():
            key = f"quality_{platform_name.lower().replace(' ', '_').replace('(', '').replace(')', '')}"
            self.settings.setValue(key, combo.currentData())

        self.settings.sync()
        self.update_cookie_widgets_state()

        if self.sender() == self.theme_combo:
            ThemeManager(self.settings).apply_theme()



    def update_cookie_widgets_state(self):
        use_cookies = self.cookies_checkbox.isChecked()
        self.cookies_options_widget.setEnabled(use_cookies)
        if use_cookies:
            is_file = self.rb_cookie_file.isChecked()
            self.rb_cookie_file.setEnabled(True)
            self.cookies_btn.setEnabled(is_file)
            self.cookie_browser_combo.setEnabled(not is_file)
            self.btn_test_cookies.setEnabled(not is_file)

    def on_portable_toggled(self, checked):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        data_dir = os.path.join(project_root, 'data')
        os.makedirs(data_dir, exist_ok=True)
        portable_marker = os.path.join(data_dir, 'portable.dat')
        ini_path = os.path.join(data_dir, 'settings.ini')

        self.settings.setValue('portable_mode', checked)
        if checked:
            try:
                with open(portable_marker, 'w', encoding='utf-8') as f:
                    f.write("portable=1\n")
                ini_settings = QSettings(ini_path, QSettings.Format.IniFormat)
                for key in self.settings.allKeys():
                    ini_settings.setValue(key, self.settings.value(key))
                ini_settings.sync()
                QMessageBox.information(
                    self,
                    "Портативный режим",
                    "Портативный режим активирован!\nНастройки сохранены в data/settings.ini.\nПри следующем запуске программа будет работать полностью автономно с флешки/папки."
                )
            except Exception as e:
                logger.error(f"Error enabling portable mode: {e}")
        else:
            try:
                if os.path.exists(portable_marker):
                    os.remove(portable_marker)
                QMessageBox.information(
                    self,
                    "Портативный режим",
                    "Портативный режим отключен. Настройки будут сохраняться в системе."
                )
            except Exception as e:
                logger.error(f"Error disabling portable mode: {e}")
        self.settings.sync()



    def on_test_cookies_clicked(self):
        browser = self.cookie_browser_combo.currentData()
        if not browser or browser == 'none':
            self.lbl_cookie_status.setText("Выберите браузер в списке")
            self.lbl_cookie_status.setStyleSheet("color: #d83b01; font-size: 12px;")
            return

        self.btn_test_cookies.setEnabled(False)
        self.lbl_cookie_status.setText(f"Чтение cookies из {browser.capitalize()}...")
        self.lbl_cookie_status.setStyleSheet("color: #0078D7; font-size: 12px;")

        self._cookie_thread = CookieTestThread(browser, self)
        self._cookie_thread.result_ready.connect(self._on_cookies_test_result)
        self._cookie_thread.finished.connect(lambda: self.btn_test_cookies.setEnabled(True))
        self._cookie_thread.start()

    def _on_cookies_test_result(self, ok, msg):
        self.lbl_cookie_status.setText(msg)
        color = "#107c41" if ok else "#d83b01"
        self.lbl_cookie_status.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.btn_test_cookies.setEnabled(True)

    def show_cookie_help_dialog(self):
        from PyQt6.QtWidgets import QMessageBox
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        box = QMessageBox(self)
        box.setWindowTitle("Использование cookies без закрытия Chrome")
        box.setText(
            "<b>Как использовать cookies без закрытия Chrome и браузеров:</b><br><br>"
            "В Windows запущенный Chrome монопольно блокирует файл базы данных cookies, "
            "а с версии Chrome 127+ Google включил защиту <i>App-Bound Encryption</i>, запрещающую "
            "внешним программам читать чужие куки напрямую из файлов.<br><br>"
            "<b>Решение раз и навсегда (1 минута):</b><br>"
            "1. Установите проверенное расширение для Chrome: <b>Get cookies.txt LOCALLY</b> "
            "(бесплатное, безопасное, работает прямо внутри Chrome и с открытым исходным кодом).<br>"
            "2. Перейдите на нужный сайт (например, YouTube) со своим аккаунтом.<br>"
            "3. Нажмите иконку расширения → <b>«Export»</b> (сохранится файл <code>cookies.txt</code>).<br>"
            "4. В настройках выше выберите радиокнопку <b>«Файл cookie»</b> и укажите этот файл.<br><br>"
            "<b>Преимущества:</b><br>"
            "• Chrome <b>вообще не нужно закрывать</b> (пусть открыты сотни вкладок).<br>"
            "• Файл <code>cookies.txt</code> действует месяцами."
        )
        btn_open = box.addButton("Открыть расширение в магазине Chrome", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Понятно", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() == btn_open:
            QDesktopServices.openUrl(QUrl("https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"))


    def on_select_save_path(self):
        folder = QFileDialog.getExistingDirectory(self, self.translator.translate('select_save_folder'))
        if folder:
            self.save_path_lbl.setText(f'<a href="file:///{folder}">{folder}</a>')
            self.settings.setValue('save_path', folder)
            self.settings.sync()

    def on_select_cookies_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.translate('select_cookies_file'), '',
                                                   'Text Files (*.txt *.cookies);;All Files (*)')
        if file_path:
            self.cookies_lbl.setText(f'<a href="file:///{file_path}">{file_path}</a>')
            self.settings.setValue('cookies_path', file_path)
            self.settings.sync()

    def set_combo_by_data(self, combo, data):
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                break