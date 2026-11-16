import os
import re
import logging

logger = logging.getLogger(__name__)


class StreamResolverHelper:
    """
    Централизованный хелпер для обработки прямых медиапотоков (Kodik, AniBoom, VOD, CDN):
    - Очистка URL от HLS-манифестов и фрагментов сегментов
    - Коррекция суффиксов качества и аудио (предотвращение багов вида /3.mp4)
    - Определение рефереров для CDN с защитой от хотлинкинга
    - Расчет оптимального числа параллельных соединений (чанков)
    """

    KODIK_DOMAINS = (
        'solodcdn', 'kodik', 'rooster.cloud2', 'cloud2.solodcdn.com',
        'orion.solodcdn.com', 'wolverine.solodcdn.com'
    )
    ANIBOOM_DOMAINS = ('ya-ligh123.site', 'ya-ligh', 'boom-img', 'poppy', 'sophia', 'aniboom')
    KINOPUB_DOMAINS = ('kinopub', 'rezka', 'voidboost')

    @classmethod
    def clean_stream_url(cls, stream_url: str) -> str:
        """
        Очищает URL потока от временных суффиксов HLS манифестов и фрагментов,
        возвращая прямой URL к исходному медиаконтейнеру.
        """
        if not stream_url or not isinstance(stream_url, str):
            return ""

        u = stream_url.strip('; "\'')

        # Очистка HLS фрагментов
        if ":hls:seg-" in u:
            u = re.sub(r':hls:seg-[^/]+\.ts.*', '', u)
        elif ".ts" in u and "seg-" in u:
            u = re.sub(r':?seg-[^/]+\.ts.*', '', u)
        elif ".m4s" in u:
            u = re.sub(r'/[^/]+(?:\.m4s).*$', '/master.m3u8', u)

        # Удаление суффикса :hls:manifest.m3u8 (характерно для Kodik / solodcdn)
        if ':hls:manifest.m3u8' in u:
            u = u.replace(':hls:manifest.m3u8', '')

        # Защита от повреждения URL вида /3.mp4 -> /360.mp4
        if re.search(r'/3\.mp4', u):
            u = re.sub(r'/3\.mp4', '/360.mp4', u)

        return u.strip('; "\'')

    @classmethod
    def is_kodik_stream(cls, url: str) -> bool:
        """Проверяет, относится ли URL к CDN-серверам Kodik."""
        if not url:
            return False
        u_lower = url.lower()
        return any(d in u_lower for d in cls.KODIK_DOMAINS)

    @classmethod
    def is_aniboom_stream(cls, url: str) -> bool:
        """Проверяет, относится ли URL к CDN-серверам AniBoom."""
        if not url:
            return False
        u_lower = url.lower()
        return any(d in u_lower for d in cls.ANIBOOM_DOMAINS)

    @classmethod
    def is_kinopub_stream(cls, url: str) -> bool:
        """Проверяет, относится ли URL к серверам KinoPub / Rezka / Voidboost."""
        if not url:
            return False
        u_lower = url.lower()
        return any(d in u_lower for d in cls.KINOPUB_DOMAINS)

    @classmethod
    def get_stream_referer(cls, url: str, default_referer: str = "") -> str:
        """
        Возвращает обязательный заголовок Referer для обхода проверки источника на CDN.
        """
        if cls.is_kodik_stream(url):
            return "https://kodikplayer.com/"
        if cls.is_aniboom_stream(url):
            return "https://animego.me/"
        if cls.is_kinopub_stream(url):
            return "https://kinopub.me/"
        return default_referer

    @classmethod
    def replace_quality(cls, url: str, quality_tag: str, is_audio: bool = False) -> str:
        """
        Безопасно заменяет разрешение в URL потока Kodik/solodcdn.
        Для аудио всегда возвращает /360.mp4 (наименьший контейнер с идентичной дорожкой AAC).
        """
        clean_url = cls.clean_stream_url(url)
        if not cls.is_kodik_stream(clean_url):
            return clean_url

        if is_audio:
            # Для MP3 аудио дорожка одинакова во всех разрешениях (AAC 128-192 kbps).
            # Контейнер 360p весит ~60-70 МБ против ~250 МБ у 1080p.
            return re.sub(r'/\d{1,4}\.mp4', '/360.mp4', clean_url)

        if quality_tag:
            m = re.search(r'(\d+)', quality_tag)
            if m:
                target_height = m.group(1)
                # Исключаем ошибочные одиночные цифры вроде '3' (от MP3)
                if len(target_height) >= 3:
                    return re.sub(r'/\d{1,4}\.mp4', f'/{target_height}.mp4', clean_url)

        return clean_url

    @classmethod
    def calculate_chunk_count(cls, total_bytes: int, max_configured_threads: int = 4) -> int:
        """
        Динамический адаптивный расчет количества параллельных потоков загрузки:
        - Менее 15 МБ: 2 потока (короткие ролики, предотвращение оверхеда)
        - 15 - 100 МБ: 4 потока (~500-600 КБ/с на ограниченных CDN)
        - Более 100 МБ: 4-8 потоков (в пределах max_configured_threads)
        - Неизвестный размер (<= 0): 1 поток (безопасный режим)
        """
        if total_bytes <= 0:
            return 1

        mb = total_bytes / (1024 * 1024)
        if mb < 15:
            return min(2, max_configured_threads)
        elif mb < 100:
            return min(4, max_configured_threads)
        else:
            return min(max(4, max_configured_threads), 8)

    @classmethod
    def format_user_friendly_error(cls, error: str, translator=None) -> str:
        """
        Преобразует системные ошибки сетевого стека, cURL, yt-dlp и HTTP
        в понятные человеку сообщения с рекомендацией решения.
        """
        if not error:
            return translator.translate('error_getting_info', 'Ошибка получения информации') if translator else 'Ошибка получения информации'

        err_lower = str(error).lower()

        # 1. Блокировка провайдером (ТСПУ / DPI / RST / SSLError / 10054 / Connection was reset)
        if any(kw in err_lower for kw in (
            'connection was reset', 'connectionreseterror', '10054', 'recv failure',
            'curl: (35)', 'errno 104', 'connection reset by peer', 'unable to establish ssl connection',
            'tls connection was reset', 'certificate verify failed', 'ssl: certificate_verify_failed'
        )):
            if translator:
                return translator.translate(
                    'error_connection_blocked',
                    'Сайт заблокирован провайдером или соединение сброшено (включите VPN или режим TUN)'
                )
            return 'Сайт заблокирован провайдером или соединение сброшено (включите VPN или режим TUN)'

        # 2. Доступ ограничен (HTTP 403 / Cloudflare / Geo-block)
        if any(kw in err_lower for kw in ('http error 403', '403: forbidden', '403 forbidden', 'cloudflare')):
            if translator:
                return translator.translate(
                    'error_access_forbidden',
                    'Доступ ограничен сервером (HTTP 403 / Cloudflare / гео-блок)'
                )
            return 'Доступ ограничен сервером (HTTP 403 / Cloudflare / гео-блок)'

        # 3. Видео удалено / не найдено (HTTP 404)
        if any(kw in err_lower for kw in ('http error 404', '404 not found', '404 client error', 'video unavailable', 'this video has been removed')):
            if translator:
                return translator.translate(
                    'error_video_not_found',
                    'Видео не найдено или удалено (HTTP 404)'
                )
            return 'Видео не найдено или удалено (HTTP 404)'

        # 4. Требуется подтверждение возраста или логин
        if any(kw in err_lower for kw in ('sign in to confirm your age', 'login required', 'confirm your age', 'private video')):
            if translator:
                return translator.translate(
                    'error_auth_required',
                    'Требуется авторизация или подтверждение возраста'
                )
            return 'Требуется авторизация или подтверждение возраста'

        # 5. Канал не в эфире (оффлайн Twitch / Kick / Live)
        if any(kw in err_lower for kw in ('the channel is not currently live', 'is not currently live', 'channel is offline', 'stream is offline')):
            if translator:
                return translator.translate(
                    'error_channel_offline',
                    'Канал сейчас не в эфире (трансляция оффлайн)'
                )
            return 'Канал сейчас не в эфире (трансляция оффлайн)'

        # 6. Очистка стандартных длинных префиксов yt-dlp
        cleaned = re.sub(r'^(?:ERROR:\s*)+\[[^\]]+\]\s*', '', str(error), flags=re.IGNORECASE)
        cleaned = re.sub(r'^(?:ERROR:\s*)+', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'please report this issue on\s+https://.*', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        # Если ошибка слишком длинная, берем первую информативную строку
        first_line = cleaned.split('\n')[0].strip()
        if len(first_line) > 120:
            first_line = first_line[:117] + '...'
        return first_line or (translator.translate('error_getting_info', 'Ошибка получения информации') if translator else 'Ошибка получения информации')

    @classmethod
    def sanitize_filename_part(cls, value: str, max_len: int = 140) -> str:
        """Удаляет запрещенные для ФС Windows символы из сегмента имени/папки."""
        if not value:
            return ""
        cleaned = re.sub(r'[\\/*?:"<>|]', "", str(value))
        cleaned = re.sub(r'\s+', ' ', cleaned).strip().strip('.')
        return cleaned[:max_len].strip()

    @classmethod
    def detect_platform_name(cls, url: str, platform_hint: str = "") -> str:
        """Определяет читаемое имя платформы для группировки по папкам."""
        u = (url or "").lower()
        p = (platform_hint or "").lower()
        mapping = [
            (('youtube.com', 'youtu.be'), 'YouTube'),
            (('twitch.tv', 'ttvnw.net'), 'Twitch'),
            (('kick.com',), 'Kick'),
            (('vk.com', 'vkvideo.ru'), 'VK'),
            (('rutube.ru',), 'RuTube'),
            (('tiktok.com',), 'TikTok'),
            (('instagram.com',), 'Instagram'),
            (('pinterest.', 'pin.it'), 'Pinterest'),
            (('twitter.com', 'x.com'), 'Twitter'),
            (('facebook.com', 'fb.watch'), 'Facebook'),
            (('animego', 'aniboom', 'kodik', 'solodcdn', 'ya-ligh'), 'AnimeGO'),
            (('kinopub', 'kino.pub', 'rezka', 'voidboost'), 'KinoPub'),
            (('vi3000', 'lampa', 'cub'), 'Lampa'),
        ]
        for keys, label in mapping:
            if any(k in u or k in p for k in keys):
                return label
        if platform_hint and platform_hint not in ('Unknown', 'generic', 'DirectStream'):
            return cls.sanitize_filename_part(platform_hint, max_len=40) or 'Other'
        return 'Other'

    @classmethod
    def resolve_output_template(
        cls,
        save_path: str,
        template: str,
        task,
        quality_tag: str = "",
        range_suffix: str = "",
        is_ytdlp: bool = True,
        create_dirs: bool = True,
    ) -> str:
        """
        Формирует итоговый путь и шаблон файла на основе пользовательского шаблона.
        Поддерживает переменные: {title}, {quality}, {platform}, {series}, {season}, {episode}, {uploader}.
        Пустые сегменты подпапок (например {series} для одиночного ролика) аккуратно пропускаются.
        """
        raw_tpl = (template or "{title} [{quality}]").strip().replace('\\', '/')
        if '{title}' not in raw_tpl:
            raw_tpl = f"{raw_tpl}/{{title}}" if raw_tpl else "{title}"

        custom_t = getattr(task, 'custom_title', None)
        task_t = getattr(task, 'title', None)
        base_title = (custom_t.strip() if custom_t else "") or (
            task_t.strip() if task_t and task_t not in ("...", "") else ""
        )
        safe_title = cls.sanitize_filename_part(base_title, max_len=150)
        if quality_tag and safe_title:
            safe_title = re.sub(
                r'\s*\[\s*(?:\d{3,4}p|MP3|AUDIO|4K|2K)\s*\]\s*$',
                '',
                safe_title,
                flags=re.IGNORECASE,
            ).strip()

        info = getattr(task, 'info', None)
        if not isinstance(info, dict):
            info = {}

        uploader = cls.sanitize_filename_part(info.get('uploader') or info.get('channel') or '', max_len=80)
        series = cls.sanitize_filename_part(getattr(task, 'series_name', '') or info.get('series') or '', max_len=100)
        season = cls.sanitize_filename_part(getattr(task, 'season_name', '') or '', max_len=60)
        episode = cls.sanitize_filename_part(getattr(task, 'episode_name', '') or '', max_len=80)
        platform = cls.detect_platform_name(
            getattr(task, 'original_url', '') or getattr(task, 'url', ''),
            getattr(task, 'platform', ''),
        )

        title_token = safe_title if safe_title else ("%(title)s" if is_ytdlp else "video")
        uploader_token = uploader if uploader else ("%(uploader|Unknown)s" if is_ytdlp else "")

        values = {
            'title': title_token,
            'quality': quality_tag or "",
            'platform': platform,
            'series': series,
            'season': season,
            'episode': episode,
            'uploader': uploader_token,
        }

        segments = [seg.strip() for seg in raw_tpl.split('/') if seg.strip()]
        resolved_dirs = []
        resolved_filename = ""

        for idx, seg in enumerate(segments):
            is_last = (idx == len(segments) - 1)
            rendered = seg
            for key, val in values.items():
                rendered = rendered.replace(f"{{{key}}}", val)
            # Убираем пустые скобки при отсутствии quality/season
            rendered = re.sub(r'\[\s*\]|\(\s*\)', '', rendered)
            rendered = re.sub(r'\s+', ' ', rendered).strip(' .-_')
            if is_last:
                resolved_filename = rendered or title_token
            else:
                # Сохраняем только непустые подпапки (пустые например {series} пропускаем)
                safe_dir = cls.sanitize_filename_part(rendered, max_len=100) if '%' not in rendered else rendered
                if safe_dir:
                    resolved_dirs.append(safe_dir)

        target_dir = os.path.join(save_path, *resolved_dirs) if resolved_dirs else save_path
        if create_dirs:
            try:
                os.makedirs(target_dir, exist_ok=True)
            except OSError as e:
                logger.warning(f"Не удалось создать директорию '{target_dir}': {e}")
                target_dir = save_path

        ext_suffix = ".%(ext)s" if is_ytdlp else ""
        full_name = f"{resolved_filename}{range_suffix}{ext_suffix}"
        return os.path.join(target_dir, full_name)

    @classmethod
    def parse_subtitle_langs(cls, langs_raw: str) -> list[str]:
        """Разбирает строку языков субтитров (например 'ru, en, uk') в список кодов."""
        if not langs_raw or not isinstance(langs_raw, str):
            return ['ru', 'en']
        tokens = [t.strip().lower() for t in re.split(r'[,;\s]+', langs_raw) if t.strip()]
        if not tokens:
            return ['ru', 'en']
        if 'all' in tokens:
            return ['all']
        seen = []
        for t in tokens:
            if t not in seen:
                seen.append(t)
        return seen


