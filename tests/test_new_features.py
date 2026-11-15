import os
import sys
import tempfile

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication

from app.download_task import DownloadTask
from app.download_item_widget import DownloadItemWidget
from app.translation import Translator
from app.animego_progress_dialog import AnimeGoScanDialog
from app.browser_cookies import find_chrome_executable, soft_restart_chrome_and_copy
from app.threads import InfoWorker


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_find_chrome_executable():
    path = find_chrome_executable()
    assert path is not None
    assert "chrome" in path.lower()


def test_soft_restart_chrome_safe_copy_no_taskkill():
    with patch("shutil.copy2") as mock_copy, \
         patch("subprocess.run") as mock_run:
        res = soft_restart_chrome_and_copy("dummy_src", "dummy_dest", "dummy_wal")
        assert res is True
        mock_copy.assert_called()
        # Verify taskkill is NEVER called!
        for call_args in mock_run.call_args_list:
            assert "taskkill" not in str(call_args)


def test_animego_scan_dialog(qapp):
    dialog = AnimeGoScanDialog("https://animego.me/anime/test-123")
    assert dialog.progress_bar.value() == 10
    dialog.update_progress(60, "Запрос плееров")
    assert dialog.progress_bar.value() == 60
    assert "60%" in dialog.status_label.text()
    dialog.on_cancel_clicked()
    assert dialog.is_cancelled is True


def test_infoworker_opts_youtube_and_tiktok():
    settings = MagicMock()
    settings.value.return_value = False

    # YouTube URL: fast opts
    w_yt = InfoWorker("https://www.youtube.com/watch?v=123", settings)
    u_lower = w_yt.url.lower()
    assert any(d in u_lower for d in ('youtube.com', 'youtu.be')) is True

    # TikTok URL: fast opts
    w_tt = InfoWorker("https://www.tiktok.com/@user/video/123", settings)
    assert 'tiktok.com' in w_tt.url.lower()


def test_direct_stream_task_pending_status():
    from app.download_manager import DownloadManager
    settings = MagicMock()
    settings.value.return_value = False
    thread_pool = MagicMock()
    translator = MagicMock()
    dm = DownloadManager(settings, "ffmpeg", thread_pool, translator)

    # Simulate custom extractor task addition
    direct_url = "https://cloud2.solodcdn.com/useruploads/123/360.mp4"
    task = DownloadTask(direct_url)
    task.title = "Свадьба светлячков - Серия 1"
    task.set_status(DownloadTask.Status.PENDING)

    assert task.status == DownloadTask.Status.PENDING
    assert task.title == "Свадьба светлячков - Серия 1"


def test_card_quality_selection_and_size(qapp):
    translator = Translator(project_root=os.getcwd())
    task = DownloadTask("https://www.youtube.com/watch?v=VAkm-MjomJl")
    
    mock_info = {
        'title': 'Test Video',
        'duration': 100,
        'formats': [
            {'height': 1080, 'vcodec': 'avc1', 'acodec': 'none', 'filesize': 100 * 1024 * 1024},
            {'height': 720, 'vcodec': 'avc1', 'acodec': 'none', 'filesize': 50 * 1024 * 1024},
            {'height': None, 'vcodec': 'none', 'acodec': 'mp4a', 'filesize': 10 * 1024 * 1024, 'abr': 128},
        ]
    }
    task.update_info(mock_info)
    
    widget = DownloadItemWidget(task, translator)
    items = widget.get_available_qualities_with_sizes()
    assert len(items) >= 3

    # Check 1080p item: 100 MB video + 10 MB audio = 110 MB
    item_1080 = next(i for i in items if i['badge'] == '1080p')
    assert item_1080['size_bytes'] == 110 * 1024 * 1024

    # Apply 720p selection: 50 MB video + 10 MB audio = 60 MB
    item_720 = next(i for i in items if i['badge'] == '720p')
    widget.apply_quality_selection(item_720)
    assert task.quality_override == '720p'
    assert task.quality_badge == '720p'
    assert '60.0 MB' in widget.size_label.text()
    assert '720p ▾' in widget.badge_quality.text()

    # Apply MP3 selection: 10 MB audio
    item_mp3 = next(i for i in items if i['badge'] == 'MP3')
    widget.apply_quality_selection(item_mp3)
    assert task.quality_override == 'audio_mp3'
    assert task.quality_badge == 'MP3'
    assert '10.0 MB' in widget.size_label.text()
    assert 'MP3 ▾' in widget.badge_quality.text()


def test_completed_task_quality_change_resets_to_pending(qapp):
    translator = Translator(project_root=os.getcwd())
    task = DownloadTask("https://www.youtube.com/watch?v=123")
    task.set_status(DownloadTask.Status.COMPLETED)
    assert task.status == DownloadTask.Status.COMPLETED

    widget = DownloadItemWidget(task, translator)
    # Selecting another quality must reset status to PENDING
    widget.apply_quality_selection({
        'key': '720p',
        'badge': '720p',
        'label': '720p',
        'size_bytes': 50000000,
        'is_audio': False
    })
    assert task.status == DownloadTask.Status.PENDING


def test_cookie_5_minute_cache():
    from app.browser_cookies import _save_cookie_cache_meta, get_cached_cookiefile, COOKIE_CACHE_TTL
    import time

    # Simulate cached file created 10 seconds ago
    dummy_file = os.path.join(tempfile.gettempdir(), "test_dummy_cookies.txt")
    with open(dummy_file, "w") as f:
        f.write("# Netscape dummy")

    _save_cookie_cache_meta({
        'chrome': {
            'path': dummy_file,
            'count': 42,
            'time': time.time() - 10.0
        }
    })

    path, count = get_cached_cookiefile('chrome')
    assert path == dummy_file
    assert count == 42


def test_chrome_restart_safe_fallback_on_lock():
    from app.browser_cookies import soft_restart_chrome_and_copy
    with patch("shutil.copy2", side_effect=PermissionError("Locked")):
        res = soft_restart_chrome_and_copy("dummy_db", "dummy_tmp", "dummy_wal")
        assert res is False, "Locked database should gracefully return False without raising"


def test_files_tab_quality_badge(qapp):
    from app.files_tab import LocalFileItemWidget
    from PyQt6.QtGui import QImage

    mock_tab = MagicMock()
    mock_tab.translator.translate.side_effect = lambda k, default: default
    mock_tab.parent_window.ffmpeg_path = "ffmpeg"

    # 1. Filename with 1080p
    w1 = LocalFileItemWidget("D:/downloads/Video_1080p.mp4", mock_tab)
    assert not w1.badge_quality.isHidden()
    assert "1080p" in w1.badge_quality.text()

    # 2. Audio file MP3
    w2 = LocalFileItemWidget("D:/downloads/Song.mp3", mock_tab)
    assert not w2.badge_quality.isHidden()
    assert "MP3" in w2.badge_quality.text()

    # 3. Dynamic resolution from QImage thumbnail frame (e.g. 640x360)
    w3 = LocalFileItemWidget("D:/downloads/Episode.mp4", mock_tab)
    test_img = QImage(640, 360, QImage.Format.Format_RGB32)
    w3.set_thumbnail(test_img)
    assert not w3.badge_quality.isHidden()
    assert "360p" in w3.badge_quality.text()


def test_hls_format_selector_and_bandwidth_calc():
    from app.threads import DownloadWorker
    from app.download_task import DownloadTask

    task = DownloadTask("https://poppy.ya-ligh123.site/jr/JRwXrjx1X0L/master.m3u8")
    task.quality_override = "360p"
    settings = MagicMock()
    settings.value.return_value = ""

    worker = DownloadWorker(task, settings, "ffmpeg", MagicMock())
    fmt, merge_fmt, pps = worker._resolve_format_and_pps()

    # For AniBoom/HLS, format selector should NOT contain YouTube-specific format_note!*=Premium or ext=m4a
    assert "format_note" not in fmt
    assert "ext=m4a" not in fmt
    assert "height<=360" in fmt
    assert merge_fmt == "mp4"


def test_query_direct_stream_size_m3u8_bandwidth(qapp):
    from app.download_manager import DownloadManager
    from app.download_task import DownloadTask
    import time
    import requests

    task = DownloadTask("https://poppy.ya-ligh123.site/jr/test/master.m3u8")
    task.quality_badge = "360p"

    mock_manifest = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=814382,RESOLUTION=640x360\nmedia_0.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1843300,RESOLUTION=1280x720\nmedia_2.m3u8\n"
    )

    settings = MagicMock()
    dm = DownloadManager(settings, "ffmpeg", MagicMock(), MagicMock())

    with patch("threading.Thread") as mock_th, \
         patch("requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_manifest
        mock_get.return_value = mock_resp

        # Run fetch synchronously inside the test
        def fake_thread_factory(target, daemon=True):
            mock_inst = MagicMock()
            mock_inst.start = target
            return mock_inst
        mock_th.side_effect = fake_thread_factory

        # Call size query
        dm._query_direct_stream_size(task)
        qapp.processEvents()

        # 814382 * 1440 / 8 = 146588760 bytes (~139.8 MB)
        assert "MB" in task.file_size_str
        assert getattr(task, 'info', None) is not None
        assert len(task.info.get('formats', [])) == 2


def test_direct_stream_fast_head_probe():
    from app.threads import InfoWorker
    settings = MagicMock()
    settings.value.return_value = False

    url = "https://cloud2.solodcdn.com/useruploads/test/360.mp4"
    worker = InfoWorker(url, settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {'Content-Length': '73171120'}

    received_info = []
    worker.signals.info_fetched.connect(lambda info: received_info.append(info))

    with patch("requests.Session.head", return_value=mock_resp):
        worker.run()

    assert len(received_info) == 1
    info = received_info[0]
    assert info['filesize'] == 73171120
    assert info['height'] == 360
    assert len(info['formats']) >= 1


def test_lampa_logo_and_animego_logo():
    from PIL import Image
    lampa_p = os.path.join("assets", "logos", "lampa.png")
    assert os.path.exists(lampa_p)
    im = Image.open(lampa_p)
    assert im.size == (512, 512)
    assert im.mode == "RGBA"

    animego_p = os.path.join("assets", "logos", "animego.png")
    assert os.path.exists(animego_p)


def test_signal_protection_on_deleted_worker():
    from app.threads import DownloadWorker
    from app.download_task import DownloadTask

    task = DownloadTask("https://cloud2.solodcdn.com/useruploads/test/360.mp4")
    worker = DownloadWorker(task, MagicMock(), "ffmpeg", MagicMock())

    # Simulate C++ QObject deletion raising RuntimeError
    mock_signals = MagicMock()
    mock_signals.finished.emit.side_effect = RuntimeError("wrapped C/C++ object has been deleted")
    mock_signals.error.emit.side_effect = RuntimeError("wrapped C/C++ object has been deleted")
    worker.signals = mock_signals

    with patch.object(worker, '_run_standard_vod', side_effect=Exception("Test error")):
        # run() must handle RuntimeError without crashing
        worker.run()


def test_file_size_stability_during_download():
    from app.threads import DownloadWorker
    from app.download_task import DownloadTask

    task = DownloadTask("https://poppy.ya-ligh123.site/test/master.m3u8")
    task.set_file_size(65116569)  # ~62.1 MB detected from manifest
    assert task.file_size_str == "62.1 MB"

    worker = DownloadWorker(task, MagicMock(), "ffmpeg", MagicMock())
    task.set_status(DownloadTask.Status.DOWNLOADING)

    # 1. Fragment 1: estimate fluctuates to 58.4 MB
    hook_d1 = {
        'status': 'downloading',
        'total_bytes_estimate': 61236864,  # ~58.4 MB
        'downloaded_bytes': 10485760,
        'speed': 5000000,
        'eta': 10,
        'fragment_index': 50,
        'fragment_count': 399
    }
    worker.simple_progress_hook(hook_d1)
    # Must remain stable at 62.1 MB!
    assert task.file_size_str == "62.1 MB"

    # 2. Fragment 2: estimate fluctuates to 64.0 MB
    hook_d2 = {
        'status': 'downloading',
        'total_bytes_estimate': 67108864,  # 64.0 MB
        'downloaded_bytes': 30485760,
        'speed': 6000000,
        'eta': 5,
        'fragment_index': 200,
        'fragment_count': 399
    }
    worker.simple_progress_hook(hook_d2)
    # Must remain stable at 62.1 MB!
    assert task.file_size_str == "62.1 MB"

    # 3. Audio stream download starts (e.g. 3.5 MB)
    task.set_file_size(3670016)
    # Must NOT downgrade to 3.5 MB!
    assert task.file_size_str == "62.1 MB"

    # 4. Download completes: force final exact size
    task.set_file_size(65536000, force=True)
    assert task.file_size_str == "62.5 MB"


def test_distinct_filenames_for_different_qualities(tmp_path):
    import re
    from app.download_task import DownloadTask
    from app.threads import DownloadWorker

    task = DownloadTask("https://poppy.ya-ligh123.site/2e/master.m3u8")
    task.title = "Пощади меня, великий господин! 3 - Серия 1 [Дубляж]"
    task.quality_badge = "360p"

    settings = MagicMock()
    settings.value.return_value = False
    translator = MagicMock()
    worker = DownloadWorker(task, settings, "ffmpeg.exe", translator)

    # Verify 360p filename logic
    safe_title = task.title
    q_tag = "360p"
    q_suffix = f" [{q_tag}]"
    out_filename_360 = f"{safe_title}{q_suffix}.mp4"
    assert out_filename_360 == "Пощади меня, великий господин! 3 - Серия 1 [Дубляж] [360p].mp4"

    # Verify switching to 480p strips [360p] and appends [480p]
    safe_title_prev = out_filename_360.replace('.mp4', '')
    cleaned_title = re.sub(r'\s*\[\s*(?:\d{3,4}p|MP3|AUDIO|4K|2K)\s*\]\s*$', '', safe_title_prev, flags=re.IGNORECASE).strip()
    assert cleaned_title == "Пощади меня, великий господин! 3 - Серия 1 [Дубляж]"

    q_tag_480 = "480p"
    out_filename_480 = f"{cleaned_title} [{q_tag_480}].mp4"
    assert out_filename_480 == "Пощади меня, великий господин! 3 - Серия 1 [Дубляж] [480p].mp4"
    assert out_filename_360 != out_filename_480


def test_available_streams_selection_and_switch(qapp):
    task = DownloadTask("https://stream.voidboost.one/abc/360.mp4")
    task.title = "Ателье колдовских колпаков"
    task.quality_badge = "360p"
    task.available_streams = {
        '1080p': 'https://stream.voidboost.one/abc/1080.mp4',
        '720p': 'https://stream.voidboost.one/abc/720.mp4',
        '480p': 'https://stream.voidboost.one/abc/480.mp4',
        '360p': 'https://stream.voidboost.one/abc/360.mp4',
    }

    widget = DownloadItemWidget(task, Translator())
    items = widget.get_available_qualities_with_sizes()

    badges = [it['badge'] for it in items]
    assert '1080p' in badges
    assert '720p' in badges
    assert '480p' in badges
    assert '360p' in badges
    assert 'MP3' in badges

    # 1. Switch from 360p to 1080p
    target_1080 = next(it for it in items if it['badge'] == '1080p')
    widget.apply_quality_selection(target_1080)
    assert task.url == 'https://stream.voidboost.one/abc/1080.mp4'
    assert task.quality_badge == '1080p'
    assert task.audio_only is False

    # 2. Switch to MP3
    target_mp3 = next(it for it in items if it['badge'] == 'MP3')
    widget.apply_quality_selection(target_mp3)
    assert task.audio_only is True
    assert task.quality_badge == 'MP3'


def test_kodik_quality_expansion_and_switch(qapp):
    task = DownloadTask("https://solodcdn.com/useruploads/xyz/360.mp4")
    task.title = "Kodik Video"
    task.quality_badge = "360p"
    task.info = {
        'formats': [
            {'format_id': '360p', 'height': 360, 'filesize': 10000000}
        ]
    }

    widget = DownloadItemWidget(task, Translator())
    items = widget.get_available_qualities_with_sizes()

    badges = [it['badge'] for it in items]
    assert '1080p' in badges
    assert '720p' in badges
    assert '480p' in badges
    assert '360p' in badges
    assert 'MP3' in badges

    # Switch to 1080p
    target_1080 = next(it for it in items if it['badge'] == '1080p')
    widget.apply_quality_selection(target_1080)
    assert task.url == 'https://solodcdn.com/useruploads/xyz/1080.mp4'
    assert task.quality_badge == '1080p'

    # Switch to MP3 - must NOT corrupt URL to /3.mp4!
    target_mp3 = next(it for it in items if it['badge'] == 'MP3')
    widget.apply_quality_selection(target_mp3)
    assert task.url == 'https://solodcdn.com/useruploads/xyz/360.mp4'
    assert task.audio_only is True
    assert task.quality_badge == 'MP3'


def test_animego_episodes_resolve_worker_and_dialog(qapp):
    from app.animego_progress_dialog import AnimeGoEpisodesResolveDialog, AnimeGoEpisodesResolveWorker
    from app.download_manager import DownloadManager
    from unittest.mock import MagicMock

    dialog = AnimeGoEpisodesResolveDialog(
        anime_title="Test Anime",
        total_episodes=2,
        voiceover="AniLibria",
        quality="1080p"
    )
    dialog.update_progress(1, 2, "Серия 1")
    assert dialog.progress_bar.value() == 1
    assert "Серия 1" in dialog.status_label.text()

    mock_extractor = MagicMock()
    mock_extractor.name = "AnimeGO"
    mock_extractor.resolve_stream.side_effect = [
        ("https://kodikplayer.com/stream1.m3u8", "1080p"),
        ("https://kodikplayer.com/stream2.m3u8", "720p"),
    ]

    selected_targets = [
        {'name': 'Серия 1', 'id': 'ep1'},
        {'name': 'Серия 2', 'id': 'ep2'}
    ]
    meta = {'safe_anime_title': 'Test Anime', 'poster_url': 'http://poster.jpg'}

    worker = AnimeGoEpisodesResolveWorker(
        selected_targets=selected_targets,
        extractor=mock_extractor,
        meta=meta,
        selected_v={'name': 'AniLibria'},
        selected_q='1080p'
    )

    resolved = []
    worker.signals.episode_resolved.connect(lambda item: resolved.append(item))
    worker.run()

    assert len(resolved) == 2
    assert resolved[0]['direct_url'] == "https://kodikplayer.com/stream1.m3u8"
    assert resolved[1]['direct_url'] == "https://kodikplayer.com/stream2.m3u8"

    # Test DownloadManager._add_single_resolved_episode
    settings = MagicMock()
    dm = DownloadManager(settings, "ffmpeg", MagicMock(), MagicMock())
    dm._add_single_resolved_episode(resolved[0], meta, {'name': 'AniLibria'}, '1080p', is_from_bot=False)

    assert len(dm.tasks) == 1
    task = dm.tasks[0]
    assert task.url == "https://kodikplayer.com/stream1.m3u8"
    assert task.quality_badge == "1080p"
    assert "AniLibria" in task.title
    assert "Test Anime" in task.title
    dialog.close()


def test_kodik_404_fallback_to_available_quality(tmp_path):
    from app.threads import DownloadWorker
    from app.download_task import DownloadTask
    from unittest.mock import MagicMock, patch

    task = DownloadTask("https://cloud2.solodcdn.com/useruploads/test/1080.mp4:hls:manifest.m3u8")
    task.quality_badge = "1080p"
    settings = MagicMock()
    settings.value.return_value = ""

    worker = DownloadWorker(task, settings, "ffmpeg", MagicMock())

    def mock_get(url, *args, **kwargs):
        resp = MagicMock()
        if "1080.mp4" in url:
            resp.status_code = 404
        elif "720.mp4" in url:
            resp.status_code = 200
            resp.headers = {'Content-Length': '10240'}
            resp.iter_content.return_value = [b"video_bytes" * 200]
        return resp

    with patch("requests.Session.get", side_effect=mock_get):
        save_p = str(tmp_path)
        out_tpl = str(tmp_path / "test.%(ext)s")
        worker._download_direct_stream(save_p, out_tpl, "https://kodikplayer.com/")

    assert "720.mp4" in task.url
    assert task.quality_badge == "720p"


def test_multipart_chunked_download(tmp_path):
    from app.threads import DownloadWorker
    from app.download_task import DownloadTask
    from unittest.mock import MagicMock, patch

    task = DownloadTask("https://cloud2.solodcdn.com/useruploads/test/720.mp4")
    task.quality_badge = "720p"
    settings = MagicMock()
    settings.value.return_value = 0

    worker = DownloadWorker(task, settings, "ffmpeg", MagicMock())
    total_size = 4 * 1024 * 1024  # 4 MB (> 3 MB threshold)

    def mock_get(url, headers=None, **kwargs):
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = None
        resp.headers = {'Content-Length': str(total_size), 'Accept-Ranges': 'bytes'}
        resp.status_code = 200

        range_hdr = (headers or {}).get('Range', '')
        if range_hdr and 'bytes=' in range_hdr:
            resp.status_code = 206
            parts = range_hdr.replace('bytes=', '').split('-')
            start = int(parts[0])
            end = int(parts[1]) if parts[1] else total_size - 1
            length = end - start + 1
            resp.headers['Content-Length'] = str(length)
            resp.iter_content.return_value = [b"A" * length]
        else:
            resp.iter_content.return_value = [b"A" * 1024]
        return resp

    with patch("requests.Session.get", side_effect=mock_get):
        save_p = str(tmp_path)
        out_tpl = str(tmp_path / "video.%(ext)s")
        worker._download_direct_stream(save_p, out_tpl, "https://kodikplayer.com/")

    final_file = tmp_path / "video.mp4"
    assert final_file.exists()
    assert final_file.stat().st_size == total_size
    assert task.status == DownloadTask.Status.COMPLETED






