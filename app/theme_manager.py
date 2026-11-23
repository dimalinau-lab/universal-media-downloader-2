from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from qfluentwidgets import setTheme, Theme, setThemeColor


class ThemeManager:
    _accent_color_set = False

    def __init__(self, settings: QSettings, window=None):
        self.settings = settings
        self.window = window

    def apply_theme(self):
        theme_str = self.settings.value('theme', 'dark')

        if not ThemeManager._accent_color_set:
            setThemeColor('#005fb8')
            ThemeManager._accent_color_set = True

        if theme_str == 'dark':
            setTheme(Theme.DARK)
            stylesheet = self.get_dark_theme()
        else:
            setTheme(Theme.LIGHT)
            stylesheet = self.get_light_theme()

        target = self.window if self.window is not None else QApplication.instance()
        if target:
            target.setStyleSheet(stylesheet)

        if self.window is not None:
            if hasattr(self.window, 'update_theme_icons'):
                self.window.update_theme_icons()
            if hasattr(self.window, '_settings_page') and self.window._settings_page:
                if hasattr(self.window._settings_page, 'update_theme_icons'):
                    self.window._settings_page.update_theme_icons()
                if hasattr(self.window._settings_page, 'update_status_indicators'):
                    self.window._settings_page.update_status_indicators()
            if hasattr(self.window, '_about_page') and self.window._about_page:
                if hasattr(self.window._about_page, 'update_theme_icons'):
                    self.window._about_page.update_theme_icons()

    def get_dark_theme(self):
        return """
            #MainWindow, QDialog {
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Roboto', sans-serif;
                font-size: 14px;
            }

            /* Главные фоны (Цвета как в Windows 11 Dark Mode) */
            #MainWindow, QDialog { background-color: #202020; }
            #NavBar {
                background-color: #202020;
                border-right: 1px solid rgba(255, 255, 255, 0.05);
            }
            #TopBar, #BottomBar {
                background-color: #272727;
            }
            #TopBar { border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
            #BottomBar { border-top: 1px solid rgba(255, 255, 255, 0.05); }

            /* Карточки и списки */
            #EmptyCard, #DownloadItem {
                background-color: #272727;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px; /* Более строгий радиус Windows 11 */
            }
            #EmptyCard { padding: 24px; }

            QGroupBox#SettingsGroup {
                background-color: #272727;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                margin-top: 24px;
                padding: 16px;
            }
            QGroupBox#SettingsGroup::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 4px;
                color: #ffffff;
                font-weight: 500;
            }

            QToolTip {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }

            #DownloadsList, QTableWidget {
                background-color: transparent;
                border: none;
                outline: none;
            }
            QTableWidget::item { color: #ffffff; }
            QHeaderView::section {
                background-color: #272727;
                color: #ffffff;
                border: none;
                padding: 4px;
            }

            /* Тексты */
            QLabel, QCheckBox, QRadioButton { color: #ffffff; background: transparent; }
            #TitleLabel, #AboutTitleLabel { font-weight: 600; font-size: 15px; }
            #UrlLabel, #StatusLabelItem, #HintLabel, #EmptyListItem, #AboutVersionLabel { color: #a0a0a0; }
            #StatusLabelSuccess { color: #10b981 !important; font-weight: 600; }
            #StatusLabelWarning { color: #f59e0b !important; font-weight: 600; }
            #StatusLabelDanger { color: #ef4444 !important; font-weight: 600; }
            #AboutCard, #NotesCard {
                background-color: #272727;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            #AboutCard:hover, #NotesCard:hover {
                border: 1px solid rgba(255, 255, 255, 0.16);
            }
            #FeatureIconBadge {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            #AboutVersionBadge {
                background-color: rgba(255, 255, 255, 0.08);
                color: #e0e0e0;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            }

            /* Превью и бейджи карточки загрузки */
            #Thumbnail {
                background-color: #2b2b2b;
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.05);
            }
            QPushButton#BadgeQuality {
                background-color: rgba(0, 95, 184, 0.25);
                color: #60a5fa;
                border: 1px solid rgba(0, 95, 184, 0.45);
                border-radius: 6px;
                padding: 1px 8px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton#BadgeQuality:hover {
                background-color: #005fb8;
                color: #ffffff;
                border-color: #106ebe;
            }
            QPushButton#BadgeQuality:pressed {
                background-color: #005a9e;
            }
            #BadgeTimeRange {
                background-color: rgba(245, 158, 11, 0.15);
                color: #f59e0b;
                border: 1px solid rgba(245, 158, 11, 0.3);
                border-radius: 6px;
                padding: 1px 8px;
                font-weight: 600;
                font-size: 11px;
            }
            #SizeLabelItem {
                color: #60a5fa;
                font-weight: 600;
                font-size: 13px;
                font-family: monospace, sans-serif;
            }

            /* Сайдбар кнопки (Мягкое полупрозрачное наведение) */
            #NavButton {
                background-color: transparent;
                color: #ffffff;
                border: none;
                padding: 8px 12px;
                text-align: left;
                border-radius: 6px;
            }
            #NavButton:hover { background-color: rgba(255, 255, 255, 0.06); }
            #NavButton:pressed { background-color: rgba(255, 255, 255, 0.03); color: #aaaaaa; }

            /* Кнопки действий нижней панели */
            #ActionButton {
                background-color: #005fb8;
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
                font-weight: 500;
            }
            #ActionButton:hover { background-color: #106ebe; }
            #ActionButton:pressed { background-color: #005a9e; }

            /* Второстепенные кнопки */
            #SecondaryButton {
                background-color: rgba(255, 255, 255, 0.06);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
            }
            #SecondaryButton:hover { background-color: rgba(255, 255, 255, 0.1); }
            #SecondaryButton:pressed { background-color: rgba(255, 255, 255, 0.03); }

            /* Кнопка режима отрезка (таймкоды) */
            #TimerangeButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
            }
            #TimerangeButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
            }
            #TimerangeButton:pressed {
                background-color: rgba(255, 255, 255, 0.04);
            }
            #TimerangeButton:checked {
                background-color: #005fb8;
                border: 1px solid #106ebe;
            }
            #TimerangeButton:checked:hover {
                background-color: #106ebe;
            }

            /* Обычный прогресс-бар (запасной) */
            #ItemProgressBar, QProgressBar {
                border: none;
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                text-align: center;
                height: 6px;
            }
            #ItemProgressBar::chunk, QProgressBar::chunk {
                background-color: #005fb8;
                border-radius: 4px;
            }

            /* Защита базовых элементов от искажения */
            QComboBox, QSpinBox, QTextEdit {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                color: #ffffff;
                padding: 5px 10px;
            }
            QSpinBox::up-button, QSpinBox::down-button, QComboBox::drop-down {
                background: transparent;
                border: none;
            }
        """

    def get_light_theme(self):
        return """
            #MainWindow, QDialog {
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Roboto', sans-serif;
                font-size: 14px;
            }

            /* Главные фоны */
            #MainWindow, QDialog { background-color: #f3f3f3; }
            #NavBar {
                background-color: #f3f3f3;
                border-right: 1px solid rgba(0, 0, 0, 0.05);
            }
            #TopBar, #BottomBar {
                background-color: #ffffff;
            }
            #TopBar { border-bottom: 1px solid rgba(0, 0, 0, 0.05); }
            #BottomBar { border-top: 1px solid rgba(0, 0, 0, 0.05); }

            /* Карточки и списки */
            #EmptyCard, #DownloadItem {
                background-color: #ffffff;
                border: 1px solid rgba(0, 0, 0, 0.06);
                border-radius: 8px;
            }
            #EmptyCard { padding: 24px; }

            QGroupBox#SettingsGroup {
                background-color: #ffffff;
                border: 1px solid rgba(0, 0, 0, 0.06);
                border-radius: 8px;
                margin-top: 24px;
                padding: 16px;
            }
            QGroupBox#SettingsGroup::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 4px;
                color: #000000;
                font-weight: 500;
            }

            QToolTip {
                background-color: #f9f9f9;
                color: #202020;
                border: 1px solid rgba(0, 0, 0, 0.15);
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }

            #DownloadsList, QTableWidget {
                background-color: transparent;
                border: none;
                outline: none;
            }
            QTableWidget::item { color: #000000; }
            QHeaderView::section {
                background-color: #ffffff;
                color: #000000;
                border: none;
                padding: 4px;
            }

            /* Тексты */
            QLabel, QCheckBox, QRadioButton { color: #000000; background: transparent; }
            #TitleLabel, #AboutTitleLabel { font-weight: 600; font-size: 15px; }
            #UrlLabel, #StatusLabelItem, #HintLabel, #EmptyListItem, #AboutVersionLabel { color: #606060; }
            #StatusLabelSuccess { color: #107c41 !important; font-weight: 600; }
            #StatusLabelWarning { color: #b45309 !important; font-weight: 600; }
            #StatusLabelDanger { color: #dc2626 !important; font-weight: 600; }
            #AboutCard, #NotesCard {
                background-color: #ffffff;
                border: 1px solid rgba(0, 0, 0, 0.08);
                border-radius: 8px;
            }
            #AboutCard:hover, #NotesCard:hover {
                border: 1px solid rgba(0, 0, 0, 0.16);
            }
            #FeatureIconBadge {
                background-color: rgba(0, 0, 0, 0.03);
                border: 1px solid rgba(0, 0, 0, 0.06);
                border-radius: 8px;
            }
            #AboutVersionBadge {
                background-color: rgba(0, 0, 0, 0.06);
                color: #404040;
                border: 1px solid rgba(0, 0, 0, 0.1);
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            }

            /* Превью и бейджи карточки загрузки */
            #Thumbnail {
                background-color: #e8e8e8;
                border-radius: 8px;
                border: 1px solid rgba(0, 0, 0, 0.06);
            }
            QPushButton#BadgeQuality {
                background-color: rgba(0, 95, 184, 0.1);
                color: #005fb8;
                border: 1px solid rgba(0, 95, 184, 0.25);
                border-radius: 6px;
                padding: 1px 8px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton#BadgeQuality:hover {
                background-color: #005fb8;
                color: #ffffff;
                border-color: #005fb8;
            }
            QPushButton#BadgeQuality:pressed {
                background-color: #005a9e;
            }
            #BadgeTimeRange {
                background-color: rgba(180, 83, 9, 0.1);
                color: #b45309;
                border: 1px solid rgba(180, 83, 9, 0.25);
                border-radius: 6px;
                padding: 1px 8px;
                font-weight: 600;
                font-size: 11px;
            }
            #SizeLabelItem {
                color: #005fb8;
                font-weight: 600;
                font-size: 13px;
                font-family: monospace, sans-serif;
            }

            /* Сайдбар кнопки */
            #NavButton {
                background-color: transparent;
                color: #000000;
                border: none;
                padding: 8px 12px;
                text-align: left;
                border-radius: 6px;
            }
            #NavButton:hover { background-color: rgba(0, 0, 0, 0.04); }
            #NavButton:pressed { background-color: rgba(0, 0, 0, 0.02); color: #555555; }

            /* Кнопки действий нижней панели */
            #ActionButton {
                background-color: #005fb8;
                color: #ffffff;
                border: 1px solid rgba(0, 0, 0, 0.08);
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
                font-weight: 500;
            }
            #ActionButton:hover { background-color: #106ebe; }
            #ActionButton:pressed { background-color: #005a9e; }

            /* Второстепенные кнопки */
            #SecondaryButton {
                background-color: rgba(0, 0, 0, 0.04);
                color: #202020;
                border: 1px solid rgba(0, 0, 0, 0.08);
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
            }
            #SecondaryButton:hover { background-color: rgba(0, 0, 0, 0.07); }
            #SecondaryButton:pressed { background-color: rgba(0, 0, 0, 0.02); }

            /* Кнопка режима отрезка (таймкоды) */
            #TimerangeButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
            }
            #TimerangeButton:hover {
                background-color: rgba(0, 0, 0, 0.06);
            }
            #TimerangeButton:pressed {
                background-color: rgba(0, 0, 0, 0.03);
            }
            #TimerangeButton:checked {
                background-color: #005fb8;
                border: 1px solid #106ebe;
            }
            #TimerangeButton:checked:hover {
                background-color: #106ebe;
            }

            /* Обычный прогресс-бар */
            #ItemProgressBar, QProgressBar {
                border: none;
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 4px;
                text-align: center;
                height: 6px;
            }
            #ItemProgressBar::chunk, QProgressBar::chunk {
                background-color: #005fb8;
                border-radius: 4px;
            }

            /* Защита базовых элементов */
            QComboBox, QSpinBox, QTextEdit {
                background-color: rgba(0, 0, 0, 0.02);
                border: 1px solid rgba(0, 0, 0, 0.05);
                border-radius: 6px;
                color: #000000;
                padding: 5px 10px;
            }
            QSpinBox::up-button, QSpinBox::down-button, QComboBox::drop-down {
                background: transparent;
                border: none;
            }
        """