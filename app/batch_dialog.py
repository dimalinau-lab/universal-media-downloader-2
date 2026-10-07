import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QPlainTextEdit, QLabel, QApplication, QMessageBox
)
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    PrimaryPushButton, PushButton, TransparentToolButton,
    FluentIcon, ComboBox, StrongBodyLabel, BodyLabel, CaptionLabel
)


class BatchAddDialog(QDialog):
    """
    Диалог пакетного добавления списка ссылок.
    Позволяет вставить десятки ссылок разом, удалить дубликаты,
    выбрать единый профиль качества и отправить в очередь загрузки.
    """
    def __init__(self, translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.selected_urls = []
        self.quality_override = None

        self.setWindowTitle(self.translator.translate('batch_dialog_title', "Пакетное добавление ссылок"))
        self.setMinimumSize(620, 520)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Заголовок и описание
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        title = StrongBodyLabel(self.translator.translate('batch_dialog_header', "Добавление нескольких ссылок"))
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        desc = CaptionLabel(self.translator.translate(
            'batch_dialog_desc',
            "Вставьте список ссылок (каждая с новой строки или через пробел). Дубликаты будут проверены автоматически."
        ))
        desc.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        layout.addLayout(header_layout)

        # Текстовое поле для ссылок
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "https://www.youtube.com/watch?v=...\n"
            "https://animego.me/anime/...\n"
            "https://www.tiktok.com/@.../video/...\n"
            "https://vk.com/video..."
        )
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit, 1)

        # Панель быстрых действий над списком
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        self.btn_paste = PushButton(FluentIcon.PASTE, self.translator.translate('paste_from_clipboard', "Вставить"))
        self.btn_paste.clicked.connect(self._paste_clipboard)

        self.btn_dedup = PushButton(FluentIcon.SYNC, self.translator.translate('remove_duplicates', "Удалить дубли"))
        self.btn_dedup.clicked.connect(self._remove_duplicates)

        self.btn_clear = PushButton(FluentIcon.DELETE, self.translator.translate('clear_all', "Очистить"))
        self.btn_clear.clicked.connect(self.text_edit.clear)

        self.lbl_stats = BodyLabel("Найдено ссылок: 0")
        self.lbl_stats.setStyleSheet("color: #0078D7; font-weight: bold;")

        actions_layout.addWidget(self.btn_paste)
        actions_layout.addWidget(self.btn_dedup)
        actions_layout.addWidget(self.btn_clear)
        actions_layout.addStretch()
        actions_layout.addWidget(self.lbl_stats)
        layout.addLayout(actions_layout)

        # Выбор общего профиля качества для пакета
        options_box = QHBoxLayout()
        options_box.setSpacing(12)

        lbl_profile = BodyLabel(self.translator.translate('download_profile', "Профиль загрузки:"))
        self.combo_profile = ComboBox()
        self.combo_profile.setMinimumWidth(260)
        self.combo_profile.addItem(self.translator.translate('profile_default', "По умолчанию (из настроек)"), userData=None)
        self.combo_profile.addItem(self.translator.translate('profile_best_video', "Видео: Максимальное качество"), userData="best")
        self.combo_profile.addItem(self.translator.translate('profile_1080p', "Видео: 1080p (Full HD)"), userData="1080p")
        self.combo_profile.addItem(self.translator.translate('profile_720p', "Видео: 720p (Эконом)"), userData="720p")
        self.combo_profile.addItem(self.translator.translate('profile_audio_only', "Только аудио (Лучшее качество)"), userData="audio_only")
        self.combo_profile.addItem(self.translator.translate('profile_audio_mp3', "Только аудио (MP3 320k)"), userData="audio_mp3")

        options_box.addWidget(lbl_profile)
        options_box.addWidget(self.combo_profile)
        options_box.addStretch()
        layout.addLayout(options_box)

        # Нижняя панель кнопок диалога
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        self.btn_cancel = PushButton(self.translator.translate('cancel_action', "Отмена"))
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_submit = PrimaryPushButton(
            FluentIcon.DOWNLOAD,
            self.translator.translate('batch_add_to_queue', "Добавить в загрузки (0)")
        )
        self.btn_submit.setEnabled(False)
        self.btn_submit.clicked.connect(self._on_submit)

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_cancel)
        bottom_layout.addWidget(self.btn_submit)
        layout.addLayout(bottom_layout)

    def _extract_urls(self, text: str) -> list[str]:
        raw_urls = re.findall(r'https?://[^\s<>"]+', text)
        cleaned = []
        for u in raw_urls:
            u = u.strip().rstrip('.,;)]}>')
            if u and u not in cleaned:
                cleaned.append(u)
        return cleaned

    def _on_text_changed(self):
        text = self.text_edit.toPlainText()
        urls = self._extract_urls(text)
        count = len(urls)
        self.lbl_stats.setText(f"{self.translator.translate('found_links', 'Найдено ссылок')}: {count}")
        btn_text = f"{self.translator.translate('batch_add_to_queue', 'Добавить в загрузки')} ({count})"
        self.btn_submit.setText(btn_text)
        self.btn_submit.setEnabled(count > 0)

    def _paste_clipboard(self):
        clipboard_text = QApplication.clipboard().text()
        if clipboard_text:
            current = self.text_edit.toPlainText().strip()
            if current:
                self.text_edit.setPlainText(current + "\n" + clipboard_text)
            else:
                self.text_edit.setPlainText(clipboard_text)

    def _remove_duplicates(self):
        text = self.text_edit.toPlainText()
        urls = self._extract_urls(text)
        if urls:
            self.text_edit.setPlainText("\n".join(urls))

    def _on_submit(self):
        text = self.text_edit.toPlainText()
        urls = self._extract_urls(text)
        if not urls:
            QMessageBox.warning(
                self,
                self.translator.translate('warning', "Предупреждение"),
                self.translator.translate('no_valid_urls_found', "В введенном тексте не найдено корректных ссылок.")
            )
            return

        self.selected_urls = urls
        self.quality_override = self.combo_profile.currentData()
        self.accept()
