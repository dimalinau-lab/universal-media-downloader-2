from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from qfluentwidgets import setTheme, Theme


class ThemeManager:
    def __init__(self, settings: QSettings):
        self.settings = settings

    def apply_theme(self):
        app = QApplication.instance()
        if app is None:
            return

        theme_str = self.settings.value('theme', 'dark')

        if theme_str == 'dark':
            setTheme(Theme.DARK)
            stylesheet = self.get_dark_theme()
        else:
            setTheme(Theme.LIGHT)
            stylesheet = self.get_light_theme()

        app.setStyleSheet(stylesheet)

    def get_dark_theme(self):
        return """
            QWidget {
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                font-size: 14px;
            }
            /* Главные фоны */
            #MainWindow { background-color: #202020; }
            #NavBar {
                background-color: #202020;
                border-right: 1px solid #333333;
            }
            #TopBar, #BottomBar {
                background-color: #272727;
            }
            #TopBar { border-bottom: 1px solid #333333; }
            #BottomBar { border-top: 1px solid #333333; }

            /* Карточки и списки */
            #EmptyCard, #DownloadItem {
                background-color: #272727;
                border: 1px solid #333333;
                border-radius: 16px;
            }
            #EmptyCard { padding: 24px; }

            /* ИСПРАВЛЕНИЕ QGroupBox (Настройки) */
            QGroupBox#SettingsGroup {
                background-color: #272727;
                border: 1px solid #333333;
                border-radius: 16px;
                margin-top: 24px; /* Отступ сверху под заголовок */
                padding: 16px;
            }
            QGroupBox#SettingsGroup::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 16px;
                padding: 0 4px;
                color: #e0e0e0;
            }

            #DownloadsList, QTableWidget {
                background-color: #202020;
                border: none;
                outline: none;
                border-radius: 12px;
            }
            QTableWidget::item { color: #e0e0e0; }
            QHeaderView::section {
                background-color: #272727;
                color: #ffffff;
                border: none;
            }

            /* Тексты */
            QLabel, QCheckBox, QRadioButton { color: #ffffff; background: transparent; }
            #TitleLabel, #AboutTitleLabel { font-weight: bold; font-size: 15px; }
            #UrlLabel, #StatusLabelItem, #HintLabel, #EmptyListItem, #AboutVersionLabel { color: #aaaaaa; }

            /* Старые кнопки в меню */
            #NavButton {
                background-color: transparent;
                color: #ffffff;
                border: none;
                padding: 10px;
                text-align: left;
                border-radius: 10px;
            }
            #NavButton:hover { background-color: #333333; }

            /* Старые кнопки действий */
            #ActionButton, #SecondaryButton {
                background-color: #333333;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 16px;
                padding: 8px 16px;
            }
            #ActionButton:hover, #SecondaryButton:hover { background-color: #444444; }
            #ActionButton { background-color: #006FB8; border: none; font-weight: bold; }
            #ActionButton:hover { background-color: #007acc; }

            /* Прогресс-бар */
            #ItemProgressBar, QProgressBar {
                border: none;
                background-color: #333333;
                border-radius: 8px;
                text-align: center;
                height: 12px;
            }
            #ItemProgressBar::chunk, QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 8px;
            }

            /* Поля ввода и выпадающие списки */
            QComboBox, QSpinBox, QTextEdit {
                background-color: #272727;
                border: 1px solid #444444;
                border-radius: 10px;
                color: #ffffff;
                padding: 6px 12px;
            }

            /* ИСПРАВЛЕНИЕ: Убираем серые прямоугольники у стрелочек */
            QSpinBox::up-button, QSpinBox::down-button, QComboBox::drop-down {
                background: transparent;
                border: none;
                width: 24px;
            }
        """

    def get_light_theme(self):
        return """
            QWidget {
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                font-size: 14px;
            }
            /* Главные фоны */
            #MainWindow { background-color: #F3F3F3; }
            #NavBar {
                background-color: #F3F3F3;
                border-right: 1px solid #E5E5E5;
            }
            #TopBar, #BottomBar {
                background-color: #FFFFFF;
            }
            #TopBar { border-bottom: 1px solid #E5E5E5; }
            #BottomBar { border-top: 1px solid #E5E5E5; }

            /* Карточки и списки */
            #EmptyCard, #DownloadItem {
                background-color: #FFFFFF;
                border: 1px solid #E5E5E5;
                border-radius: 16px;
            }
            #EmptyCard { padding: 24px; }

            /* ИСПРАВЛЕНИЕ QGroupBox (Настройки) */
            QGroupBox#SettingsGroup {
                background-color: #FFFFFF;
                border: 1px solid #E5E5E5;
                border-radius: 16px;
                margin-top: 24px;
                padding: 16px;
            }
            QGroupBox#SettingsGroup::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 16px;
                padding: 0 4px;
                color: #000000;
            }

            #DownloadsList, QTableWidget {
                background-color: #F3F3F3;
                border: none;
                outline: none;
                border-radius: 12px;
            }
            QTableWidget::item { color: #000000; }
            QHeaderView::section {
                background-color: #FFFFFF;
                color: #000000;
                border: none;
            }

            /* Тексты */
            QLabel, QCheckBox, QRadioButton { color: #000000; background: transparent; }
            #TitleLabel, #AboutTitleLabel { font-weight: bold; font-size: 15px; }
            #UrlLabel, #StatusLabelItem, #HintLabel, #EmptyListItem, #AboutVersionLabel { color: #666666; }

            /* Старые кнопки в меню */
            #NavButton {
                background-color: transparent;
                color: #000000;
                border: none;
                padding: 10px;
                text-align: left;
                border-radius: 10px;
            }
            #NavButton:hover { background-color: #E5E5E5; }

            /* Старые кнопки действий */
            #ActionButton, #SecondaryButton {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #D1D1D1;
                border-radius: 16px;
                padding: 8px 16px;
            }
            #ActionButton:hover, #SecondaryButton:hover { background-color: #F0F0F0; }
            #ActionButton { background-color: #006FB8; color: white; border: none; font-weight: bold; }
            #ActionButton:hover { background-color: #007acc; }

            /* Прогресс-бар */
            #ItemProgressBar, QProgressBar {
                border: none;
                background-color: #E5E5E5;
                border-radius: 8px;
                text-align: center;
                height: 12px;
            }
            #ItemProgressBar::chunk, QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 8px;
            }

            /* Поля ввода и выпадающие списки */
            QComboBox, QSpinBox, QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #D1D1D1;
                border-radius: 10px;
                color: #000000;
                padding: 6px 12px;
            }

            /* ИСПРАВЛЕНИЕ: Убираем серые прямоугольники у стрелочек */
            QSpinBox::up-button, QSpinBox::down-button, QComboBox::drop-down {
                background: transparent;
                border: none;
                width: 24px;
            }
        """