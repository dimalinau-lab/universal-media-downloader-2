import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt
from qfluentwidgets import (LineEdit, PushButton, BodyLabel,
                            StrongBodyLabel, InfoBar, InfoBarPosition, SingleDirectionScrollArea,
                            FluentIcon, IconWidget)

logger = logging.getLogger(__name__)


class TelegramTab(QWidget):
    def __init__(self, translator, bot_manager, settings, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.bot_manager = bot_manager
        self.settings = settings
        self.initUI()
        self.load_settings()

    def initUI(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Orientation.Vertical, parent=self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.enableTransparentBackground()
        self.scroll_area.setStyleSheet("SingleDirectionScrollArea, QScrollArea { border: none; background: transparent; }")

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self.scroll_content)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.title = StrongBodyLabel()
        self.title.setStyleSheet("font-size: 22px;")
        layout.addWidget(self.title)

        self.desc = BodyLabel()
        self.desc.setStyleSheet("color: #888888;")
        self.desc.setWordWrap(True)
        layout.addWidget(self.desc)

        token_layout = QHBoxLayout()
        self.token_input = LineEdit()
        self.token_input.setEchoMode(LineEdit.EchoMode.Password)

        self.token_label = BodyLabel()
        token_layout.addWidget(self.token_label)
        token_layout.addWidget(self.token_input, 1)
        layout.addLayout(token_layout)

        controls_layout = QHBoxLayout()
        self.btn_save = PushButton(FluentIcon.PLAY, "")
        self.btn_stop = PushButton(FluentIcon.PAUSE, "")
        self.btn_test = PushButton(FluentIcon.SYNC, "")
        self.btn_clear = PushButton(FluentIcon.DELETE, "")

        controls_layout.addWidget(self.btn_save)
        controls_layout.addWidget(self.btn_stop)
        controls_layout.addWidget(self.btn_test)
        controls_layout.addWidget(self.btn_clear)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 10, 0, 0)
        status_layout.setSpacing(8)
        self.status_icon = IconWidget(FluentIcon.CANCEL)
        self.status_icon.setFixedSize(16, 16)
        self.status_label = BodyLabel()
        self.status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.status_icon)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        self.btn_save.clicked.connect(self.start_bot)
        self.btn_stop.clicked.connect(self.stop_bot)
        self.btn_test.clicked.connect(self.test_bot)
        self.btn_clear.clicked.connect(self.clear_token)

        self.scroll_area.setWidget(self.scroll_content)
        outer_layout.addWidget(self.scroll_area)

        self.update_translations()

    def update_translations(self):
        self.title.setText(self.translator.translate('tg_title', 'Telegram Бот (Удаленное управление)'))
        self.desc.setText(self.translator.translate('tg_desc', 'Отправляй боту ссылки с телефона...'))
        self.token_input.setPlaceholderText(
            self.translator.translate('tg_token_placeholder', 'Вставь сюда токен от @BotFather...'))
        self.token_label.setText(self.translator.translate('tg_token_label', 'Токен бота:'))
        self.btn_save.setText(self.translator.translate('tg_btn_save', 'Сохранить и запустить'))
        self.btn_stop.setText(self.translator.translate('tg_btn_stop', 'Остановить'))
        self.btn_test.setText(self.translator.translate('tg_btn_test', 'Проверить бота'))
        self.btn_clear.setText(self.translator.translate('tg_btn_clear', 'Сбросить токен'))

        if getattr(self.bot_manager, '_is_running', False):
            self.status_icon.setIcon(FluentIcon.COMPLETED)
            self.status_label.setText(self.translator.translate('tg_status_on', 'Статус: В сети и ждет ссылки'))
        else:
            self.status_icon.setIcon(FluentIcon.CANCEL)
            self.status_label.setText(self.translator.translate('tg_status_off', 'Статус: Выключен'))

    def load_settings(self):
        token = self.settings.value('tg_bot_token', '')
        if token:
            self.token_input.setText(token)

        if getattr(self.bot_manager, '_is_running', False):
            self.status_icon.setIcon(FluentIcon.COMPLETED)
            self.status_label.setText(self.translator.translate('tg_status_on', 'Статус: В сети и ждет ссылки'))
            self.status_label.setStyleSheet("color: #28a745; font-weight: bold;")
            self.btn_save.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_test.setEnabled(True)
        else:
            self.status_icon.setIcon(FluentIcon.CANCEL)
            self.status_label.setText(self.translator.translate('tg_status_off', 'Статус: Выключен'))
            self.status_label.setStyleSheet("color: #dc3545; font-weight: bold;")
            self.btn_save.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_test.setEnabled(False)

    def start_bot(self):
        token = self.token_input.text().strip()
        if not token:
            InfoBar.error(self.translator.translate('error', 'Ошибка'),
                          self.translator.translate('tg_error_empty_token', 'Сначала введи токен бота!'), parent=self,
                          position=InfoBarPosition.TOP)
            return

        self.settings.setValue('tg_bot_token', token)
        self.settings.sync()

        try:
            self.bot_manager.start_bot(token)
            self.status_icon.setIcon(FluentIcon.COMPLETED)
            self.status_label.setText(self.translator.translate('tg_status_on', 'Статус: В сети и ждет ссылки'))
            self.status_label.setStyleSheet("color: #28a745; font-weight: bold;")
            self.btn_save.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_test.setEnabled(True)
            InfoBar.success(self.translator.translate('success', 'Успех'),
                            self.translator.translate('tg_success_start', 'Telegram-бот успешно запущен!'), parent=self,
                            position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error(self.translator.translate('error', 'Ошибка'),
                          f"{self.translator.translate('tg_error_start', 'Не удалось подключиться:')} {e}", parent=self,
                          position=InfoBarPosition.TOP)

    def stop_bot(self):
        self.bot_manager.stop_bot()
        self.status_icon.setIcon(FluentIcon.CANCEL)
        self.status_label.setText(self.translator.translate('tg_status_off', 'Статус: Выключен'))
        self.status_label.setStyleSheet("color: #dc3545; font-weight: bold;")
        self.btn_save.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_test.setEnabled(False)

    def clear_token(self):
        self.stop_bot()
        self.settings.remove('tg_bot_token')
        self.settings.remove('tg_admin_chat_id')
        self.settings.sync()
        self.token_input.clear()
        InfoBar.success(self.translator.translate('success', 'Успех'),
                        self.translator.translate('tg_success_clear', 'Токен успешно удален!'), parent=self,
                        position=InfoBarPosition.TOP)

    def test_bot(self):
        success, msg = self.bot_manager.send_test_message()
        if success:
            InfoBar.success(self.translator.translate('success', 'Успех'), msg, parent=self,
                            position=InfoBarPosition.TOP)
        else:
            InfoBar.warning(self.translator.translate('warning', 'Внимание'), msg, parent=self,
                            position=InfoBarPosition.TOP)