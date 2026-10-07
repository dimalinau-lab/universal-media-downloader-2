import os
import queue
import time
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
        self._sender_thread = None
        self._msg_queue = queue.Queue()
        self._is_running = False
        self.last_chat_id = None
        self.current_token = None

    def start_bot(self, token):
        if self._is_running and getattr(self, 'current_token', None) == token:
            return

        if self._is_running:
            self.stop_bot()

        self.current_token = token
        self.bot = telebot.TeleBot(token)
        self._is_running = True

        saved_chat_id = self.settings.value('tg_admin_chat_id', None)
        if saved_chat_id:
            try:
                self.last_chat_id = int(saved_chat_id)
            except (ValueError, TypeError):
                self.last_chat_id = saved_chat_id

        @self.bot.message_handler(content_types=['text'])
        def handle_message(message):
            user_id = str(message.from_user.id if message.from_user else message.chat.id)
            admin_id = str(self.settings.value('tg_admin_chat_id', '') or '')

            # Автоматическая привязка к первому обратившемуся владельцу
            if not admin_id:
                admin_id = str(message.chat.id)
                self.settings.setValue('tg_admin_chat_id', admin_id)
                self.settings.sync()
                self.last_chat_id = message.chat.id
                self.bot.reply_to(message, "🔒 Бот успешно привязан к вашему аккаунту! Теперь только вы можете управлять загрузками.")

            if str(message.chat.id) != admin_id and user_id != admin_id:
                self.bot.reply_to(message, "⛔ Доступ ограничен. Этот бот привязан к личному ПК другого пользователя.")
                return

            self.last_chat_id = message.chat.id
            text = message.text.strip()

            if text.startswith('http://') or text.startswith('https://'):
                self.signals.url_received.emit(text)
                self.bot.reply_to(message, "Ссылка поймана! Анализирую видео...")
            elif text.startswith('/start'):
                self.bot.reply_to(message, "Привет! Я на связи. Отправь мне ссылку, и загрузка начнется автоматически.")
            elif text.startswith('/unbind'):
                self.settings.remove('tg_admin_chat_id')
                self.settings.sync()
                self.bot.reply_to(message, "🔓 Привязка снята. Напишите /start с нужного аккаунта для новой привязки.")
            else:
                self.bot.reply_to(message, "Просто отправь мне ссылку на видео, и я скачаю его!")

        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._sender_thread.start()

    def send_test_message(self):
        if not self.bot or not self._is_running:
            return False, "Бот не запущен."
        if not self.last_chat_id:
            return False, "Сначала напиши боту любое сообщение в Telegram, чтобы он узнал куда отвечать!"

        try:
            self.bot.send_message(self.last_chat_id,
                                  "Проверка связи: всё работает отлично! Бот готов к приему ссылок.",
                                  timeout=5)
            return True, "Тестовое сообщение отправлено в Telegram!"
        except Exception as e:
            return False, f"Ошибка отправки: {e}"

    def send_message(self, text):
        """Асинхронная неблокирующая отправка сообщения через очередь (безопасно для GUI потока)"""
        if not self._is_running or not self.last_chat_id:
            return False
        self._msg_queue.put(('msg', self.last_chat_id, text))
        return True

    def send_file(self, file_path, caption=""):
        """Асинхронная отправка скачанного медиафайла владельцу в Telegram"""
        if not self._is_running or not self.last_chat_id:
            return False
        if not file_path or not os.path.exists(file_path):
            return False
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > 49.0:
            self.send_message(f"⚠️ Файл '{os.path.basename(file_path)}' ({size_mb:.1f} MB) превышает лимит Telegram (50 MB) и сохранен на вашем ПК.")
            return False
        self._msg_queue.put(('file', self.last_chat_id, file_path, caption))
        return True

    def _send_loop(self):
        while self._is_running:
            try:
                item = self._msg_queue.get(timeout=1.0)
                if not self._is_running or not self.bot:
                    break
                try:
                    mode = item[0]
                    if mode == 'file':
                        _, chat_id, file_path, caption = item
                        ext = os.path.splitext(file_path)[1].lower()
                        with open(file_path, 'rb') as f:
                            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.ogg'):
                                self.bot.send_audio(chat_id, f, caption=caption, timeout=90)
                            elif ext in ('.mp4', '.mkv', '.webm', '.mov'):
                                self.bot.send_video(chat_id, f, caption=caption, timeout=120)
                            else:
                                self.bot.send_document(chat_id, f, caption=caption, timeout=90)
                    else:
                        _, chat_id, text = item
                        self.bot.send_message(chat_id, text, timeout=10)
                except Exception as e:
                    logger.error(f"Ошибка асинхронной отправки TG: {e}")
                finally:
                    self._msg_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Непредвиденная ошибка в очереди сообщений Telegram: {e}")

    def _poll(self):
        try:
            self.bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"Ошибка Telegram бота: {e}")
            self._is_running = False

    def stop_bot(self):
        self._is_running = False
        if self.bot:
            try:
                self.bot.stop_polling()
            except Exception:
                pass
        self.bot = None
        self.current_token = None