from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                             QListWidget, QListWidgetItem)
from PyQt6.QtCore import Qt
from qfluentwidgets import (SearchLineEdit, PushButton, PrimaryPushButton,
                            SubtitleLabel, BodyLabel)


class PlaylistDialog(QDialog):
    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Обнаружен плейлист / сезон")
        self.resize(600, 550)  # Сделали окно чуть больше
        self.entries = [e for e in entries if e]
        self.selected_urls = []
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(15)

        self.title_label = SubtitleLabel(f"Найдено видео: {len(self.entries)}")
        layout.addWidget(self.title_label)

        self.desc_label = BodyLabel("Выберите нужные для скачивания или воспользуйтесь поиском:")
        self.desc_label.setStyleSheet("color: gray;")
        layout.addWidget(self.desc_label)

        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("Поиск по названию видео...")
        self.search_input.textChanged.connect(self.filter_list)
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 5px;
                outline: none;
            }
            QListWidget::item {
                padding: 10px;
                border-radius: 6px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }
            QListWidget::item:hover {
                background-color: rgba(255, 255, 255, 0.08);
            }
        """)

        for entry in self.entries:
            title = entry.get('title', 'Без названия')
            url = entry.get('url') or entry.get('webpage_url')

            if not url and entry.get('id'):
                url = f"https://www.youtube.com/watch?v={entry.get('id')}"

            if url:
                item = QListWidgetItem(title)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, url)
                self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_select_all = PushButton("Выбрать все")
        self.btn_select_all.clicked.connect(self.select_all)

        self.btn_deselect_all = PushButton("Снять все")
        self.btn_deselect_all.clicked.connect(self.deselect_all)

        self.btn_ok = PrimaryPushButton("Добавить в загрузки")
        self.btn_ok.clicked.connect(self.accept_selection)

        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_deselect_all)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)

        layout.addLayout(btn_layout)

    def filter_list(self, text):
        search_text = text.lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if search_text in item.text().lower():
                item.setHidden(False)
            else:
                item.setHidden(True)


    def select_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)

    def deselect_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Unchecked)

    def accept_selection(self):
        self.selected_urls = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self.selected_urls.append(item.data(Qt.ItemDataRole.UserRole))
        self.accept()