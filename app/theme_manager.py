from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from qfluentwidgets import setTheme, Theme, setThemeColor


class ThemeManager:
    def __init__(self, settings: QSettings):
        self.settings = settings

    def apply_theme(self):
        app = QApplication.instance()
        if app is None:
            return

        theme_str = self.settings.value('theme', 'dark')

        # Устанавливаем красивый синий акцентный цвет для Fluent-элементов
        setThemeColor('#005fb8')

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
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Roboto', sans-serif;
                font-size: 14px;
            }

            /* Главные фоны (Цвета как в Windows 11 Dark Mode) */
            #MainWindow { background-color: #202020; }
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

            /* Второстепенные старые кнопки (если остались) */
            #SecondaryButton {
                background-color: rgba(255, 255, 255, 0.06);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 6px;
                padding: 6px 16px;
            }
            #SecondaryButton:hover { background-color: rgba(255, 255, 255, 0.1); }
            #SecondaryButton:pressed { background-color: rgba(255, 255, 255, 0.03); }

            /* Обычный прогресс-бар (запасной) */
            #ItemProgressBar, QProgressBar {
                border: none;
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 3px;
                text-align: center;
                height: 6px;
            }
            #ItemProgressBar::chunk, QProgressBar::chunk {
                background-color: #005fb8;
                border-radius: 3px;
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
            QWidget {
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Roboto', sans-serif;
                font-size: 14px;
            }

            /* Главные фоны */
            #MainWindow { background-color: #f3f3f3; }
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

            /* Второстепенные старые кнопки */
            #SecondaryButton {
                background-color: rgba(0, 0, 0, 0.03);
                color: #000000;
                border: 1px solid rgba(0, 0, 0, 0.05);
                border-radius: 6px;
                padding: 6px 16px;
            }
            #SecondaryButton:hover { background-color: rgba(0, 0, 0, 0.06); }
            #SecondaryButton:pressed { background-color: rgba(0, 0, 0, 0.02); }

            /* Обычный прогресс-бар */
            #ItemProgressBar, QProgressBar {
                border: none;
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 3px;
                text-align: center;
                height: 6px;
            }
            #ItemProgressBar::chunk, QProgressBar::chunk {
                background-color: #005fb8;
                border-radius: 3px;
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