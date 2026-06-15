from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication


class ThemeManager:
    def __init__(self, settings: QSettings):
        self.settings = settings

    def apply_theme(self):
        app = QApplication.instance()
        if app is None:
            return
        theme = self.settings.value('theme', 'dark')
        stylesheet = self.get_dark_theme() if theme == 'dark' else self.get_light_theme()
        app.setStyleSheet(stylesheet)

    def get_dark_theme(self):
        return """
            QWidget {
                background-color: #1c1c1e;
                color: #e0e0e0;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                font-size: 14px;
            }
            QWidget:disabled {
                background-color: #1f1f21;
                color: #8a8a8a;
            }
            QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QPushButton:disabled, QCheckBox:disabled, QRadioButton:disabled {
                background-color: #2a2a2c;
                border: 1px solid #3a3a3c;
                color: #8a8a8a;
            }
            #MainWindow {
                background-color: #1c1c1e;
            }
            #TopBar, #BottomBar {
                background-color: #2a2a2c;
                border-bottom: 1px solid #3a3a3c;
            }
            #BottomBar {
                border-top: 1px solid #3a3a3c;
                border-bottom: none;
            }
            #NavBar {
                background-color: #252527;
                border-right: 1px solid #3a3a3c;
            }
            #UrlInput {
                background-color: #3a3a3c;
                border: 1px solid #505052;
                border-radius: 5px;
                padding: 5px 10px;
            }
            #UrlInput:focus {
                border: 1px solid #007acc;
            }
            #AddUrlButton, #LoadFileButton, #SecondaryButton {
                background-color: #3a3a3c;
                border: 1px solid #505052;
                border-radius: 17px;
                min-width: 34px;
                min-height: 34px;
            }
            #SecondaryButton {
                border-radius: 6px;
                padding: 6px 10px;
                min-width: 0px;
                min-height: 0px;
            }
            #AddUrlButton:hover, #LoadFileButton:hover, #SecondaryButton:hover {
                background-color: #4f4f4f;
            }
            #DownloadsList {
                background-color: #1c1c1e;
                border: none;
            }
            #DownloadItem {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2a2a2c, stop:1 #252527);
                border-radius: 8px;
                border: 1px solid #3a3a3c;
            }
            #RemoveButton {
                background-color: #2b2b2d;
                border: 1px solid #505052;
                border-radius: 6px;
            }
            #RemoveButton:hover {
                background-color: #3c3c3e;
            }
            #Thumbnail {
                background-color: #3a3a3c;
                border-radius: 4px;
            }
            #TitleLabel {
                font-size: 15px;
                font-weight: bold;
            }
            #UrlLabel, #StatusLabelItem, #PlaceholderLabel, #HintLabel {
                color: #9e9e9e;
                background-color: transparent;
            }
            QLabel { background-color: transparent; }
            #ItemProgressBar, QProgressBar {
                border: none;
                background-color: #3a3a3c;
                border-radius: 4px;
                text-align: center;
                color: #e0e0e0;
            }
            #ItemProgressBar::chunk, QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 4px;
            }
            #NavButton {
                background-color: transparent;
                border: none;
                padding: 10px;
                text-align: left;
                border-radius: 5px;
            }
            #NavButton:hover {
                background-color: #3a3a3c;
            }
            #ActionButton, #AboutButton {
                background-color: #007acc;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }
            #ActionButton:hover, #AboutButton:hover {
                background-color: #0095ff;
            }
            #ActionButton:disabled {
                background-color: #555555;
                color: #888888;
            }
            QComboBox, QSpinBox {
                background-color: #3a3a3c;
                border: 1px solid #505052;
                border-radius: 5px;
                padding: 5px;
            }
            QComboBox:hover, QSpinBox:hover {
                border: 1px solid #6a6a6c;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #3a3a3c;
                border: 1px solid #505052;
                selection-background-color: #007acc;
                color: #e0e0e0;
                outline: 0px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border;
                width: 18px;
                border-left: 1px solid #505052;
                background: #3a3a3c;
            }
            QScrollBar:vertical {
                border: none;
                background: #2a2a2c;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #505052;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QGroupBox#SettingsGroup {
                background-color: #1f1f21;
                border: 1px solid #3a3a3c;
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px;
            }
            QGroupBox#SettingsGroup::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                background-color: #1c1c1e;
            }
            QGroupBox#SettingsGroup QWidget {
                background-color: transparent;
            }
            #EmptyCard {
                background-color: #232326;
                border: 1px solid #3a3a3c;
                border-radius: 12px;
                padding: 24px;
            }
            #EmptyCard QWidget {
                background-color: transparent;
            }
            #EmptyTitle {
                font-size: 18px;
                font-weight: 600;
            }
            #EmptyListItem {
                color: #bdbdbd;
            }
            #QuickActions {
                background-color: transparent;
            }
            #RocketEmoji {
                font-size: 20px;
            }
            #AboutTitleLabel { font-size: 24px; font-weight: bold; }
            #AboutVersionLabel { font-size: 14px; color: #9e9e9e; }
            #AboutAuthorLabel { font-size: 16px; }
            #AboutDescriptionLabel { font-size: 14px; }
            QToolTip {
                background-color: #3a3a3c;
                color: #e0e0e0;
                border: 1px solid #505052;
            }
            QTableWidget {
                background-color: #1c1c1e;
                alternate-background-color: #232326;
                gridline-color: #3a3a3c;
                border: 1px solid #3a3a3c;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 8px;
                color: #e0e0e0;
            }
            QTableWidget::item:selected {
                background-color: #007acc;
                color: white;
            }
            QHeaderView::section {
                background-color: #2a2a2c;
                color: #e0e0e0;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #3a3a3c;
                font-weight: bold;
            }
            QHeaderView::section:hover {
                background-color: #3a3a3c;
            }
        """

    def get_light_theme(self):
        return """
            QWidget {
                background-color: #f0f2f5;
                color: #1e1e1e;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                font-size: 14px;
            }
            QWidget:disabled {
                background-color: #f3f4f6;
                color: #9aa0a6;
            }
            QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QPushButton:disabled, QCheckBox:disabled, QRadioButton:disabled {
                background-color: #ededed;
                border: 1px solid #dcdfe3;
                color: #9aa0a6;
            }
            #MainWindow {
                background-color: #f0f2f5;
            }
            #TopBar, #BottomBar {
                background-color: #ffffff;
                border-bottom: 1px solid #dcdfe3;
            }
            #BottomBar {
                border-top: 1px solid #dcdfe3;
                border-bottom: none;
            }
            #NavBar {
                background-color: #f7f9fa;
                border-right: 1px solid #dcdfe3;
            }
            #UrlInput {
                background-color: #ffffff;
                border: 1px solid #dcdfe3;
                border-radius: 5px;
                padding: 5px 10px;
            }
            #UrlInput:focus {
                border: 1px solid #007acc;
            }
            #AddUrlButton, #LoadFileButton, #SecondaryButton {
                background-color: #ffffff;
                border: 1px solid #dcdfe3;
                border-radius: 17px;
                min-width: 34px;
                min-height: 34px;
            }
            #SecondaryButton {
                border-radius: 6px;
                padding: 6px 10px;
                min-width: 0px;
                min-height: 0px;
            }
            #AddUrlButton:hover, #LoadFileButton:hover, #SecondaryButton:hover {
                background-color: #f5f5f5;
            }
            #DownloadsList {
                background-color: #f0f2f5;
                border: none;
            }
            #DownloadItem {
                background-color: #ffffff;
                border-radius: 8px;
                border: 1px solid #dcdfe3;
            }
            #RemoveButton {
                background-color: #ffffff;
                border: 1px solid #dcdfe3;
                border-radius: 6px;
            }
            #RemoveButton:hover {
                background-color: #f5f5f5;
            }
            #Thumbnail {
                background-color: #e0e0e0;
                border-radius: 4px;
            }
            #TitleLabel {
                font-size: 15px;
                font-weight: bold;
            }
            #UrlLabel, #StatusLabelItem, #PlaceholderLabel, #HintLabel {
                color: #666666;
                background-color: transparent;
            }
            QLabel { background-color: transparent; }
            #ItemProgressBar, QProgressBar {
                border: none;
                background-color: #e0e0e0;
                border-radius: 4px;
                text-align: center;
                color: #1e1e1e;
            }
            #ItemProgressBar::chunk, QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 4px;
            }
            #NavButton {
                background-color: transparent;
                border: none;
                padding: 10px;
                text-align: left;
                border-radius: 5px;
            }
            #NavButton:hover {
                background-color: #e8e8e8;
            }
            #ActionButton, #AboutButton {
                background-color: #007acc;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
            }
            #ActionButton:hover, #AboutButton:hover {
                background-color: #0095ff;
            }
            #ActionButton:disabled {
                background-color: #dcdfe3;
                color: #aaaaaa;
            }
            QComboBox, QSpinBox {
                background-color: #ffffff;
                border: 1px solid #dcdfe3;
                border-radius: 5px;
                padding: 5px;
            }
            QComboBox:hover, QSpinBox:hover {
                 border: 1px solid #c0c4c7;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                border: 1px solid #dcdfe3;
                selection-background-color: #007acc;
                color: #1e1e1e;
                outline: 0px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border;
                width: 18px;
                border-left: 1px solid #dcdfe3;
                background: #ffffff;
            }
            QScrollBar:vertical {
                border: none;
                background: #f0f2f5;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #dcdfe3;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QGroupBox#SettingsGroup {
                background-color: #ffffff;
                border: 1px solid #dcdfe3;
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px;
            }
            QGroupBox#SettingsGroup::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                background-color: #f0f2f5;
            }
            QGroupBox#SettingsGroup QWidget {
                background-color: transparent;
            }
            #EmptyCard {
                background-color: #ffffff;
                border: 1px solid #dcdfe3;
                border-radius: 12px;
                padding: 24px;
            }
            #EmptyCard QWidget {
                background-color: transparent;
            }
            #EmptyTitle {
                font-size: 18px;
                font-weight: 600;
            }
            #EmptyListItem {
                color: #444;
            }
            #QuickActions {
                background-color: transparent;
            }
            #RocketEmoji {
                font-size: 20px;
            }
            #AboutTitleLabel { font-size: 24px; font-weight: bold; }
            #AboutVersionLabel { font-size: 14px; color: #666666; }
            #AboutAuthorLabel { font-size: 16px; }
            #AboutDescriptionLabel { font-size: 14px; }
            QToolTip {
                background-color: #ffffff;
                color: #1e1e1e;
                border: 1px solid #dcdfe3;
            }
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f7f9fa;
                gridline-color: #dcdfe3;
                border: 1px solid #dcdfe3;
                border-radius: 6px;
            }
            QTableWidget::item {
                padding: 8px;
                color: #1e1e1e;
            }
            QTableWidget::item:selected {
                background-color: #007acc;
                color: white;
            }
            QHeaderView::section {
                background-color: #f0f2f5;
                color: #1e1e1e;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #dcdfe3;
                font-weight: bold;
            }
            QHeaderView::section:hover {
                background-color: #e8e8e8;
            }
        """
