from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                             QListWidget, QListWidgetItem, QMessageBox)
from PyQt6.QtCore import Qt
from qfluentwidgets import (SearchLineEdit, PushButton, PrimaryPushButton,
                            SubtitleLabel, BodyLabel, CaptionLabel, LineEdit, isDarkTheme)


def parse_range_spec(raw: str) -> set[int]:
    """Разбирает строку диапазонов вида '1-10, 15, 20-30' в множество индексов."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return set()
    indices: set[int] = set()
    for part in cleaned.replace(';', ',').split(','):
        p = part.strip()
        if not p:
            continue
        if '-' in p:
            start_s, end_s = p.split('-', 1)
            s, e = int(start_s.strip()), int(end_s.strip())
            if s > e:
                s, e = e, s
            indices.update(range(s, e + 1))
        else:
            indices.add(int(p))
    return indices


class PlaylistDialog(QDialog):
    def __init__(self, entries, parent=None, translator=None):
        super().__init__(parent)
        if translator is None and hasattr(parent, 'translator'):
            translator = parent.translator
        self.translator = translator
        self.setWindowTitle(self.t("playlist_dialog_title", "Обнаружен плейлист / сезон"))
        self.resize(650, 600)
        self.entries = [e for e in entries if e]
        self.selected_urls = []
        self.initUI()

    def t(self, key, default):
        if self.translator and hasattr(self.translator, 'translate'):
            return self.translator.translate(key, default)
        return default

    def _is_dark_theme(self) -> bool:
        parent = self.parent()
        if parent is not None and hasattr(parent, 'settings') and parent.settings is not None:
            return parent.settings.value('theme', 'dark') == 'dark'
        return isDarkTheme()

    def initUI(self):
        is_dark = self._is_dark_theme()
        accent_color = "#29b6f6" if is_dark else "#0067c0"
        muted_color = "#999999" if is_dark else "#666666"
        list_bg = "rgba(255, 255, 255, 0.03)" if is_dark else "rgba(0, 0, 0, 0.02)"
        list_border = "rgba(255, 255, 255, 0.1)" if is_dark else "rgba(0, 0, 0, 0.12)"
        item_border = "rgba(255, 255, 255, 0.05)" if is_dark else "rgba(0, 0, 0, 0.06)"
        item_hover = "rgba(255, 255, 255, 0.08)" if is_dark else "rgba(0, 0, 0, 0.05)"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        top_header = QHBoxLayout()
        self.title_label = SubtitleLabel(f"{self.t('found_videos', 'Найдено видео')}: {len(self.entries)}")
        self.count_label = CaptionLabel()
        self.count_label.setStyleSheet(f"color: {accent_color}; font-weight: 600; font-size: 13px;")
        top_header.addWidget(self.title_label)
        top_header.addStretch()
        top_header.addWidget(self.count_label)
        layout.addLayout(top_header)

        self.desc_label = CaptionLabel(self.t('playlist_desc', "Выберите видео для загрузки:"))
        self.desc_label.setStyleSheet(f"color: {muted_color};")
        layout.addWidget(self.desc_label)

        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText(self.t('search_video_placeholder', "Поиск по названию..."))
        self.search_input.textChanged.connect(self.filter_list)
        layout.addWidget(self.search_input)

        # Панель выбора диапазона номеров (1-10, 15, 20-25)
        range_layout = QHBoxLayout()
        range_layout.setSpacing(8)
        self.range_input = LineEdit()
        self.range_input.setPlaceholderText(self.t('batch_range_placeholder', "Диапазон: 1-10, 15, 20-30"))
        self.range_input.returnPressed.connect(self.apply_range)

        self.btn_apply_range = PushButton(self.t('apply_range', "Выбрать диапазон"))
        self.btn_apply_range.clicked.connect(self.apply_range)

        range_layout.addWidget(self.range_input, 1)
        range_layout.addWidget(self.btn_apply_range)
        layout.addLayout(range_layout)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {list_bg};
                border: 1px solid {list_border};
                border-radius: 8px;
                padding: 5px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px;
                border-radius: 6px;
                border-bottom: 1px solid {item_border};
            }}
            QListWidget::item:hover {{
                background-color: {item_hover};
            }}
        """)

        for idx, entry in enumerate(self.entries, start=1):
            title = entry.get('title', 'Без названия')
            url = entry.get('url') or entry.get('webpage_url')

            if not url and entry.get('id'):
                url = f"https://www.youtube.com/watch?v={entry.get('id')}"

            if url:
                item_text = f"{idx}. {title}"
                item = QListWidgetItem(item_text)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, url)
                item.setData(Qt.ItemDataRole.UserRole + 1, idx)
                self.list_widget.addItem(item)

        self.list_widget.itemChanged.connect(self.update_count_label)
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_select_all = PushButton(self.t('batch_select_all', "Выбрать все"))
        self.btn_select_all.clicked.connect(self.select_all)

        self.btn_deselect_all = PushButton(self.t('batch_deselect_all', "Снять все"))
        self.btn_deselect_all.clicked.connect(self.deselect_all)

        self.btn_invert = PushButton(self.t('invert_selection', "Инвертировать"))
        self.btn_invert.clicked.connect(self.invert_selection)

        self.btn_ok = PrimaryPushButton(self.t('add_to_downloads', "Добавить в загрузки"))
        self.btn_ok.clicked.connect(self.accept_selection)

        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_deselect_all)
        btn_layout.addWidget(self.btn_invert)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)

        layout.addLayout(btn_layout)
        self.update_count_label()

    def update_count_label(self):
        total = self.list_widget.count()
        selected = sum(1 for i in range(total) if self.list_widget.item(i).checkState() == Qt.CheckState.Checked)
        tpl = self.t('batch_selected_count', "Выбрано: {selected} из {total}")
        self.count_label.setText(tpl.format(selected=selected, total=total))
        self.btn_ok.setEnabled(selected > 0)

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
        self.update_count_label()

    def deselect_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Unchecked)
        self.update_count_label()

    def invert_selection(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                new_state = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
                item.setCheckState(new_state)
        self.update_count_label()

    def apply_range(self):
        raw = self.range_input.text().strip()
        if not raw:
            return

        try:
            target_indices = parse_range_spec(raw)

            self.list_widget.blockSignals(True)
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                idx = item.data(Qt.ItemDataRole.UserRole + 1)
                if idx in target_indices:
                    item.setCheckState(Qt.CheckState.Checked)
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.blockSignals(False)
            self.update_count_label()
        except ValueError:
            QMessageBox.warning(
                self,
                self.t('invalid_range_title', "Ошибка формата"),
                self.t('invalid_range_msg', "Введите корректный диапазон номеров, например: 1-10, 15, 20-30")
            )

    def accept_selection(self):
        self.selected_urls = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self.selected_urls.append(item.data(Qt.ItemDataRole.UserRole))
        self.accept()