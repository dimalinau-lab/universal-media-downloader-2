import os
import sys
from unittest.mock import MagicMock, patch
import pytest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.download_task import DownloadTask
from app.threads import DownloadWorker
from app.stream_helper import StreamResolverHelper


def test_twitch_routing_vod_vs_live():
    settings = MagicMock()
    translator = MagicMock()

    # 1. Twitch Channel (Прямой эфир) -> должен вызывать _run_twitch_stream
    live_task = DownloadTask("https://www.twitch.tv/shroud")
    worker_live = DownloadWorker(live_task, settings, "ffmpeg.exe", translator)

    with patch.object(worker_live, '_run_twitch_stream') as mock_twitch_stream, \
         patch.object(worker_live, '_run_standard_vod') as mock_vod:
        worker_live.run()
        mock_twitch_stream.assert_called_once()
        mock_vod.assert_not_called()

    # 2. Twitch VOD (Запись стрима /videos/) -> должен вызывать _run_standard_vod
    vod_task = DownloadTask("https://www.twitch.tv/videos/2290456182")
    worker_vod = DownloadWorker(vod_task, settings, "ffmpeg.exe", translator)

    with patch.object(worker_vod, '_run_twitch_stream') as mock_twitch_stream, \
         patch.object(worker_vod, '_run_standard_vod') as mock_vod:
        worker_vod.run()
        mock_vod.assert_called_once()
        mock_twitch_stream.assert_not_called()

    # 3. Twitch Clip (/clip/) -> должен вызывать _run_standard_vod
    clip_task = DownloadTask("https://www.twitch.tv/shroud/clip/FrailTameGrasshopper")
    worker_clip = DownloadWorker(clip_task, settings, "ffmpeg.exe", translator)

    with patch.object(worker_clip, '_run_twitch_stream') as mock_twitch_stream, \
         patch.object(worker_clip, '_run_standard_vod') as mock_vod:
        worker_clip.run()
        mock_vod.assert_called_once()
        mock_twitch_stream.assert_not_called()

    # 4. clips.twitch.tv -> должен вызывать _run_standard_vod
    clips_sub_task = DownloadTask("https://clips.twitch.tv/FrailTameGrasshopper")
    worker_sub = DownloadWorker(clips_sub_task, settings, "ffmpeg.exe", translator)

    with patch.object(worker_sub, '_run_twitch_stream') as mock_twitch_stream, \
         patch.object(worker_sub, '_run_standard_vod') as mock_vod:
        worker_sub.run()
        mock_vod.assert_called_once()
        mock_twitch_stream.assert_not_called()


def test_twitch_offline_error_formatting():
    err = "ERROR: [twitch:stream] shroud: The channel is not currently live"
    friendly = StreamResolverHelper.format_user_friendly_error(err)
    assert "не в эфире" in friendly.lower() or "оффлайн" in friendly.lower()


def test_twitch_cdn_url_recovery():
    settings = MagicMock()
    translator = MagicMock()

    # Если в task.url попал временный CDN eun17.playlist.ttvnw.net
    corrupted_task = DownloadTask("https://eun17.playlist.ttvnw.net/v1/playlist/test.m3u8")
    corrupted_task.original_url = "https://www.twitch.tv/caedrel"

    worker = DownloadWorker(corrupted_task, settings, "ffmpeg.exe", translator)
    with patch.object(worker, '_run_twitch_stream') as mock_twitch_stream, \
         patch.object(worker, '_run_standard_vod') as mock_vod:
        worker.run()
        # Должен восстановить оригинальный URL и запустить запись стрима
        assert corrupted_task.url == "https://www.twitch.tv/caedrel"
        mock_twitch_stream.assert_called_once()
        mock_vod.assert_not_called()


def test_twitch_run_twitch_stream_format_resolution(tmp_path):
    settings = MagicMock()
    translator = MagicMock()
    task = DownloadTask("https://www.twitch.tv/strogo")
    task.quality_override = "1080p60"

    worker = DownloadWorker(task, settings, "ffmpeg.exe", translator)
    with patch("shutil.disk_usage") as mock_disk, \
         patch("yt_dlp.YoutubeDL") as mock_ydl, \
         patch("subprocess.Popen") as mock_popen, \
         patch("threading.Thread"):
        mock_disk.return_value = MagicMock(free=10 * 1024 * 1024 * 1024)
        mock_ydl_inst = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_ydl_inst
        mock_ydl_inst.extract_info.return_value = {
            'url': 'https://mock.stream.m3u8',
            'title': 'StRoGo (live)'
        }
        mock_popen.return_value.poll.return_value = 0

        worker._run_twitch_stream(str(tmp_path))
        assert mock_popen.called
        cmd = mock_popen.call_args[0][0]
        assert "ffmpeg.exe" in cmd[0]
        assert "https://mock.stream.m3u8" in cmd


