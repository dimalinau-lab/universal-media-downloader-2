import os
import re
import queue
import time
import shutil
import socket
import urllib.parse
import threading
import logging
import html
import uuid
from http.server import HTTPServer, SimpleHTTPRequestHandler

class _LazyTelebot:
    _module = None

    def __getattr__(self, name):
        if _LazyTelebot._module is None:
            import telebot as _real
            _LazyTelebot._module = _real
        return getattr(_LazyTelebot._module, name)

telebot = _LazyTelebot()


class _LazyInlineKeyboardMarkup:
    def __new__(cls, *args, **kwargs):
        from telebot.types import InlineKeyboardMarkup as _Real
        return _Real(*args, **kwargs)


class _LazyInlineKeyboardButton:
    def __new__(cls, *args, **kwargs):
        from telebot.types import InlineKeyboardButton as _Real
        return _Real(*args, **kwargs)


InlineKeyboardMarkup = _LazyInlineKeyboardMarkup
InlineKeyboardButton = _LazyInlineKeyboardButton
from PyQt6.QtCore import QObject, pyqtSignal

class _TokenSanitizingFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = re.sub(r'bot\d+:[A-Za-z0-9_-]+', 'bot***:***', record.msg)
        return True

logger = logging.getLogger(__name__)
logger.addFilter(_TokenSanitizingFilter())


class BotSignals(QObject):
    url_received = pyqtSignal(object)
    dispatch_main = pyqtSignal(object, tuple)
    admin_paired = pyqtSignal(str)


class TelegramBotManager:
    def __init__(self, settings):
        self.settings = settings
        self.signals = BotSignals()
        self.signals.dispatch_main.connect(self._run_on_main_thread)
        self.bot = None
        self.download_manager = None
        self.main_window = None
        self.thread = None
        self._sender_thread = None
        self._msg_queue = queue.Queue()
        self._is_running = False
        self.last_chat_id = None
        self.current_token = None
        self._interactive_sessions = {}
        self._single_video_sessions = {}
        self._search_sessions = {}
        self._tracked_tasks = {}
        self._large_files = {}
        self._wifi_servers = []
        self._pin_attempts = {}

        # Надежное хранилище авторизации и PIN в оперативной памяти (защита от сбоев синхронизации потоков)
        saved_admin = str(self.settings.value('tg_admin_chat_id', '') or '').strip()
        self._admin_chat_id = saved_admin if saved_admin and saved_admin != 'None' else ''
        saved_pin = str(self.settings.value('tg_auth_pin', '') or '').strip()
        self._current_pin = saved_pin if (saved_pin and len(saved_pin) == 6 and saved_pin.isdigit()) else ''
        whitelist_raw = str(self.settings.value('tg_whitelist_users', '') or '').strip()
        self._whitelist_users = [w.strip() for w in whitelist_raw.split(',') if w.strip() and w.strip() != 'None']

    def _run_on_main_thread(self, fn, args):
        try:
            fn(*args)
        except Exception as e:
            logger.error(f"[TelegramBot] Ошибка выполнения в GUI потоке: {e}", exc_info=True)

    def dispatch_to_main_thread(self, fn, *args):
        self.signals.dispatch_main.emit(fn, args)

    # ------------------ БЕЗОПАСНОСТЬ И АВТОРИЗАЦИЯ ------------------

    def get_or_create_pin(self) -> str:
        if self._current_pin and len(self._current_pin) == 6 and self._current_pin.isdigit():
            return self._current_pin
        pin = str(self.settings.value('tg_auth_pin', '') or '').strip()
        if not pin or len(pin) != 6 or not pin.isdigit():
            import random
            pin = f"{random.randint(100000, 999999)}"
            self.settings.setValue('tg_auth_pin', pin)
            self.settings.sync()
        self._current_pin = pin
        return pin

    def generate_new_pin(self) -> str:
        import random
        pin = f"{random.randint(100000, 999999)}"
        self._current_pin = pin
        self.settings.setValue('tg_auth_pin', pin)
        self.settings.sync()
        return pin

    def is_user_authorized(self, chat_id, user_id=None) -> bool:
        admin_id = self._admin_chat_id or str(self.settings.value('tg_admin_chat_id', '') or '').strip()
        c_id = str(chat_id).strip()
        u_id = str(user_id).strip() if user_id else c_id

        # Если администратор не привязан — доступ строго заблокирован
        if not admin_id or admin_id == 'None':
            return False

        if c_id == admin_id or u_id == admin_id:
            return True

        whitelist = self._whitelist_users
        if not whitelist:
            whitelist_raw = str(self.settings.value('tg_whitelist_users', '') or '').strip()
            whitelist = [w.strip() for w in whitelist_raw.split(',') if w.strip() and w.strip() != 'None']
            self._whitelist_users = whitelist

        if c_id in whitelist or u_id in whitelist:
            return True

        return False

    def authorize_user(self, chat_id, user_id=None):
        c_str = str(chat_id).strip()
        if not self._admin_chat_id:
            self._admin_chat_id = c_str
            self.settings.setValue('tg_admin_chat_id', c_str)
            self.settings.sync()
            logger.info(f"[TelegramBot] Администратор успешно привязан: chat_id={c_str}")
            self.signals.admin_paired.emit(c_str)
        else:
            if c_str != self._admin_chat_id and c_str not in self._whitelist_users:
                self._whitelist_users.append(c_str)
                self.settings.setValue('tg_whitelist_users', ','.join(self._whitelist_users))
                self.settings.sync()
                logger.info(f"[TelegramBot] Пользователь добавлен в белый список: chat_id={c_str}")
        self.last_chat_id = chat_id

    def unbind_admin(self):
        self._admin_chat_id = ""
        self._whitelist_users = []
        self.settings.remove('tg_admin_chat_id')
        self.settings.remove('tg_whitelist_users')
        self.settings.sync()
        new_pin = self.generate_new_pin()
        logger.info("[TelegramBot] Привязка аккаунтов сброшена.")
        self.signals.admin_paired.emit("")
        return new_pin

    # ------------------ ЗАПУСК И ОБРАБОТЧИКИ БОТА ------------------

    def start_bot(self, token):
        if self._is_running and getattr(self, 'current_token', None) == token:
            return

        if self._is_running:
            self.stop_bot()

        self.current_token = token
        import telebot as _tb
        _tb.apihelper.CONNECT_TIMEOUT = 15
        _tb.apihelper.READ_TIMEOUT = 45
        self.bot = _tb.TeleBot(token)
        self._is_running = True

        saved_chat_id = self.settings.value('tg_admin_chat_id', None)
        if saved_chat_id:
            try:
                self.last_chat_id = int(saved_chat_id)
            except (ValueError, TypeError):
                self.last_chat_id = saved_chat_id

        # 1. Текстовые сообщения и команды
        @self.bot.message_handler(content_types=['text'])
        def handle_message(message):
            chat_id = message.chat.id
            user_id = str(message.from_user.id if message.from_user else chat_id)
            text = (message.text or "").strip()

            # Команда авторизации по PIN-коду доступна всем (с защитой от брутфорса)
            if text.startswith('/auth'):
                now = time.time()
                att = self._pin_attempts.setdefault(user_id, {'count': 0, 'blocked_until': 0})
                if now < att.get('blocked_until', 0):
                    rem_sec = int(att['blocked_until'] - now)
                    rem_min = (rem_sec // 60) + 1
                    self.bot.reply_to(
                        message,
                        f"🚫 <b>Ввод PIN временно заблокирован</b> из-за нескольких неверных попыток.\n"
                        f"Повторите попытку через {rem_min} мин.",
                        parse_mode='HTML'
                    )
                    return

                parts = text.split()
                if len(parts) >= 2:
                    code = parts[1].replace('-', '').strip()
                    current_pin = self.get_or_create_pin()
                    if code == current_pin:
                        self._pin_attempts.pop(user_id, None)
                        self.authorize_user(chat_id, user_id)
                        self.generate_new_pin()
                        self.bot.reply_to(message, "✅ <b>Авторизация успешна!</b>\nВаш аккаунт привязан к UMD.", parse_mode='HTML')
                    else:
                        att['count'] = att.get('count', 0) + 1
                        if att['count'] >= 3:
                            att['blocked_until'] = now + 900  # Блокировка на 15 минут
                            logger.warning(f"[Security] Превышен лимит попыток PIN для user_id={user_id}. Блокировка 15 минут.")
                            self.bot.reply_to(
                                message,
                                "🚫 <b>Превышен лимит попыток.</b> Ввод PIN заблокирован на 15 минут.",
                                parse_mode='HTML'
                            )
                        else:
                            left = 3 - att['count']
                            self.bot.reply_to(message, f"❌ Неверный PIN-код. Осталось попыток: {left}.")
                else:
                    self.bot.reply_to(
                        message,
                        "Использование: <code>/auth 123-456</code> (введите 6-значный PIN из вкладки «Telegram-бот» на ПК).",
                        parse_mode='HTML'
                    )
                return

            # Проверка авторизации
            if not self.is_user_authorized(chat_id, user_id):
                self.bot.reply_to(
                    message,
                    "🔒 <b>Доступ ограничен.</b>\n"
                    "Для подключения введите команду с PIN-кодом из окна программы на ПК:\n"
                    "<code>/auth 123-456</code> (вместо 123-456 введите код из вкладки «Telegram-бот» на ПК)",
                    parse_mode='HTML'
                )
                return

            self.last_chat_id = chat_id

            # Диспетчеризация команд
            if text.startswith('/'):
                cmd_parts = text.split(maxsplit=1)
                cmd = cmd_parts[0].lower().replace('@' + (self.bot.get_me().username.lower() if self.bot and hasattr(self.bot, 'get_me') else ''), '')
                arg = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""
                self._dispatch_command(message, cmd, arg)
                return

            # Поиск всех URL в тексте (поддержка пакетов ссылок)
            urls = re.findall(r'https?://[^\s<>"]+', text)
            if urls:
                if len(urls) == 1:
                    self.signals.url_received.emit(urls[0])
                    self.bot.reply_to(message, "🔍 <b>Ссылка получена.</b> Выполняется анализ потоков...", parse_mode='HTML')
                else:
                    self.signals.url_received.emit(urls)
                    self.bot.reply_to(message, f"📥 <b>Пакетное добавление:</b> получено {len(urls)} ссылок. Все задачи поставлены в очередь.", parse_mode='HTML')
            else:
                self.bot.reply_to(message, "Отправьте ссылку на видео для загрузки или введите /help для списка команд.")

        # 2. Обработка документов (.txt с пакетом ссылок)
        @self.bot.message_handler(content_types=['document'])
        def handle_document(message):
            chat_id = message.chat.id
            user_id = str(message.from_user.id if message.from_user else chat_id)
            if not self.is_user_authorized(chat_id, user_id):
                self.bot.reply_to(message, "🔒 Доступ ограничен.")
                return

            doc = message.document
            if doc and doc.file_name and doc.file_name.lower().endswith(('.txt', '.list')):
                try:
                    file_info = self.bot.get_file(doc.file_id)
                    downloaded = self.bot.download_file(file_info.file_path)
                    content = downloaded.decode('utf-8', errors='ignore')
                    urls = re.findall(r'https?://[^\s<>"]+', content)
                    if urls:
                        self.signals.url_received.emit(urls)
                        self.bot.reply_to(message, f"📄 Из файла <b>'{html.escape(doc.file_name)}'</b> извлечено {len(urls)} ссылок. Они добавлены в очередь загрузки на ПК.", parse_mode='HTML')
                    else:
                        self.bot.reply_to(message, "В текстовом файле не найдено ссылок.")
                except Exception as e:
                    logger.error(f"[TelegramBot] Ошибка обработки файла: {e}")
                    self.bot.reply_to(message, f"Ошибка чтения файла: {e}")
            else:
                self.bot.reply_to(message, "Поддерживаются только текстовые файлы (.txt) со списком ссылок.")

        # 3. Инлайн-кнопки
        @self.bot.callback_query_handler(func=lambda _call: True)
        def handle_callback_query(call):
            self._handle_callback_query(call)

        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._sender_thread.start()

    # ------------------ ДИСПЕТЧЕРИЗАЦИЯ КОМАНД ------------------

    def _dispatch_command(self, message, cmd, arg):
        chat_id = message.chat.id

        if cmd in ('/start', '/help'):
            help_text = (
                "👋 <b>Universal Media Downloader Bot</b>\n\n"
                "Отправьте мне ссылку (YouTube, VK, Rutube, TikTok, фильм, аниме) или список ссылок — я сразу скачаю их на ПК.\n\n"
                "<b>Команды управления:</b>\n"
                "📊 /status — Текущие задачи, скорость и очередь\n"
                "🔎 /search <code>[запрос]</code> — Поиск и скачивание видео с YouTube\n"
                "⚡ /speed <code>[число]</code> — Установить лимит (напр. <code>/speed 5m</code> или меню)\n"
                "📋 /logs — Последние логи приложения с ПК\n"
                "🔕 /silent — Включить / выключить тихий режим уведомлений\n"
                "💾 /disk — Свободное место на дисках ПК\n"
                "⏸ /pause — Поставить скачивание на паузу\n"
                "▶️ /resume — Возобновить скачивание\n"
                "🧹 /clear — Очистить завершенные задачи\n"
                "🔌 /power — Выключение или спящий режим ПК\n"
                "🔐 /auth <code>[PIN]</code> — Привязать аккаунт\n"
                "🔓 /unbind — Сбросить привязку администратора"
            )
            self.bot.send_message(chat_id, help_text, parse_mode='HTML')

        elif cmd in ('/status', '/list'):
            text, markup = self._build_status_message()
            self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

        elif cmd in ('/search', '/find'):
            if not arg:
                self.bot.send_message(chat_id, "🔎 Использование: <code>/search <название видео></code> (например: <code>/search Suzume</code>)", parse_mode='HTML')
                return
            self.bot.send_message(chat_id, f"🔎 Ищу: <b>{html.escape(arg)}</b>...", parse_mode='HTML')
            threading.Thread(target=self._run_video_search, args=(chat_id, arg), daemon=True).start()

        elif cmd == '/disk':
            text = self._get_disk_info()
            self.bot.send_message(chat_id, text, parse_mode='HTML')

        elif cmd in ('/pause', '/stop'):
            if self.download_manager:
                self.dispatch_to_main_thread(self.download_manager.stop_all)
            self.bot.send_message(chat_id, "⏸ <b>Загрузки на ПК приостановлены.</b>", parse_mode='HTML')

        elif cmd in ('/resume', '/start_all'):
            if self.download_manager:
                self.dispatch_to_main_thread(self.download_manager.start_all)
            self.bot.send_message(chat_id, "▶️ <b>Загрузки на ПК возобновлены.</b>", parse_mode='HTML')

        elif cmd == '/clear':
            if self.download_manager:
                self.dispatch_to_main_thread(self.download_manager.clear_completed)
            self.bot.send_message(chat_id, "🧹 <b>Завершенные задачи очищены.</b>", parse_mode='HTML')

        elif cmd == '/speed':
            if not arg:
                curr_spd = self.settings.value('speed_limit', 0, type=int) or 0
                if curr_spd <= 0:
                    spd_str = "Без ограничений"
                elif curr_spd >= 1024 * 1024:
                    spd_str = f"{curr_spd / (1024 * 1024):.1f} МБ/с"
                else:
                    spd_str = f"{curr_spd // 1024} КБ/с"

                markup = InlineKeyboardMarkup()
                markup.row(
                    InlineKeyboardButton("⚡ Без лимита", callback_data="tgspd:0"),
                    InlineKeyboardButton("🐌 1 МБ/с", callback_data="tgspd:1m")
                )
                markup.row(
                    InlineKeyboardButton("🚀 3 МБ/с", callback_data="tgspd:3m"),
                    InlineKeyboardButton("🚀 5 МБ/с", callback_data="tgspd:5m"),
                    InlineKeyboardButton("🚀 10 МБ/с", callback_data="tgspd:10m")
                )
                self.bot.send_message(
                    chat_id,
                    f"⚡ Текущий лимит скорости: <b>{spd_str}</b>\n\n"
                    f"Выберите пресет ниже или задайте вручную: <code>/speed 5m</code> (5 МБ/с) или <code>/speed 500k</code>.",
                    reply_markup=markup,
                    parse_mode='HTML'
                )
                return

            limit_bytes = self._parse_speed_arg(arg)
            self._apply_speed_limit(limit_bytes)
            res_str = "Без ограничений" if limit_bytes <= 0 else f"{limit_bytes / (1024*1024):.1f} МБ/с"
            self.bot.send_message(chat_id, f"⚡ Лимит скорости установлен: <b>{res_str}</b>", parse_mode='HTML')

        elif cmd == '/logs':
            log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'app.log')
            if not os.path.exists(log_path):
                self.bot.send_message(chat_id, "Файл логов пока не создан.")
                return
            try:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                tail_lines = lines[-25:]
                raw_text = "".join(tail_lines)
                clean_text = re.sub(r'bot\d+:[A-Za-z0-9_-]+', 'bot***:***', raw_text)
                if len(clean_text) > 3800:
                    clean_text = clean_text[-3800:]
                self.bot.send_message(chat_id, f"📋 <b>Последние строки логов:</b>\n<pre>{html.escape(clean_text)}</pre>", parse_mode='HTML')
            except Exception as e:
                self.bot.send_message(chat_id, f"Ошибка чтения логов: {e}")

        elif cmd == '/silent':
            curr = self.settings.value('tg_silent_mode', False, type=bool)
            if arg.lower() in ('on', '1', 'true', 'да', 'вкл'):
                new_state = True
            elif arg.lower() in ('off', '0', 'false', 'нет', 'выкл'):
                new_state = False
            else:
                new_state = not curr
            self.settings.setValue('tg_silent_mode', new_state)
            self.settings.sync()
            if new_state:
                self.bot.send_message(chat_id, "🔕 <b>Тихий режим включен.</b> Все последующие уведомления будут приходить без звука.", parse_mode='HTML')
            else:
                self.bot.send_message(chat_id, "🔔 <b>Тихий режим выключен.</b> Звуковые уведомления активны.", parse_mode='HTML')

        elif cmd == '/power':
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("💤 Спящий режим", callback_data="tgpwr:sleep"),
                InlineKeyboardButton("🔌 Выключить ПК", callback_data="tgpwr:shutdown")
            )
            markup.row(InlineKeyboardButton("❌ Отмена", callback_data="tgpwr:cancel"))
            self.bot.send_message(chat_id, "⚡ <b>Управление питанием компьютера:</b>\nВыберите действие:", reply_markup=markup, parse_mode='HTML')

        elif cmd == '/unbind':
            self.unbind_admin()
            self.bot.send_message(chat_id, "🔓 <b>Привязка снята.</b> Теперь бот ждет нового подключения по /auth.", parse_mode='HTML')

        else:
            self.bot.send_message(chat_id, "Неизвестная команда. Введите /help для списка доступных команд.")

    def _parse_speed_arg(self, arg_str: str) -> int:
        arg_lower = (arg_str or "").strip().lower()
        if not arg_lower or arg_lower in ('0', 'unlimited', 'none', 'off'):
            return 0
        if arg_lower.endswith('m') or arg_lower.endswith('mb'):
            num = float(re.sub(r'[^\d\.]', '', arg_lower) or 0)
            return int(num * 1024 * 1024)
        elif arg_lower.endswith('k') or arg_lower.endswith('kb'):
            num = float(re.sub(r'[^\d\.]', '', arg_lower) or 0)
            return int(num * 1024)
        elif arg_lower.isdigit():
            num = int(arg_lower)
            return num * 1024 * 1024 if num < 500 else num
        return 0

    def _apply_speed_limit(self, limit_bytes: int):
        self.settings.setValue('speed_limit', limit_bytes)
        self.settings.sync()
        if hasattr(self, 'main_window') and self.main_window:
            self.dispatch_to_main_thread(self.main_window.set_quick_speed_limit, limit_bytes)

    def _run_video_search(self, chat_id, query):
        try:
            import yt_dlp
            ydl_opts = {
                'quiet': True,
                'skip_download': True,
                'extract_flat': 'in_playlist',
                'noplaylist': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(f"ytsearch3:{query}", download=False)

            entries = res.get('entries', []) if res else []
            if not entries:
                self.bot.send_message(chat_id, f"❌ По запросу <b>'{html.escape(query)}'</b> ничего не найдено.", parse_mode='HTML')
                return

            self.bot.send_message(chat_id, f"🔍 <b>Результаты поиска ({len(entries)}):</b>", parse_mode='HTML')
            for idx, entry in enumerate(entries[:3], 1):
                vid_id = entry.get('id')
                vid_url = entry.get('url') or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "")
                if not vid_url:
                    continue
                title = entry.get('title', 'Видео')
                channel = entry.get('uploader') or entry.get('channel') or ''
                duration = entry.get('duration', 0)
                dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else ""

                sess_id = uuid.uuid4().hex[:8]
                self._search_sessions[sess_id] = {
                    'url': vid_url,
                    'title': title
                }

                desc = f"<b>{idx}. {html.escape(title)}</b>"
                if channel:
                    desc += f"\n👤 Автор: {html.escape(channel)}"
                if dur_str:
                    desc += f"\n⏱ Длительность: {dur_str}"

                markup = InlineKeyboardMarkup()
                markup.row(
                    InlineKeyboardButton("🎥 1080p", callback_data=f"tgdl:1080p:{sess_id}"),
                    InlineKeyboardButton("🎥 720p", callback_data=f"tgdl:720p:{sess_id}"),
                    InlineKeyboardButton("🎵 MP3", callback_data=f"tgdl:mp3:{sess_id}")
                )
                self.bot.send_message(chat_id, desc, reply_markup=markup, parse_mode='HTML')
        except Exception as e:
            logger.error(f"[TelegramBot] Ошибка поиска: {e}")
            self.bot.send_message(chat_id, f"Ошибка при поиске: {e}")

    def _add_search_download(self, url, quality):
        if not self.download_manager:
            return
        is_audio = (quality.lower() == 'mp3')
        tasks = self.download_manager.add_urls([url])
        if tasks:
            task = tasks[0]
            task._quality_chosen = True
            task.is_from_bot = True
            if is_audio:
                task.audio_only = True
                task.quality_badge = "MP3"
                task.quality_override = "bestaudio/best"
            else:
                clean_h = quality.rstrip('p')
                task.quality_override = f"bestvideo[height<={clean_h}]+bestaudio/bestvideo[width<={clean_h}]+bestaudio/best"
                task.quality_badge = quality
            task.info_updated.emit()
            self.download_manager.start_task(task)

    def _build_status_message(self):
        if not self.download_manager:
            return "Менеджер загрузок не подключен.", None

        tasks = list(self.download_manager.tasks)
        active = [t for t in tasks if getattr(t, 'status', None) and t.status.value in ('downloading', 'processing')]
        pending = [t for t in tasks if getattr(t, 'status', None) and t.status.value in ('pending', 'fetching_info')]
        completed = [t for t in tasks if getattr(t, 'status', None) and t.status.value == 'completed']
        errors = [t for t in tasks if getattr(t, 'status', None) and t.status.value == 'error']

        lines = ["📊 <b>Статус загрузок на ПК:</b>\n"]
        if active:
            lines.append("<b>📥 Скачиваются сейчас:</b>")
            for t in active[:5]:
                p = getattr(t, 'progress', 0)
                txt = getattr(t, 'progress_text', '')
                title = t.title or "Видео"
                filled = p // 10
                bar = "█" * filled + "░" * (10 - filled)
                lines.append(f"• <b>{html.escape(title[:32])}</b>\n  [{bar}] <b>{p}%</b> ({txt})")
            lines.append("")
        else:
            lines.append("<i>Нет активных скачиваний.</i>\n")

        lines.append(f"⏳ В очереди: <b>{len(pending)}</b>")
        lines.append(f"✅ Завершено: <b>{len(completed)}</b>")
        lines.append(f"❌ С ошибкой: <b>{len(errors)}</b>")

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("⏸ Пауза", callback_data="tgcmd:pause"),
            InlineKeyboardButton("▶️ Старт", callback_data="tgcmd:resume"),
            InlineKeyboardButton("🧹 Очистить", callback_data="tgcmd:clear")
        )
        markup.row(InlineKeyboardButton("🔄 Обновить статус", callback_data="tgstat:refresh"))
        return "\n".join(lines), markup

    def _get_disk_info(self) -> str:
        drives = [f"{d}:" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:")]
        lines = ["💾 <b>Свободное место на накопителях ПК:</b>\n"]
        for d in drives:
            try:
                usage = shutil.disk_usage(d)
                free_gb = usage.free / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
                used_gb = total_gb - free_gb
                pct = int((used_gb / total_gb) * 100) if total_gb > 0 else 0
                lines.append(f"• Диск <b>{d}</b>: свободно <b>{free_gb:.1f} ГБ</b> из {total_gb:.1f} ГБ ({100 - pct}% свободно)")
            except Exception:
                pass
        return "\n".join(lines)

    # ------------------ ЖИВОЙ ТРЕКИНГ ПРОГРЕССА ------------------

    def on_task_download_started(self, task):
        if not self._is_running or not self.last_chat_id:
            return
        if not self.settings.value('tg_live_progress', True, type=bool):
            return

        task_id = id(task)
        title = task.title or "Видео"
        text = (
            f"📥 <b>Скачивание начато:</b>\n"
            f"{html.escape(title)}\n\n"
            f"[░░░░░░░░░░] <b>0%</b>"
        )
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("⏹ Остановить", callback_data=f"tgstop:{task_id}"))

        try:
            msg = self.bot.send_message(self.last_chat_id, text, reply_markup=markup, parse_mode='HTML')
            self._tracked_tasks[task_id] = {
                'task': task,
                'chat_id': self.last_chat_id,
                'message_id': msg.message_id,
                'last_update': time.time(),
                'last_percent': 0,
                'title': title
            }
        except Exception as e:
            logger.debug(f"[TelegramBot] Ошибка отправки стартового прогресса: {e}")

    def on_task_progress(self, task, percent, speed_text):
        if not self.settings.value('tg_live_progress', True, type=bool):
            return
        task_id = id(task)
        tracker = self._tracked_tasks.get(task_id)
        if not tracker:
            return

        now = time.time()
        # Троттлинг обновлений сообщений (не чаще 2.5 секунд)
        if now - tracker['last_update'] < 2.5 and abs(percent - tracker['last_percent']) < 25:
            return

        tracker['last_update'] = now
        tracker['last_percent'] = percent

        p = max(0, min(100, percent))
        filled = p // 10
        bar = "█" * filled + "░" * (10 - filled)
        text = (
            f"📥 <b>Скачивание:</b>\n"
            f"{html.escape(tracker['title'])}\n\n"
            f"[{bar}] <b>{p}%</b>\n"
            f"⚡ {html.escape(speed_text)}"
        )
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("⏹ Остановить", callback_data=f"tgstop:{task_id}"))

        try:
            self.bot.edit_message_text(
                text,
                chat_id=tracker['chat_id'],
                message_id=tracker['message_id'],
                reply_markup=markup,
                parse_mode='HTML'
            )
        except Exception:
            pass

    def on_task_completed(self, task):
        task_id = id(task)
        tracker = self._tracked_tasks.pop(task_id, None)
        title = task.title or "Видео"
        chat_id = tracker['chat_id'] if tracker else self.last_chat_id
        if not chat_id:
            return

        final_msg = f"✅ <b>Успешно скачано на ПК:</b>\n{html.escape(title)}"
        if tracker and tracker.get('message_id'):
            try:
                self.bot.edit_message_text(final_msg, chat_id=chat_id, message_id=tracker['message_id'], parse_mode='HTML')
            except Exception:
                self.send_message(final_msg)
        else:
            self.send_message(final_msg)

        actual_file = task.final_filepath or task.current_filename
        if actual_file and os.path.exists(actual_file):
            size_mb = os.path.getsize(actual_file) / (1024 * 1024)
            if size_mb <= 49.0:
                self.send_file(actual_file, caption=f"{title}")
            else:
                markup = InlineKeyboardMarkup()
                markup.row(
                    InlineKeyboardButton("🎵 Сжать в MP3 и прислать", callback_data=f"tgmp3:{task_id}"),
                    InlineKeyboardButton("🌐 Раздать по Wi-Fi", callback_data=f"tgwifi:{task_id}")
                )
                self._large_files[task_id] = actual_file
                self.bot.send_message(
                    chat_id,
                    f"📦 Файл <b>'{html.escape(os.path.basename(actual_file))}'</b> ({size_mb:.1f} МБ) сохранен на ПК.\n"
                    f"Он превышает лимит Telegram (50 МБ). Выберите действие:",
                    reply_markup=markup,
                    parse_mode='HTML'
                )

    def on_task_error(self, task):
        task_id = id(task)
        tracker = self._tracked_tasks.pop(task_id, None)
        title = task.title or task.url or "Видео"
        err = task.error_message or "Неизвестная ошибка"
        msg = f"❌ <b>Ошибка скачивания:</b>\n{html.escape(title)}\nПричина: {html.escape(err)}"
        chat_id = tracker['chat_id'] if tracker else self.last_chat_id
        if not chat_id:
            return
        if tracker and tracker.get('message_id'):
            try:
                self.bot.edit_message_text(msg, chat_id=chat_id, message_id=tracker['message_id'], parse_mode='HTML')
                return
            except Exception:
                pass
        self.send_message(msg)

    # ------------------ ИНТЕРАКТИВНЫЙ ВЫБОР ДЛЯ ОДНОГО ВИДЕО ------------------

    def start_single_video_selection(self, task, info: dict, on_complete, chat_id=None):
        target_chat_id = chat_id or self.last_chat_id
        if not target_chat_id or not self._is_running:
            return False

        sess_id = uuid.uuid4().hex[:8]
        raw_title = info.get('title') or task.title or 'Видео'
        duration = info.get('duration', 0)
        dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else ""
        formats = info.get('formats', [])

        def _fmt_size(b):
            if not b or b <= 0:
                return ''
            if b >= 1024 * 1024 * 1024:
                return f'{b / (1024 ** 3):.1f} ГБ'
            elif b >= 10 * 1024 * 1024:
                return f'{round(b / (1024 ** 2))} МБ'
            elif b >= 1024 * 1024:
                return f'{b / (1024 ** 2):.1f} МБ'
            else:
                return f'{round(b / 1024)} КБ'

        # Оценка размера лучшего аудиопотока
        best_audio_size = 0
        for f in formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                s = f.get('filesize') or f.get('filesize_approx')
                if not s and f.get('abr') and duration:
                    s = int(f.get('abr') * 1000 / 8 * duration)
                if s and s > best_audio_size:
                    best_audio_size = s

        mp3_bytes = int(320 * 1000 / 8 * duration) if duration else (best_audio_size or 0)
        mp3_size_str = _fmt_size(mp3_bytes)

        target_resolutions = [4320, 2160, 1440, 1080, 720, 480, 360, 240, 144]
        found_map = {}
        res_sizes = {}
        for f in formats:
            if f.get('vcodec') == 'none':
                continue
            w = f.get('width')
            h = f.get('height')
            # Для вертикальных видео (Shorts/Reels) эффективное разрешение определяет меньшая сторона
            dim = min(w, h) if (w and h) else (h or w)
            if not dim:
                note = f.get('format_note') or ''
                m = re.search(r'(\d+)p', str(note))
                if m:
                    dim = int(m.group(1))
            if dim:
                for t in target_resolutions:
                    if dim >= t * 0.88 and dim <= t * 1.15:
                        found_map[t] = t
                        s = f.get('filesize') or f.get('filesize_approx')
                        if not s:
                            br = f.get('vbr') or f.get('tbr')
                            if br and duration:
                                s = int(br * 1000 / 8 * duration)
                        if s:
                            total_s = s + (best_audio_size if f.get('acodec') == 'none' else 0)
                            if t not in res_sizes or total_s > res_sizes[t]:
                                res_sizes[t] = total_s
                        break

        sorted_h = sorted(list(found_map.keys()), reverse=True)
        if not sorted_h:
            sorted_h = [1080, 720, 480, 360]

        labels = {
            4320: '8K (4320p)',
            2160: '4K (2160p)',
            1440: '2K (1440p)',
            1080: '1080p',
            720: '720p',
            480: '480p',
            360: '360p',
            240: '240p',
            144: '144p'
        }

        markup = InlineKeyboardMarkup()
        row = []
        for h in sorted_h:
            lbl = labels.get(h, f"{h}p")
            sz = _fmt_size(res_sizes.get(h, 0))
            btn_text = f"🎥 {lbl} (~{sz})" if sz else f"🎥 {lbl}"
            btn = InlineKeyboardButton(btn_text, callback_data=f"tgsq:{sess_id}:{h}p")
            row.append(btn)
            if len(row) == 2:
                markup.row(*row)
                row = []
        if row:
            markup.row(*row)

        mp3_btn_text = f"🎵 MP3 320k (~{mp3_size_str})" if mp3_size_str else "🎵 Аудио MP3 (320k)"
        markup.row(
            InlineKeyboardButton(mp3_btn_text, callback_data=f"tgsq:{sess_id}:mp3"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"tgc:{sess_id}")
        )

        header = f"🎬 <b>{html.escape(raw_title)}</b>"
        if dur_str:
            header += f"\n⏱ Длительность: {dur_str}"

        size_lines = []
        for h in sorted_h:
            lbl = labels.get(h, f"{h}p")
            sz = _fmt_size(res_sizes.get(h, 0))
            if sz:
                size_lines.append(f"• {lbl}: ~{sz}")
        if mp3_size_str:
            size_lines.append(f"• MP3 (320k): ~{mp3_size_str}")

        size_block = ""
        if size_lines:
            size_block = "\n\n📊 <b>Примерный вес:</b>\n" + "\n".join(size_lines)

        text = f"{header}{size_block}\n\n<b>Выберите качество для загрузки на ПК:</b>"

        sess = {
            'id': sess_id,
            'task': task,
            'on_complete': on_complete,
            'time': time.time()
        }
        self._single_video_sessions[sess_id] = sess

        try:
            self.bot.send_message(target_chat_id, text, reply_markup=markup, parse_mode='HTML')
            return True
        except Exception as e:
            logger.error(f"[TelegramBot] Ошибка отправки выбора качества: {e}")
            return False

    # ------------------ БОЛЬШИЕ ФАЙЛЫ И WI-FI РАЗДАЧА ------------------

    def _extract_mp3_and_send(self, file_path, chat_id):
        def _run():
            try:
                from .path_manager import get_ffmpeg_path, get_data_dir
                ffmpeg = get_ffmpeg_path()
                out_dir = get_data_dir()
                base = os.path.splitext(os.path.basename(file_path))[0]
                out_mp3 = os.path.join(out_dir, f"{base}_audio.mp3")

                self.send_message("🎵 Извлечение аудиодорожки (MP3)... Пожалуйста, подождите.")
                import subprocess
                cmd = [
                    ffmpeg, '-y', '-i', file_path,
                    '-vn', '-c:a', 'libmp3lame', '-b:a', '192k',
                    out_mp3
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=180)
                if os.path.exists(out_mp3):
                    self.send_file(out_mp3, caption=f"🎵 {base} (Аудиодорожка)")
            except Exception as e:
                logger.error(f"[TelegramBot] Ошибка извлечения MP3: {e}")
                self.send_message(f"Не удалось извлечь MP3: {e}")
        threading.Thread(target=_run, daemon=True).start()

    def _start_wifi_share(self, file_path, chat_id):
        def _run():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    s.connect(('10.255.255.255', 1))
                    lan_ip = s.getsockname()[0]
                except Exception:
                    lan_ip = '127.0.0.1'
                finally:
                    s.close()

                port = 8998
                file_dir = os.path.dirname(file_path)
                filename = os.path.basename(file_path)

                class FileHandler(SimpleHTTPRequestHandler):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, directory=file_dir, **kwargs)
                    def log_message(self, format, *args):
                        pass

                httpd = HTTPServer(('0.0.0.0', port), FileHandler)
                encoded = urllib.parse.quote(filename)
                share_url = f"http://{lan_ip}:{port}/{encoded}"

                self.send_message(
                    f"🌐 <b>Локальная раздача по Wi-Fi запущена!</b>\n\n"
                    f"🔗 Ссылка для скачивания на телефон:\n<code>{share_url}</code>\n\n"
                    f"💡 <i>Телефон должен быть подключен к той же сети Wi-Fi. Ссылка активна 10 минут.</i>"
                )

                httpd.timeout = 600
                start_t = time.time()
                while time.time() - start_t < 600 and self._is_running:
                    httpd.handle_request()
                httpd.server_close()
            except Exception as e:
                logger.error(f"[TelegramBot] Ошибка Wi-Fi раздачи: {e}")
                self.send_message(f"Ошибка запуска Wi-Fi сервера: {e}")

        threading.Thread(target=_run, daemon=True).start()

    # ------------------ CALLBACK ДИСПЕТЧЕР ------------------

    def _handle_callback_query(self, call):
        data = call.data or ""
        chat_id = call.message.chat.id
        user_id = str(call.from_user.id if call.from_user else chat_id)

        if not self.is_user_authorized(chat_id, user_id):
            try: self.bot.answer_callback_query(call.id, "Доступ ограничен.")
            except Exception: pass
            return

        parts = data.split(':', 2)
        if len(parts) < 2:
            return

        action = parts[0]
        sess_id = parts[1]
        param = parts[2] if len(parts) > 2 else ""

        # Остановка конкретной задачи
        if action == 'tgstop':
            try:
                task_id = int(sess_id)
                tracker = self._tracked_tasks.get(task_id)
                if tracker and tracker.get('task'):
                    tracker['task'].request_stop()
                    self.bot.answer_callback_query(call.id, "Загрузка останавливается...")
                    self.bot.edit_message_text("⏹ <b>Загрузка отменена пользователем.</b>", chat_id=chat_id, message_id=call.message.message_id, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Error handling tgstop callback: {e}")

        # Установка ограничения скорости из пресетов
        elif action == 'tgspd':
            limit_bytes = self._parse_speed_arg(sess_id)
            self._apply_speed_limit(limit_bytes)
            res_str = "Без ограничений" if limit_bytes <= 0 else f"{limit_bytes / (1024*1024):.1f} МБ/с"
            self.bot.answer_callback_query(call.id, f"Лимит: {res_str}")
            try:
                self.bot.edit_message_text(
                    f"⚡ Лимит скорости установлен: <b>{res_str}</b>",
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass

        # Скачивание видео из результатов поиска
        elif action == 'tgdl':
            quality = sess_id
            s_id = param
            search_item = self._search_sessions.get(s_id)
            if search_item:
                url = search_item['url']
                title = search_item['title']
                self.bot.answer_callback_query(call.id, f"Выбрано: {quality}")
                try:
                    self.bot.edit_message_text(
                        f"🎬 <b>{html.escape(title)}</b>\n\n"
                        f"Качество: <b>{quality}</b>\n"
                        f"🚀 Добавлено в очередь скачивания на ПК.",
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        parse_mode='HTML'
                    )
                except Exception:
                    pass
                self.dispatch_to_main_thread(self._add_search_download, url, quality)
            else:
                self.bot.answer_callback_query(call.id, "Сессия поиска устарела.")

        # Действия над большими файлами (>50MB)
        elif action == 'tgmp3':
            try:
                task_id = int(sess_id)
                file_p = self._large_files.get(task_id)
                if file_p and os.path.exists(file_p):
                    self.bot.answer_callback_query(call.id, "Запущено извлечение MP3...")
                    self._extract_mp3_and_send(file_p, chat_id)
                else:
                    self.bot.answer_callback_query(call.id, "Файл не найден на диске.")
            except Exception as e:
                logger.error(f"Error handling tgmp3 callback: {e}")

        elif action == 'tgwifi':
            try:
                task_id = int(sess_id)
                file_p = self._large_files.get(task_id)
                if file_p and os.path.exists(file_p):
                    self.bot.answer_callback_query(call.id, "Запуск локального сервера...")
                    self._start_wifi_share(file_p, chat_id)
                else:
                    self.bot.answer_callback_query(call.id, "Файл не найден на диске.")
            except Exception as e:
                logger.error(f"Error handling tgwifi callback: {e}")

        # Выбор качества для одиночного видео
        elif action == 'tgsq':
            try:
                sess = self._single_video_sessions.pop(sess_id, None)
                if sess:
                    q = param
                    is_audio = (q == 'mp3')
                    sel_text = "MP3 Аудио" if is_audio else q
                    self.bot.answer_callback_query(call.id, f"Выбрано: {sel_text}")
                    self.bot.edit_message_text(
                        f"🎬 <b>{html.escape(sess['task'].title)}</b>\n\n"
                        f"Формат: <b>{sel_text}</b>\n"
                        f"🚀 Загрузка запущена на ПК.",
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        parse_mode='HTML'
                    )
                    on_complete = sess.get('on_complete')
                    if on_complete:
                        self.dispatch_to_main_thread(on_complete, q, is_audio)
                else:
                    self.bot.answer_callback_query(call.id, "Сессия выбора устарела.")
            except Exception as e:
                logger.error(f"Error handling tgsq callback: {e}")

        # Обновление и управление из инлайн-статуса
        elif action == 'tgstat':
            try:
                text, markup = self._build_status_message()
                self.bot.answer_callback_query(call.id, "Статус обновлен")
                self.bot.edit_message_text(text, chat_id=chat_id, message_id=call.message.message_id, reply_markup=markup, parse_mode='HTML')
            except Exception:
                pass

        elif action == 'tgcmd':
            cmd = sess_id
            if cmd == 'pause' and self.download_manager:
                self.dispatch_to_main_thread(self.download_manager.stop_all)
                self.bot.answer_callback_query(call.id, "Загрузки приостановлены")
            elif cmd == 'resume' and self.download_manager:
                self.dispatch_to_main_thread(self.download_manager.start_all)
                self.bot.answer_callback_query(call.id, "Загрузки возобновлены")
            elif cmd == 'clear' and self.download_manager:
                self.dispatch_to_main_thread(self.download_manager.clear_completed)
                self.bot.answer_callback_query(call.id, "Завершенные очищены")
            text, markup = self._build_status_message()
            try:
                self.bot.edit_message_text(text, chat_id=chat_id, message_id=call.message.message_id, reply_markup=markup, parse_mode='HTML')
            except Exception:
                pass

        # Управление питанием ПК
        elif action == 'tgpwr':
            pwr_mode = sess_id
            if pwr_mode == 'cancel':
                self.bot.edit_message_text("Отменено.", chat_id=chat_id, message_id=call.message.message_id)
                return
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("⚠️ Да, подтверждаю", callback_data=f"tgpwrok:{pwr_mode}"),
                InlineKeyboardButton("❌ Отмена", callback_data="tgpwr:cancel")
            )
            action_desc = "выключить компьютер" if pwr_mode == 'shutdown' else "перевести компьютер в спящий режим"
            self.bot.edit_message_text(f"Вы уверены, что хотите <b>{action_desc}</b>?", chat_id=chat_id, message_id=call.message.message_id, reply_markup=markup, parse_mode='HTML')

        elif action == 'tgpwrok':
            pwr_mode = sess_id
            import subprocess
            if pwr_mode == 'sleep':
                self.bot.edit_message_text("💤 Компьютер переводится в спящий режим...", chat_id=chat_id, message_id=call.message.message_id)
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            elif pwr_mode == 'shutdown':
                self.bot.edit_message_text("🔌 Компьютер выключается...", chat_id=chat_id, message_id=call.message.message_id)
                subprocess.run(["shutdown", "/s", "/t", "5"])

        # Интерактивные серии KinoPub / AnimeGo
        elif action in ('tgv', 'tgq', 'tge', 'tgback', 'tgc'):
            sess = self._interactive_sessions.get(sess_id)
            if not sess and action != 'tgc':
                try: self.bot.answer_callback_query(call.id, "Сессия истекла или устарела.")
                except Exception: pass
                return

            if action == 'tgv':
                try:
                    v_idx = int(param)
                    if 0 <= v_idx < len(sess['voiceovers']):
                        sess['selected_voice'] = sess['voiceovers'][v_idx]
                        try: self.bot.answer_callback_query(call.id, f"Озвучка: {sess['selected_voice'].get('name')}")
                        except Exception: pass
                        self._render_quality_step(sess, call)
                except Exception as e:
                    logger.error(f"Error handling tgv callback: {e}")

            elif action == 'tgq':
                try:
                    q_idx = int(param)
                    qualities = sess.get('current_qualities') or sess.get('available_qualities', [])
                    selected_q = qualities[q_idx] if 0 <= q_idx < len(qualities) else '1080p'
                    sess['selected_quality'] = selected_q
                    try: self.bot.answer_callback_query(call.id, f"Качество: {selected_q}")
                    except Exception: pass

                    is_movie = sess.get('is_movie', False) or len(sess.get('episodes', [])) <= 1
                    if is_movie:
                        targets = sess.get('episodes') or [{'name': 'Полный фильм', 'id': '1'}]
                        sel_v = sess.get('selected_voice') or (sess['voiceovers'][0] if sess.get('voiceovers') else {'name': 'По умолчанию', 'id': '59'})
                        v_name = sel_v.get('name', 'По умолчанию')
                        text = (
                            f"<b>Параметры выбраны</b>\n"
                            f"{html.escape(sess['title'])}\n"
                            f"Озвучка: <b>{html.escape(v_name)}</b>\n"
                            f"Качество: <b>{html.escape(selected_q)}</b>\n\n"
                            f"Загрузка фильма запущена на ПК."
                        )
                        try: self.bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML')
                        except Exception: pass

                        on_complete = sess.get('on_complete')
                        self._interactive_sessions.pop(sess_id, None)
                        if on_complete:
                            self.dispatch_to_main_thread(on_complete, sel_v, selected_q, targets)
                    else:
                        self._render_episodes_step(sess, call)
                except Exception as e:
                    logger.error(f"Error handling tgq callback: {e}")

            elif action == 'tge':
                try:
                    episodes = sess.get('episodes', [])
                    if param == 'all':
                        targets = episodes
                        desc = f"Все серии ({len(targets)} шт.)"
                    else:
                        ep_idx = int(param)
                        if 0 <= ep_idx < len(episodes):
                            targets = [episodes[ep_idx]]
                            desc = str(episodes[ep_idx].get('name') or f"Серия {ep_idx + 1}")
                        else:
                            targets = episodes
                            desc = f"Все серии ({len(targets)} шт.)"

                    try: self.bot.answer_callback_query(call.id, f"Выбрана {desc}")
                    except Exception: pass

                    sel_v = sess.get('selected_voice') or (sess['voiceovers'][0] if sess.get('voiceovers') else {'name': 'По умолчанию', 'id': '59'})
                    v_name = sel_v.get('name', 'По умолчанию')
                    sel_q = sess.get('selected_quality', '1080p')

                    text = (
                        f"<b>Загрузка запущена</b>\n"
                        f"{html.escape(sess['title'])}\n"
                        f"Озвучка: <b>{html.escape(v_name)}</b>\n"
                        f"Качество: <b>{html.escape(sel_q)}</b>\n"
                        f"Серии: <b>{html.escape(desc)}</b>\n\n"
                        f"Задачи добавлены в очередь на ПК."
                    )
                    try: self.bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML')
                    except Exception: pass

                    on_complete = sess.get('on_complete')
                    self._interactive_sessions.pop(sess_id, None)
                    if on_complete:
                        self.dispatch_to_main_thread(on_complete, sel_v, sel_q, targets)
                except Exception as e:
                    logger.error(f"Error handling tge callback: {e}")

            elif action == 'tgback':
                if param == 'voice': self._render_voiceover_step(sess, call)
                elif param == 'quality': self._render_quality_step(sess, call)

            elif action == 'tgc':
                try: self.bot.answer_callback_query(call.id, "Загрузка отменена")
                except Exception: pass
                try: self.bot.edit_message_text("<b>Загрузка отменена.</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML')
                except Exception: pass
                if sess and sess.get('on_cancel'):
                    self.dispatch_to_main_thread(sess['on_cancel'])
                self._interactive_sessions.pop(sess_id, None)

    # ------------------ ШАГИ ВЫБОРА СЕРИЙ И ОЗВУЧЕК ------------------

    def start_interactive_selection(self, meta: dict, on_complete, on_cancel=None, chat_id=None):
        if not self._is_running or not self.bot:
            return False

        target_chat_id = chat_id or self.last_chat_id
        if not target_chat_id:
            saved_id = self.settings.value('tg_admin_chat_id', None)
            if saved_id:
                try: target_chat_id = int(saved_id)
                except Exception: target_chat_id = saved_id

        if not target_chat_id:
            return False

        sess_id = uuid.uuid4().hex[:8]
        raw_title = meta.get('safe_anime_title') or meta.get('title') or 'Видео'
        voiceovers = meta.get('voiceovers') or [{'name': 'Оригинал / По умолчанию', 'id': 'default'}]
        episodes = meta.get('episodes') or []
        seasons = meta.get('seasons') or [{'name': '1 Сезон', 'id': '1'}]
        is_movie = meta.get('is_movie', False) or len(episodes) <= 1
        available_qualities = meta.get('available_qualities') or ['1080p', '720p', '480p', '360p']
        voice_qualities = meta.get('voice_qualities') or {}

        now = time.time()
        expired = [k for k, v in self._interactive_sessions.items() if now - v.get('time', now) > 3600]
        for k in expired: self._interactive_sessions.pop(k, None)

        sess = {
            'id': sess_id,
            'chat_id': target_chat_id,
            'meta': meta,
            'title': raw_title,
            'voiceovers': voiceovers,
            'episodes': episodes,
            'seasons': seasons,
            'is_movie': is_movie,
            'available_qualities': available_qualities,
            'voice_qualities': voice_qualities,
            'selected_voice': None,
            'selected_quality': None,
            'current_qualities': available_qualities,
            'on_complete': on_complete,
            'on_cancel': on_cancel,
            'time': now,
            'message_id': None,
        }
        self._interactive_sessions[sess_id] = sess
        self._render_voiceover_step(sess)
        return True

    def _render_voiceover_step(self, sess, call=None):
        sess_id = sess['id']
        voiceovers = sess['voiceovers']
        title = sess['title']
        is_movie = sess['is_movie']
        episodes = sess['episodes']

        markup = InlineKeyboardMarkup()
        row = []
        for idx, v in enumerate(voiceovers):
            v_name = v.get('name') or f"Озвучка {idx + 1}"
            btn = InlineKeyboardButton(text=v_name, callback_data=f"tgv:{sess_id}:{idx}")
            if len(v_name) > 18:
                if row:
                    markup.row(*row)
                    row = []
                markup.row(btn)
            else:
                row.append(btn)
                if len(row) == 2:
                    markup.row(*row)
                    row = []
        if row: markup.row(*row)
        markup.row(InlineKeyboardButton("Отмена", callback_data=f"tgc:{sess_id}"))

        type_str = "Фильм" if is_movie or len(episodes) <= 1 else f"Сериал ({len(episodes)} серий)"
        text = f"<b>{html.escape(title)}</b>\n{type_str}\n\n<b>Выберите озвучку:</b>"

        if call and call.message:
            try: self.bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='HTML')
            except Exception: pass
        else:
            try:
                msg = self.bot.send_message(sess['chat_id'], text, reply_markup=markup, parse_mode='HTML')
                sess['message_id'] = msg.message_id
            except Exception as e:
                logger.error(f"Send message error in _render_voiceover_step: {e}")

    def _render_quality_step(self, sess, call):
        sess_id = sess['id']
        title = sess['title']
        selected_voice = sess.get('selected_voice') or {}
        v_name = selected_voice.get('name', 'По умолчанию')

        v_id = str(selected_voice.get('id', ''))
        qualities = sess.get('voice_qualities', {}).get(v_id) or sess.get('available_qualities') or ['1080p', '720p', '480p']
        seen = set()
        clean_qualities = []
        for q in qualities:
            if q not in seen:
                seen.add(q)
                clean_qualities.append(q)
        sess['current_qualities'] = clean_qualities

        markup = InlineKeyboardMarkup()
        row = []
        for q_idx, q in enumerate(clean_qualities):
            btn = InlineKeyboardButton(text=str(q), callback_data=f"tgq:{sess_id}:{q_idx}")
            row.append(btn)
            if len(row) == 2:
                markup.row(*row)
                row = []
        if row: markup.row(*row)

        markup.row(
            InlineKeyboardButton("Назад к озвучкам", callback_data=f"tgback:{sess_id}:voice"),
            InlineKeyboardButton("Отмена", callback_data=f"tgc:{sess_id}")
        )

        text = f"<b>{html.escape(title)}</b>\nОзвучка: <b>{html.escape(v_name)}</b>\n\n<b>Выберите качество:</b>"
        try: self.bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='HTML')
        except Exception: pass

    def _render_episodes_step(self, sess, call):
        sess_id = sess['id']
        title = sess['title']
        selected_voice = sess.get('selected_voice') or {}
        v_name = selected_voice.get('name', 'По умолчанию')
        selected_quality = sess.get('selected_quality', '1080p')
        episodes = sess.get('episodes', [])

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton(f"Скачать все серии ({len(episodes)} шт.)", callback_data=f"tge:{sess_id}:all"))

        ep_row = []
        max_ep = min(len(episodes), 30)
        for ep_idx in range(max_ep):
            ep_obj = episodes[ep_idx]
            ep_label = str(ep_obj.get('episode_number') or ep_idx + 1)
            btn = InlineKeyboardButton(text=ep_label, callback_data=f"tge:{sess_id}:{ep_idx}")
            ep_row.append(btn)
            if len(ep_row) == 5:
                markup.row(*ep_row)
                ep_row = []
        if ep_row: markup.row(*ep_row)

        markup.row(
            InlineKeyboardButton("Назад к качеству", callback_data=f"tgback:{sess_id}:quality"),
            InlineKeyboardButton("Отмена", callback_data=f"tgc:{sess_id}")
        )

        text = f"<b>{html.escape(title)}</b>\nОзвучка: <b>{html.escape(v_name)}</b>\nКачество: <b>{html.escape(selected_quality)}</b>\n\n<b>Выберите серии:</b> ({len(episodes)} шт.)"
        try: self.bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='HTML')
        except Exception: pass

    # ------------------ СЛУЖЕБНЫЕ МЕТОДЫ ОТПРАВКИ ------------------

    def send_test_message(self):
        if not self.bot or not self._is_running:
            return False, "Бот не запущен."
        if not self.last_chat_id:
            return False, "Сначала напишите боту в Telegram, чтобы привязать чат!"
        try:
            self.bot.send_message(self.last_chat_id, "Проверка связи: всё работает отлично! Бот готов к приему ссылок.", timeout=5)
            return True, "Тестовое сообщение отправлено в Telegram!"
        except Exception as e:
            return False, f"Ошибка отправки: {e}"

    def send_message(self, text, chat_id=None, reply_markup=None):
        target_chat_id = chat_id or self.last_chat_id
        if not self._is_running or not target_chat_id:
            return False
        is_silent = self.settings.value('tg_silent_mode', False, type=bool)
        self._msg_queue.put(('msg', target_chat_id, text, reply_markup, is_silent))
        return True

    def send_file(self, file_path, caption="", chat_id=None):
        target_chat_id = chat_id or self.last_chat_id
        if not self._is_running or not target_chat_id:
            return False
        if not file_path or not os.path.exists(file_path):
            return False
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > 49.0:
            self.send_message(f"Файл '{os.path.basename(file_path)}' ({size_mb:.1f} MB) превышает лимит Telegram (50 MB) и сохранен на вашем ПК.", chat_id=target_chat_id)
            return False
        is_silent = self.settings.value('tg_silent_mode', False, type=bool)
        self._msg_queue.put(('file', target_chat_id, file_path, caption, is_silent))
        return True

    def _send_loop(self):
        while self._is_running:
            try:
                item = self._msg_queue.get(timeout=1.0)
                if not self._is_running or not self.bot:
                    break
                try:
                    mode = item[0]
                    is_silent = item[-1] if len(item) >= 5 else False
                    if mode == 'file':
                        _, chat_id, file_path, caption = item[:4]
                        ext = os.path.splitext(file_path)[1].lower()
                        with open(file_path, 'rb') as f:
                            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.ogg'):
                                self.bot.send_audio(chat_id, f, caption=caption, timeout=90, disable_notification=is_silent)
                            elif ext in ('.mp4', '.mkv', '.webm', '.mov'):
                                self.bot.send_video(chat_id, f, caption=caption, timeout=120, disable_notification=is_silent)
                            else:
                                self.bot.send_document(chat_id, f, caption=caption, timeout=90, disable_notification=is_silent)
                    else:
                        _, chat_id, text = item[:3]
                        markup = item[3] if len(item) >= 4 else None
                        self.bot.send_message(chat_id, text, reply_markup=markup, timeout=10, parse_mode='HTML', disable_notification=is_silent)
                except Exception as e:
                    logger.error(f"Ошибка асинхронной отправки TG: {e}")
                finally:
                    self._msg_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Непредвиденная ошибка в очереди сообщений Telegram: {e}")

    def _poll(self):
        import telebot as _tb
        _tb.apihelper.CONNECT_TIMEOUT = 15
        _tb.apihelper.READ_TIMEOUT = 45

        while self._is_running and self.bot:
            try:
                self.bot.infinity_polling(timeout=20, long_polling_timeout=20, logger_level=None)
            except Exception as e:
                if not self._is_running:
                    break
                logger.warning(f"[TelegramBot] Сбой связи (переподключение через 3с): {e}")
                time.sleep(3)

    def stop_bot(self):
        self._is_running = False
        if self.bot:
            try:
                self.bot.stop_polling()
            except Exception:
                pass
        self.bot = None
        self.current_token = None
