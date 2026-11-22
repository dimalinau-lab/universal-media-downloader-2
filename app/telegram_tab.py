import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt
from qfluentwidgets import (LineEdit, PushButton, BodyLabel,
                            StrongBodyLabel, InfoBar, InfoBarPosition, SingleDirectionScrollArea,
                            FluentIcon, IconWidget, CheckBox)

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
        layout.setSpacing(18)
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
        status_layout.setContentsMargins(0, 6, 0, 0)
        status_layout.setSpacing(8)
        self.status_icon = IconWidget(FluentIcon.CANCEL)
        self.status_icon.setFixedSize(16, 16)
        self.status_label = BodyLabel()
        self.status_label.setStyleSheet("font-weight: 600;")
        status_layout.addWidget(self.status_icon)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        # Раздел 2: Безопасность и PIN-авторизация
        pin_layout = QHBoxLayout()
        pin_layout.setContentsMargins(0, 10, 0, 0)
        pin_layout.setSpacing(12)
        self.pin_title = BodyLabel("PIN для подключения:")
        self.pin_display = StrongBodyLabel("------")
        self.pin_display.setStyleSheet("font-size: 16px; color: #0078d4; font-weight: 700; letter-spacing: 2px;")
        self.btn_new_pin = PushButton(FluentIcon.SYNC, "Новый PIN")
        self.btn_new_pin.setFixedHeight(30)
        pin_layout.addWidget(self.pin_title)
        pin_layout.addWidget(self.pin_display)
        pin_layout.addWidget(self.btn_new_pin)
        pin_layout.addStretch()
        layout.addLayout(pin_layout)

        admin_layout = QHBoxLayout()
        admin_layout.setSpacing(12)
        self.admin_title = BodyLabel("Привязанный Chat ID:")
        self.admin_display = BodyLabel("Не привязан")
        self.admin_display.setStyleSheet("color: #888888;")
        self.btn_unbind = PushButton(FluentIcon.DELETE, "Сбросить")
        self.btn_unbind.setFixedHeight(30)
        admin_layout.addWidget(self.admin_title)
        admin_layout.addWidget(self.admin_display)
        admin_layout.addWidget(self.btn_unbind)
        admin_layout.addStretch()
        layout.addLayout(admin_layout)

        # Раздел 3: Функции и интерактивность
        self.cb_interactive_quality = CheckBox("Спрашивать качество видео (1080p, 720p, MP3) перед скачиванием в Telegram")
        self.cb_live_progress = CheckBox("Живой прогресс-бар скачивания в чате Telegram (с троттлингом)")
        self.cb_silent_mode = CheckBox("Тихий режим (отправка уведомлений бота без звука)")

        layout.addWidget(self.cb_interactive_quality)
        layout.addWidget(self.cb_live_progress)
        layout.addWidget(self.cb_silent_mode)

        self.btn_save.clicked.connect(self.start_bot)
        self.btn_stop.clicked.connect(self.stop_bot)
        self.btn_test.clicked.connect(self.test_bot)
        self.btn_clear.clicked.connect(self.clear_token)
        self.btn_new_pin.clicked.connect(self._on_new_pin)
        self.btn_unbind.clicked.connect(self._on_unbind)
        self.cb_interactive_quality.stateChanged.connect(self._on_quality_setting_changed)
        self.cb_live_progress.stateChanged.connect(self._on_progress_setting_changed)
        self.cb_silent_mode.stateChanged.connect(self._on_silent_setting_changed)
        self.bot_manager.signals.admin_paired.connect(self._on_admin_paired)

        self.scroll_area.setWidget(self.scroll_content)
        outer_layout.addWidget(self.scroll_area)

        self.update_translations()

    def update_translations(self):
        self.title.setText(self.translator.translate('tg_title', 'Telegram-бот'))
        self.desc.setText(self.translator.translate('tg_desc', 'Отправка ссылок боту для автоматической загрузки на ПК.'))
        self.token_input.setPlaceholderText(
            self.translator.translate('tg_token_placeholder', 'Токен @BotFather'))
        self.token_label.setText(self.translator.translate('tg_token_label', 'Токен бота:'))
        self.btn_save.setText(self.translator.translate('tg_btn_save', 'Сохранить и запустить'))
        self.btn_stop.setText(self.translator.translate('tg_btn_stop', 'Остановить'))
        self.btn_test.setText(self.translator.translate('tg_btn_test', 'Проверить бота'))
        self.btn_clear.setText(self.translator.translate('tg_btn_clear', 'Сбросить токен'))
        self.pin_title.setText(self.translator.translate('tg_pin_label', 'PIN для подключения:'))
        self.btn_new_pin.setText(self.translator.translate('tg_btn_new_pin', 'Новый PIN'))
        self.admin_title.setText(self.translator.translate('tg_admin_label', 'Привязанный Chat ID:'))
        self.btn_unbind.setText(self.translator.translate('tg_btn_unbind', 'Сбросить'))
        self.cb_interactive_quality.setText(self.translator.translate('tg_cb_quality', 'Спрашивать качество видео (1080p, 720p, MP3) перед скачиванием в Telegram'))
        self.cb_live_progress.setText(self.translator.translate('tg_cb_progress', 'Живой прогресс-бар скачивания в чате Telegram (с троттлингом)'))
        self.cb_silent_mode.setText(self.translator.translate('tg_cb_silent', 'Тихий режим (отправка уведомлений бота без звука)'))

        if getattr(self.bot_manager, '_is_running', False):
            self.status_icon.setIcon(FluentIcon.COMPLETED)
            self.status_label.setText(self.translator.translate('tg_status_on', 'В сети'))
        else:
            self.status_icon.setIcon(FluentIcon.CANCEL)
            self.status_label.setText(self.translator.translate('tg_status_off', 'Отключен'))

    def load_settings(self):
        token = self.settings.value('tg_bot_token', '')
        if token:
            self.token_input.setText(token)

        pin = self.bot_manager.get_or_create_pin()
        self.pin_display.setText(f"{pin[:3]}-{pin[3:]}")

        admin_id = getattr(self.bot_manager, '_admin_chat_id', '') or str(self.settings.value('tg_admin_chat_id', '') or '').strip()
        if admin_id and admin_id != 'None':
            self.admin_display.setText(str(admin_id))
            self.admin_display.setStyleSheet("color: #28a745; font-weight: 600;")
            self.btn_unbind.setEnabled(True)
        else:
            self.admin_display.setText("Не привязан (отправьте /auth PIN в чат)")
            self.admin_display.setStyleSheet("color: #888888;")
            self.btn_unbind.setEnabled(False)

        self.cb_interactive_quality.setChecked(self.settings.value('tg_interactive_quality', True, type=bool))
        self.cb_live_progress.setChecked(self.settings.value('tg_live_progress', True, type=bool))
        self.cb_silent_mode.setChecked(self.settings.value('tg_silent_mode', False, type=bool))

        if getattr(self.bot_manager, '_is_running', False):
            self.status_icon.setIcon(FluentIcon.COMPLETED)
            self.status_label.setText(self.translator.translate('tg_status_on', 'В сети'))
            self.status_label.setStyleSheet("color: #28a745; font-weight: 600;")
            self.btn_save.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_test.setEnabled(True)
        else:
            self.status_icon.setIcon(FluentIcon.CANCEL)
            self.status_label.setText(self.translator.translate('tg_status_off', 'Отключен'))
            self.status_label.setStyleSheet("color: #dc3545; font-weight: 600;")
            self.btn_save.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_test.setEnabled(False)

    def _on_new_pin(self):
        new_pin = self.bot_manager.generate_new_pin()
        self.pin_display.setText(f"{new_pin[:3]}-{new_pin[3:]}")
        InfoBar.info("PIN обновлен", f"Новый код для команды /auth: {new_pin[:3]}-{new_pin[3:]}", parent=self, position=InfoBarPosition.TOP)

    def _on_unbind(self):
        if hasattr(self.bot_manager, 'unbind_admin'):
            self.bot_manager.unbind_admin()
        else:
            self.settings.remove('tg_admin_chat_id')
            self.settings.remove('tg_whitelist_users')
            self.settings.sync()
        self.load_settings()
        InfoBar.success("Привязка снята", "Аккаунты отвязаны. Введите /auth с новым PIN в боте для повторного подключения.", parent=self, position=InfoBarPosition.TOP)

    def _on_admin_paired(self, chat_id):
        if chat_id and str(chat_id).strip() and str(chat_id).strip() != 'None':
            c_str = str(chat_id).strip()
            self.admin_display.setText(c_str)
            self.admin_display.setStyleSheet("color: #28a745; font-weight: 600;")
            self.btn_unbind.setEnabled(True)
            pin = self.bot_manager.get_or_create_pin()
            self.pin_display.setText(f"{pin[:3]}-{pin[3:]}")
            InfoBar.success("Telegram привязан", f"Бот успешно привязан к Chat ID: {c_str}", parent=self, position=InfoBarPosition.TOP)
        else:
            self.admin_display.setText("Не привязан (отправьте /auth PIN в чат)")
            self.admin_display.setStyleSheet("color: #888888;")
            self.btn_unbind.setEnabled(False)
            pin = self.bot_manager.get_or_create_pin()
            self.pin_display.setText(f"{pin[:3]}-{pin[3:]}")

    def _on_quality_setting_changed(self, state):
        self.settings.setValue('tg_interactive_quality', bool(state))
        self.settings.sync()

    def _on_progress_setting_changed(self, state):
        self.settings.setValue('tg_live_progress', bool(state))
        self.settings.sync()

    def _on_silent_setting_changed(self, state):
        self.settings.setValue('tg_silent_mode', bool(state))
        self.settings.sync()

    def start_bot(self):
        token = self.token_input.text().strip()
        if not token:
            InfoBar.error(self.translator.translate('error', 'Ошибка'),
                          self.translator.translate('tg_error_empty_token', 'Введите токен бота'), parent=self,
                          position=InfoBarPosition.TOP)
            return

        self.settings.setValue('tg_bot_token', token)
        self.settings.sync()

        try:
            self.bot_manager.start_bot(token)
            self.status_icon.setIcon(FluentIcon.COMPLETED)
            self.status_label.setText(self.translator.translate('tg_status_on', 'В сети'))
            self.status_label.setStyleSheet("color: #28a745; font-weight: 600;")
            self.btn_save.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_test.setEnabled(True)
            InfoBar.success(self.translator.translate('success', 'Успех'),
                            self.translator.translate('tg_success_start', 'Telegram-бот запущен'), parent=self,
                            position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error(self.translator.translate('error', 'Ошибка'),
                          f"{self.translator.translate('tg_error_start', 'Не удалось подключиться:')} {e}", parent=self,
                          position=InfoBarPosition.TOP)

    def stop_bot(self):
        self.bot_manager.stop_bot()
        self.status_icon.setIcon(FluentIcon.CANCEL)
        self.status_label.setText(self.translator.translate('tg_status_off', 'Отключен'))
        self.status_label.setStyleSheet("color: #dc3545; font-weight: 600;")
        self.btn_save.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_test.setEnabled(False)

    def clear_token(self):
        self.stop_bot()
        self.settings.remove('tg_bot_token')
        if hasattr(self.bot_manager, 'unbind_admin'):
            self.bot_manager.unbind_admin()
        else:
            self.settings.remove('tg_admin_chat_id')
            self.settings.sync()
        self.token_input.clear()
        self.load_settings()
        InfoBar.success(self.translator.translate('success', 'Успех'),
                        self.translator.translate('tg_success_clear', 'Токен удален'), parent=self,
                        position=InfoBarPosition.TOP)

    def test_bot(self):
        success, msg = self.bot_manager.send_test_message()
        if success:
            InfoBar.success(self.translator.translate('success', 'Успех'), msg, parent=self,
                            position=InfoBarPosition.TOP)
        else:
            InfoBar.warning(self.translator.translate('warning', 'Внимание'), msg, parent=self,
                            position=InfoBarPosition.TOP)
