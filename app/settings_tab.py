import os
import logging
import subprocess
import platform
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QFileDialog, QGridLayout, QGroupBox, QLabel, QComboBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from qfluentwidgets import (SwitchButton, ComboBox, SpinBox, RadioButton,
                            PushButton, BodyLabel, FluentIcon)
from .translation import Translator
from .theme_manager import ThemeManager

logger = logging.getLogger(__name__)


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
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.create_general_settings(main_layout)
        self.create_download_settings(main_layout)
        self.create_quality_settings(main_layout)

        self.update_translations()
        self.connect_signals()
        self.load_settings()

    def create_general_settings(self, layout):
        group_box = QGroupBox()
        group_box.setProperty("title_key", "general_settings")
        group_box.setObjectName('SettingsGroup')
        v_layout = QVBoxLayout(group_box)
        v_layout.setSpacing(12)
        v_layout.setContentsMargins(16, 24, 16, 16)

        # Тема
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

        # Параллельные загрузки
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

        layout.addWidget(group_box)

    def create_download_settings(self, layout):
        group_box = QGroupBox()
        group_box.setProperty("title_key", "download_settings")
        group_box.setObjectName('SettingsGroup')
        v_layout = QVBoxLayout(group_box)
        v_layout.setSpacing(15)
        v_layout.setContentsMargins(16, 24, 16, 16)

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
        save_path_layout.addWidget(self.save_path_lbl)
        save_path_layout.addStretch()
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
        file_opt_layout.addWidget(self.cookies_lbl)
        file_opt_layout.addStretch()
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

        v_layout.addWidget(self.cookies_options_widget)
        layout.addWidget(group_box)

    def create_quality_settings(self, layout):
        group_box = QGroupBox()
        group_box.setProperty("title_key", "quality_settings")
        group_box.setObjectName('SettingsGroup')

        grid_layout = QGridLayout(group_box)
        grid_layout.setSpacing(12)
        # Магия сетки: делаем пустые колонки (2 и 5), которые будут "пружинить"
        # и прижимать настройки влево, не разрывая их
        grid_layout.setColumnStretch(2, 1)
        grid_layout.setColumnStretch(5, 1)

        platforms = ['YouTube', 'RuTube', 'TikTok', 'Instagram', 'VK', 'PornHub', 'Facebook', 'X (Twitter)',
                     'Kinopoisk', 'Twitch', 'Kick', 'KinoPub']
        self.quality_combos = {}

        row, col = 0, 0
        for platform in platforms:
            platform_label = self._platform_label(platform)
            combo = QComboBox()
            combo.setMinimumWidth(140)
            self.quality_combos[platform] = combo

            # Смещаем индекс колонки в сетке (0-1 для первой группы, 3-4 для второй)
            grid_col_offset = col * 3

            grid_layout.addWidget(platform_label, row, grid_col_offset)
            grid_layout.addWidget(combo, row, grid_col_offset + 1)

            col += 1
            if col > 1:  # Держим строго 2 столбца
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
        for combo in self.quality_combos.values():
            combo.currentIndexChanged.connect(self.on_setting_changed)

    def disconnect_signals(self):
        self.theme_combo.currentIndexChanged.disconnect()
        self.parallel_downloads_spin.valueChanged.disconnect()
        self.save_path_btn.clicked.disconnect()
        self.subtitles_checkbox.checkedChanged.disconnect()
        self.sponsorblock_checkbox.checkedChanged.disconnect()
        self.cookies_checkbox.checkedChanged.disconnect()
        self.rb_cookie_file.toggled.disconnect()
        self.cookies_btn.clicked.disconnect()
        self.cookie_browser_combo.currentIndexChanged.disconnect()
        for combo in self.quality_combos.values():
            combo.currentIndexChanged.disconnect()

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

    def update_translations(self):
        widgets_with_keys = self.findChildren(QWidget)
        for widget in widgets_with_keys:
            key = widget.property("text_key")
            if key and hasattr(widget, 'setText'):
                widget.setText(self.translator.translate(key))

            title_key = widget.property("title_key")
            if title_key and hasattr(widget, 'setTitle'):
                widget.setTitle(self.translator.translate(title_key))

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

        cookie_source_type = self.settings.value('cookie_source_type', 'file')
        self.rb_cookie_file.setChecked(cookie_source_type == 'file')
        self.rb_cookie_browser.setChecked(cookie_source_type == 'browser')

        cookies_path = self.settings.value('cookies_path', '')
        if cookies_path:
            self.cookies_lbl.setText(f'<a href="file:///{cookies_path}">{cookies_path}</a>')
        else:
            self.cookies_lbl.setText(self.translator.translate('file_not_selected'))

        cookie_browser = self.settings.value('cookie_browser', 'none')
        self.set_combo_by_data(self.cookie_browser_combo, cookie_browser)

        self.update_cookie_widgets_state()

        for platform_name, combo in self.quality_combos.items():
            key = f"quality_{platform_name.lower().replace(' ', '_').replace('(', '').replace(')', '')}"
            default_quality = 'bestvideo+bestaudio/best' if platform_name == 'YouTube' else 'best'
            quality = self.settings.value(key, default_quality)
            self.set_combo_by_data(combo, quality)

        self.connect_signals()

    def on_setting_changed(self):
        self.settings.setValue('theme', self.theme_combo.currentData())
        self.settings.setValue('parallel_downloads', self.parallel_downloads_spin.value())
        self.parent_window.thread_pool.setMaxThreadCount(self.parallel_downloads_spin.value())

        self.settings.setValue('subtitles_enabled', self.subtitles_checkbox.isChecked())
        self.settings.setValue('sponsorblock_enabled', self.sponsorblock_checkbox.isChecked())
        self.settings.setValue('use_cookies', self.cookies_checkbox.isChecked())

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