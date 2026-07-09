import threading
import logging
import telebot
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

class BotSignals(QObject):
    url_received = pyqtSignal(str)

class TelegramBotManager:
    def __init__(self, settings):
        self.settings = settings
        self.signals = BotSignals()
        self.bot = None
        self.thread = None
        self._is_running = False
        self.last_chat_id = None

    def start_bot(self, token):
        if self._is_running and getattr(self, 'current_token', None) == token:
            return

        if self._is_running:
            self.stop_bot()

        self.current_token = token
        self.bot = telebot.TeleBot(token)
        self._is_running = True

        @self.bot.message_handler(content_types=['text'])
        def handle_message(message):
            self.last_chat_id = message.chat.id
            text = message.text.strip()

            if text.startswith('http://') or text.startswith('https://'):
                self.signals.url_received.emit(text)
                self.bot.reply_to(message, "Ссылка поймана! Анализирую видео...")
            elif text.startswith('/start'):
                self.bot.reply_to(message, "Привет! Я на связи. Отправь мне ссылку, и загрузка начнется автоматически.")
            else:
                self.bot.reply_to(message, "Просто отправь мне ссылку на видео, и я скачаю его!")

        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def send_test_message(self):
        if not self.bot or not self._is_running:
            return False, "Бот не запущен."
        if not self.last_chat_id:
            return False, "Сначала напиши боту любое сообщение в Telegram, чтобы он узнал куда отвечать!"

        try:
            self.bot.send_message(self.last_chat_id,
                                  "Проверка связи: всё работает отлично! Бот готов к приему ссылок.")
            return True, "Тестовое сообщение отправлено в Telegram!"
        except Exception as e:
            return False, f"Ошибка отправки: {e}"

    def send_message(self, text):
        if not self.bot or not self._is_running:
            return False
        if not self.last_chat_id:
            return False

        try:
            self.bot.send_message(self.last_chat_id, text)
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки TG: {e}")
            return False

    def _poll(self):
        try:
            self.bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Ошибка Telegram бота: {e}")
            self._is_running = False

    def stop_bot(self):
        self._is_running = False
        if self.bot:
            self.bot.stop_polling()
        self.bot = None
        self.current_token = None