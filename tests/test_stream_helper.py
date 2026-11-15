import os
import sys
import pytest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.stream_helper import StreamResolverHelper
from app.path_manager import get_aria2c_path


def test_clean_stream_url():
    # 1. HLS manifest removal
    u1 = "https://cloud2.solodcdn.com/useruploads/abc/720.mp4:hls:manifest.m3u8"
    assert StreamResolverHelper.clean_stream_url(u1) == "https://cloud2.solodcdn.com/useruploads/abc/720.mp4"

    # 2. Segments removal
    u2 = "https://cloud2.solodcdn.com/useruploads/abc/720.mp4:hls:seg-1-v1-a1.ts"
    assert StreamResolverHelper.clean_stream_url(u2) == "https://cloud2.solodcdn.com/useruploads/abc/720.mp4"

    # 3. /3.mp4 corruption fix
    u3 = "https://cloud2.solodcdn.com/useruploads/abc/3.mp4"
    assert StreamResolverHelper.clean_stream_url(u3) == "https://cloud2.solodcdn.com/useruploads/abc/360.mp4"

    # 4. Spaces and semicolons
    u4 = '  "https://cloud2.solodcdn.com/useruploads/abc/1080.mp4";  '
    assert StreamResolverHelper.clean_stream_url(u4) == "https://cloud2.solodcdn.com/useruploads/abc/1080.mp4"


def test_is_kodik_and_aniboom_stream():
    assert StreamResolverHelper.is_kodik_stream("https://cloud2.solodcdn.com/useruploads/1/720.mp4") is True
    assert StreamResolverHelper.is_kodik_stream("https://orion.solodcdn.com/test.mp4") is True
    assert StreamResolverHelper.is_kodik_stream("https://youtube.com/watch?v=123") is False

    assert StreamResolverHelper.is_aniboom_stream("https://ya-ligh123.site/master.m3u8") is True
    assert StreamResolverHelper.is_aniboom_stream("https://poppy.aniboom.one/video.m3u8") is True
    assert StreamResolverHelper.is_aniboom_stream("https://cloud2.solodcdn.com/test.mp4") is False


def test_get_stream_referer():
    kodik_url = "https://cloud2.solodcdn.com/useruploads/1/720.mp4"
    assert StreamResolverHelper.get_stream_referer(kodik_url) == "https://kodikplayer.com/"

    aniboom_url = "https://ya-ligh123.site/master.m3u8"
    assert StreamResolverHelper.get_stream_referer(aniboom_url) == "https://animego.me/"

    other_url = "https://example.com/video.mp4"
    assert StreamResolverHelper.get_stream_referer(other_url, "https://default.com/") == "https://default.com/"


def test_replace_quality():
    base_url = "https://cloud2.solodcdn.com/useruploads/abc/720.mp4"

    # Замена на 1080p
    assert StreamResolverHelper.replace_quality(base_url, "1080p") == "https://cloud2.solodcdn.com/useruploads/abc/1080.mp4"

    # Замена на 480p
    assert StreamResolverHelper.replace_quality(base_url, "480p") == "https://cloud2.solodcdn.com/useruploads/abc/480.mp4"

    # Аудио режим: всегда переключает на легкий 360p
    assert StreamResolverHelper.replace_quality(base_url, "MP3", is_audio=True) == "https://cloud2.solodcdn.com/useruploads/abc/360.mp4"

    # Защита от ошибочной одиночной цифры '3'
    assert StreamResolverHelper.replace_quality(base_url, "3") == base_url


def test_calculate_chunk_count():
    # <= 0 байт -> 1 поток
    assert StreamResolverHelper.calculate_chunk_count(0) == 1
    assert StreamResolverHelper.calculate_chunk_count(-100) == 1

    # < 15 МБ (например, 10 МБ) -> 2 потока
    ten_mb = 10 * 1024 * 1024
    assert StreamResolverHelper.calculate_chunk_count(ten_mb, max_configured_threads=4) == 2

    # 15 - 100 МБ (например, 50 МБ) -> 4 потока
    fifty_mb = 50 * 1024 * 1024
    assert StreamResolverHelper.calculate_chunk_count(fifty_mb, max_configured_threads=4) == 4

    # > 100 МБ (например, 300 МБ) с max_configured_threads=8 -> 8 потоков
    three_hundred_mb = 300 * 1024 * 1024
    assert StreamResolverHelper.calculate_chunk_count(three_hundred_mb, max_configured_threads=8) == 8
    # с ограничением 4 -> 4 потока
    assert StreamResolverHelper.calculate_chunk_count(three_hundred_mb, max_configured_threads=4) == 4


def test_get_aria2c_path():
    path = get_aria2c_path()
    assert isinstance(path, str)


def test_format_user_friendly_error():
    # 1. Ошибка блокировки провайдером (DPI / 10054 / curl 35)
    err_rst = "Unable to download webpage: Failed to perform, curl: (35) Recv failure: Connection was reset. (caused by SSLError('Connection was reset'))"
    msg1 = StreamResolverHelper.format_user_friendly_error(err_rst)
    assert "заблокирован" in msg1.lower()
    assert "vpn" in msg1.lower()

    # 2. HTTP 403 Forbidden
    err_403 = "HTTP Error 403: Forbidden"
    msg2 = StreamResolverHelper.format_user_friendly_error(err_403)
    assert "403" in msg2 or "ограничен" in msg2.lower()

    # 3. HTTP 404 Not Found
    err_404 = "404 Client Error: Not Found for url: https://example.com/video.mp4"
    msg3 = StreamResolverHelper.format_user_friendly_error(err_404)
    assert "не найдено" in msg3.lower() or "404" in msg3

    # 4. Требуется подтверждение возраста
    err_age = "Sign in to confirm your age"
    msg4 = StreamResolverHelper.format_user_friendly_error(err_age)
    assert "возраста" in msg4.lower() or "авторизация" in msg4.lower()

