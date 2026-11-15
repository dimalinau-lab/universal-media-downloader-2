import re
import os
import logging
from typing import Optional, Tuple

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
    ANIBOOM_DOMAINS = ('ya-ligh123.site', 'poppy', 'sophia', 'aniboom')

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
    def get_stream_referer(cls, url: str, default_referer: str = "") -> str:
        """
        Возвращает обязательный заголовок Referer для обхода проверки источника на CDN.
        """
        if cls.is_kodik_stream(url):
            return "https://kodikplayer.com/"
        if cls.is_aniboom_stream(url):
            return "https://animego.me/"
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

