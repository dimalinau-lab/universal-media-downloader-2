import os
import queue
import time
import threading
import logging
import html
import uuid
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class BotSignals(QObject):
    url_received = pyqtSignal(str)
    dispatch_main = pyqtSignal(object, tuple)


class TelegramBotManager:
    def __init__(self, settings):
        self.settings = settings
        self.signals = BotSignals()
        self.signals.dispatch_main.connect(self._run_on_main_thread)
        self.bot = None
        self.thread = None
        self._sender_thread = None
        self._msg_queue = queue.Queue()
        self._is_running = False
        self.last_chat_id = None
        self.current_token = None
        self._interactive_sessions = {}

    def _run_on_main_thread(self, fn, args):
        try:
            fn(*args)
        except Exception as e:
            logger.error(f"[TelegramBot] Ошибка выполнения в GUI потоке: {e}", exc_info=True)

    def dispatch_to_main_thread(self, fn, *args):
        self.signals.dispatch_main.emit(fn, args)

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
                self.bot.reply_to(message, "🔍 Ссылка поймана! Анализирую видео...")
            elif text.startswith('/start'):
                self.bot.reply_to(message, "Привет! Я на связи. Отправь мне ссылку, и загрузка начнется автоматически.")
            elif text.startswith('/unbind'):
                self.settings.remove('tg_admin_chat_id')
                self.settings.sync()
                self.bot.reply_to(message, "🔓 Привязка снята. Напишите /start с нужного аккаунта для новой привязки.")
            else:
                self.bot.reply_to(message, "Просто отправь мне ссылку на видео, и я скачаю его!")

        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_callback_query(call):
            self._handle_callback_query(call)

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

    def start_interactive_selection(self, meta: dict, on_complete, on_cancel=None, chat_id=None):
        """
        Инициирует интерактивный выбор параметров видео (озвучка, качество, серии)
        через Telegram Inline-кнопки без блокировки GUI на ПК.
        """
        if not self._is_running or not self.bot:
            logger.warning("[TelegramBot] Бот не запущен, интерактивный выбор невозможен.")
            return False

        target_chat_id = chat_id or self.last_chat_id
        if not target_chat_id:
            saved_id = self.settings.value('tg_admin_chat_id', None)
            if saved_id:
                try:
                    target_chat_id = int(saved_id)
                except Exception:
                    target_chat_id = saved_id

        if not target_chat_id:
            logger.warning("[TelegramBot] Отсутствует chat_id для отправки интерактивного выбора.")
            return False

        sess_id = uuid.uuid4().hex[:8]
        raw_title = meta.get('safe_anime_title') or meta.get('title') or 'Видео'
        voiceovers = meta.get('voiceovers') or [{'name': 'Оригинал / По умолчанию', 'id': 'default'}]
        episodes = meta.get('episodes') or []
        seasons = meta.get('seasons') or [{'name': '1 Сезон', 'id': '1'}]
        is_movie = meta.get('is_movie', False) or len(episodes) <= 1
        available_qualities = meta.get('available_qualities') or ['1080p', '720p', '480p', '360p']
        voice_qualities = meta.get('voice_qualities') or {}

        # Очистка устаревших сессий (> 1 часа)
        now = time.time()
        expired = [k for k, v in self._interactive_sessions.items() if now - v.get('time', now) > 3600]
        for k in expired:
            self._interactive_sessions.pop(k, None)

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
        if row:
            markup.row(*row)

        markup.row(InlineKeyboardButton("❌ Отмена", callback_data=f"tgc:{sess_id}"))

        type_str = "🎞️ Фильм" if is_movie or len(episodes) <= 1 else f"📺 Сериал ({len(episodes)} серий)"
        text = (
            f"🎬 <b>Найдено:</b> {html.escape(title)}\n"
            f"{type_str}\n\n"
            f"🎙️ <b>Выберите озвучку:</b>"
        )

        if call and call.message:
            try:
                self.bot.edit_message_text(
                    text,
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=markup,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.debug(f"Edit message error in _render_voiceover_step: {e}")
        else:
            chat_id = sess['chat_id']
            try:
                msg = self.bot.send_message(
                    chat_id,
                    text,
                    reply_markup=markup,
                    parse_mode='HTML'
                )
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
        if row:
            markup.row(*row)

        markup.row(
            InlineKeyboardButton("⬅️ Назад к озвучкам", callback_data=f"tgback:{sess_id}:voice"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"tgc:{sess_id}")
        )

        text = (
            f"🎬 <b>{html.escape(title)}</b>\n"
            f"🎙️ Озвучка: <b>{html.escape(v_name)}</b>\n\n"
            f"⚙️ <b>Выберите качество видео:</b>"
        )

        try:
            self.bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.debug(f"Edit message error in _render_quality_step: {e}")

    def _render_episodes_step(self, sess, call):
        sess_id = sess['id']
        title = sess['title']
        selected_voice = sess.get('selected_voice') or {}
        v_name = selected_voice.get('name', 'По умолчанию')
        selected_quality = sess.get('selected_quality', '1080p')
        episodes = sess.get('episodes', [])

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton(f"📥 Скачать ВСЕ серии ({len(episodes)} шт.)", callback_data=f"tge:{sess_id}:all"))

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
        if ep_row:
            markup.row(*ep_row)

        markup.row(
            InlineKeyboardButton("⬅️ Назад к качеству", callback_data=f"tgback:{sess_id}:quality"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"tgc:{sess_id}")
        )

        text = (
            f"🎬 <b>{html.escape(title)}</b>\n"
            f"🎙️ Озвучка: <b>{html.escape(v_name)}</b>\n"
            f"⚙️ Качество: <b>{html.escape(selected_quality)}</b>\n\n"
            f"📺 <b>Выберите серии для загрузки:</b> (всего {len(episodes)} серий)"
        )

        try:
            self.bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.debug(f"Edit message error in _render_episodes_step: {e}")

    def _handle_callback_query(self, call):
        data = call.data or ""
        user_id = str(call.from_user.id if call.from_user else call.message.chat.id)
        admin_id = str(self.settings.value('tg_admin_chat_id', '') or '')
        if admin_id and str(call.message.chat.id) != admin_id and user_id != admin_id:
            try:
                self.bot.answer_callback_query(call.id, "⛔ Доступ ограничен.")
            except Exception:
                pass
            return

        parts = data.split(':', 2)
        if len(parts) < 2:
            return

        action = parts[0]
        sess_id = parts[1]
        param = parts[2] if len(parts) > 2 else ""

        sess = self._interactive_sessions.get(sess_id)
        if not sess and action != 'tgc':
            try:
                self.bot.answer_callback_query(call.id, "Сессия истекла или устарела.")
            except Exception:
                pass
            return

        if action == 'tgv':
            try:
                v_idx = int(param)
                if 0 <= v_idx < len(sess['voiceovers']):
                    sess['selected_voice'] = sess['voiceovers'][v_idx]
                    try:
                        self.bot.answer_callback_query(call.id, f"Озвучка: {sess['selected_voice'].get('name')}")
                    except Exception:
                        pass
                    self._render_quality_step(sess, call)
            except Exception as e:
                logger.error(f"Error handling tgv callback: {e}")

        elif action == 'tgq':
            try:
                q_idx = int(param)
                qualities = sess.get('current_qualities') or sess.get('available_qualities', [])
                if 0 <= q_idx < len(qualities):
                    selected_q = qualities[q_idx]
                else:
                    selected_q = '1080p'
                sess['selected_quality'] = selected_q
                try:
                    self.bot.answer_callback_query(call.id, f"Качество: {selected_q}")
                except Exception:
                    pass

                is_movie = sess.get('is_movie', False) or len(sess.get('episodes', [])) <= 1
                if is_movie:
                    targets = sess.get('episodes') or [{'name': 'Полный фильм', 'id': '1'}]
                    sel_v = sess.get('selected_voice') or (sess['voiceovers'][0] if sess.get('voiceovers') else {'name': 'По умолчанию', 'id': '59'})
                    v_name = sel_v.get('name', 'По умолчанию')
                    text = (
                        f"✅ <b>Параметры выбраны!</b>\n"
                        f"🎬 <b>{html.escape(sess['title'])}</b>\n"
                        f"🎙️ Озвучка: <b>{html.escape(v_name)}</b>\n"
                        f"⚙️ Качество: <b>{html.escape(selected_q)}</b>\n\n"
                        f"🚀 <b>Скачивание фильма запущено на ПК!</b>"
                    )
                    try:
                        self.bot.edit_message_text(
                            text,
                            chat_id=call.message.chat.id,
                            message_id=call.message.message_id,
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.debug(f"Error updating completion message: {e}")

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
                    try:
                        self.bot.answer_callback_query(call.id, "Выбраны все серии")
                    except Exception:
                        pass
                else:
                    ep_idx = int(param)
                    if 0 <= ep_idx < len(episodes):
                        targets = [episodes[ep_idx]]
                        desc = str(episodes[ep_idx].get('name') or f"Серия {ep_idx + 1}")
                    else:
                        targets = episodes
                        desc = f"Все серии ({len(targets)} шт.)"
                    try:
                        self.bot.answer_callback_query(call.id, f"Выбрана {desc}")
                    except Exception:
                        pass

                sel_v = sess.get('selected_voice') or (sess['voiceovers'][0] if sess.get('voiceovers') else {'name': 'По умолчанию', 'id': '59'})
                v_name = sel_v.get('name', 'По умолчанию')
                sel_q = sess.get('selected_quality', '1080p')

                text = (
                    f"✅ <b>Загрузка запущена!</b>\n"
                    f"🎬 <b>{html.escape(sess['title'])}</b>\n"
                    f"🎙️ Озвучка: <b>{html.escape(v_name)}</b>\n"
                    f"⚙️ Качество: <b>{html.escape(sel_q)}</b>\n"
                    f"📺 Серии: <b>{html.escape(desc)}</b>\n\n"
                    f"🚀 <b>Задачи успешно добавлены в очередь на ПК!</b>"
                )
                try:
                    self.bot.edit_message_text(
                        text,
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.debug(f"Error updating completion message: {e}")

                on_complete = sess.get('on_complete')
                self._interactive_sessions.pop(sess_id, None)
                if on_complete:
                    self.dispatch_to_main_thread(on_complete, sel_v, sel_q, targets)
            except Exception as e:
                logger.error(f"Error handling tge callback: {e}")

        elif action == 'tgback':
            try:
                if param == 'voice':
                    try:
                        self.bot.answer_callback_query(call.id, "Возврат к выбору озвучки")
                    except Exception:
                        pass
                    self._render_voiceover_step(sess, call)
                elif param == 'quality':
                    try:
                        self.bot.answer_callback_query(call.id, "Возврат к выбору качества")
                    except Exception:
                        pass
                    self._render_quality_step(sess, call)
            except Exception as e:
                logger.error(f"Error handling tgback callback: {e}")

        elif action == 'tgc':
            try:
                try:
                    self.bot.answer_callback_query(call.id, "Загрузка отменена")
                except Exception:
                    pass
                try:
                    self.bot.edit_message_text(
                        "❌ <b>Загрузка отменена пользователем.</b>",
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        parse_mode='HTML'
                    )
                except Exception:
                    pass
                if sess and sess.get('on_cancel'):
                    self.dispatch_to_main_thread(sess['on_cancel'])
                self._interactive_sessions.pop(sess_id, None)
            except Exception as e:
                logger.error(f"Error handling tgc callback: {e}")