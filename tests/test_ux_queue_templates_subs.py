import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings

from app.download_task import DownloadTask
from app.download_manager import DownloadManager
from app.stream_helper import StreamResolverHelper
from app.threads import DownloadWorker


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_resolve_output_template_presets(tmp_path):
    base = str(tmp_path)

    # 1. Standard preset
    t_yt = DownloadTask("https://www.youtube.com/watch?v=abc")
    t_yt.title = "My Video: Demo?"
    t_yt.platform = "Youtube"
    p1 = StreamResolverHelper.resolve_output_template(
        base, "{title} [{quality}]", t_yt, quality_tag="1080p", is_ytdlp=True
    )
    assert p1 == os.path.join(base, "My Video Demo [1080p].%(ext)s")

    # 2. By platform preset
    p2 = StreamResolverHelper.resolve_output_template(
        base, "{platform}/{title} [{quality}]", t_yt, quality_tag="720p", is_ytdlp=True
    )
    assert p2 == os.path.join(base, "YouTube", "My Video Demo [720p].%(ext)s")
    assert os.path.isdir(os.path.join(base, "YouTube"))

    # 3. Series preset WITH series metadata -> creates nested Series/Season folder
    t_series = DownloadTask("https://cloud2.solodcdn.com/u/720.mp4")
    t_series.custom_title = "Attack on Titan - Серия 5 [AniLibria]"
    t_series.series_name = "Attack on Titan"
    t_series.season_name = "1 Сезон"
    t_series.episode_name = "Серия 5"
    p3 = StreamResolverHelper.resolve_output_template(
        base, "{series}/{season}/{title} [{quality}]", t_series, quality_tag="1080p", is_ytdlp=True
    )
    assert p3 == os.path.join(base, "Attack on Titan", "1 Сезон", "Attack on Titan - Серия 5 [AniLibria] [1080p].%(ext)s")
    assert os.path.isdir(os.path.join(base, "Attack on Titan", "1 Сезон"))

    # 4. Series preset WITHOUT series metadata -> cleanly collapses empty folders
    p4 = StreamResolverHelper.resolve_output_template(
        base, "{series}/{season}/{title} [{quality}]", t_yt, quality_tag="", is_ytdlp=True
    )
    assert p4 == os.path.join(base, "My Video Demo.%(ext)s")

    # 5. Non-ytdlp mode (Twitch live / direct) with range suffix
    t_tw = DownloadTask("https://www.twitch.tv/caedrel")
    t_tw.custom_title = "Caedrel Live"
    p5 = StreamResolverHelper.resolve_output_template(
        base, "{platform}/{title} [{quality}]", t_tw, quality_tag="1080p60", range_suffix="_[00-10_01-00]", is_ytdlp=False
    )
    assert p5 == os.path.join(base, "Twitch", "Caedrel Live [1080p60]_[00-10_01-00]")


def test_parse_subtitle_langs():
    assert StreamResolverHelper.parse_subtitle_langs("ru, en, uk") == ["ru", "en", "uk"]
    assert StreamResolverHelper.parse_subtitle_langs("JA; en ru ja") == ["ja", "en", "ru"]
    assert StreamResolverHelper.parse_subtitle_langs("all") == ["all"]
    assert StreamResolverHelper.parse_subtitle_langs("") == ["ru", "en"]


def test_queue_priority_reordering(qapp, tmp_path):
    ini = str(tmp_path / "test_queue.ini")
    settings = QSettings(ini, QSettings.Format.IniFormat)
    settings.setValue("auto_start_downloads", False)
    settings.setValue("save_path", str(tmp_path))

    from app.translation import Translator
    from app.main_window import MainWindow

    translator = Translator()
    with patch.object(MainWindow, 'check_ffmpeg', return_value="ffmpeg"):
        win = MainWindow(translator, settings)

    t1 = DownloadTask("https://example.com/1")
    t1.title = "First"
    t2 = DownloadTask("https://example.com/2")
    t2.title = "Second"
    t3 = DownloadTask("https://example.com/3")
    t3.title = "Third"

    for t in (t1, t2, t3):
        win.download_manager.tasks.append(t)
        win.download_manager.task_added.emit(t)

    assert [t.title for t in win.download_manager.tasks] == ["First", "Second", "Third"]
    assert win.downloads_list.count() == 3

    # Move Third to Top
    win.download_manager.move_task_to_top(t3)
    assert [t.title for t in win.download_manager.tasks] == ["Third", "First", "Second"]
    assert win.downloads_list.itemWidget(win.downloads_list.item(0)).task is t3

    # Move Third Down -> index 1
    win.download_manager.move_task_down(t3)
    assert [t.title for t in win.download_manager.tasks] == ["First", "Third", "Second"]
    assert win.downloads_list.itemWidget(win.downloads_list.item(1)).task is t3

    # Move Second Up -> index 1
    win.download_manager.move_task_up(t2)
    assert [t.title for t in win.download_manager.tasks] == ["First", "Second", "Third"]

    # Move First to Bottom -> index 2
    win.download_manager.move_task_to_bottom(t1)
    assert [t.title for t in win.download_manager.tasks] == ["Second", "Third", "First"]
    assert win.downloads_list.itemWidget(win.downloads_list.item(2)).task is t1

    win.close()


def test_advanced_subtitles_and_settings_tab(qapp, tmp_path):
    ini = str(tmp_path / "test_subs.ini")
    settings = QSettings(ini, QSettings.Format.IniFormat)
    settings.setValue("subtitles_enabled", True)
    settings.setValue("subtitles_langs", "ru, en, ja")
    settings.setValue("subtitles_mode", "both")
    settings.setValue("subtitles_format", "srt")
    settings.setValue("filename_template", "{platform}/{title} [{quality}]")

    from app.translation import Translator
    from app.main_window import MainWindow

    translator = Translator()
    with patch.object(MainWindow, 'check_ffmpeg', return_value="ffmpeg"):
        win = MainWindow(translator, settings)

    # Trigger lazy SettingsTab initialization
    win._show_settings_tab()
    st = win.settings_page

    assert st.subtitles_checkbox.isChecked() is True
    assert st.subtitles_options_widget.isHidden() is False
    assert st.subtitles_langs_input.text() == "ru, en, ja"
    assert st.subtitles_mode_combo.currentData() == "both"
    assert st.subtitles_format_combo.currentData() == "srt"
    assert st.filename_template_combo.currentData() == "{platform}/{title} [{quality}]"

    # Change mode to separate and verify persistence
    st.set_combo_by_data(st.subtitles_mode_combo, "separate")
    assert settings.value("subtitles_mode") == "separate"

    # Verify DownloadWorker builds correct yt-dlp subtitle opts
    task = DownloadTask("https://www.youtube.com/watch?v=xyz")
    task.title = "SubVideo"
    task.quality_badge = "1080p"

    captured_opts = {}

    class FakeYDL:
        def __init__(self, opts):
            captured_opts.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def download(self, urls):
            # Create dummy output file so _run_standard_vod finishes cleanly
            out_dir = os.path.dirname(captured_opts['outtmpl'])
            os.makedirs(out_dir, exist_ok=True)
            dummy_mp4 = os.path.join(out_dir, "SubVideo [1080p].mp4")
            with open(dummy_mp4, "wb") as f:
                f.write(b"0" * 2048)
            return 0

    settings.setValue("save_path", str(tmp_path))
    settings.setValue("subtitles_mode", "both")
    settings.setValue("enable_aria2c", False)
    worker = DownloadWorker(task, settings, "ffmpeg", translator)

    with patch("app.threads.yt_dlp.YoutubeDL", FakeYDL):
        worker._run_standard_vod(str(tmp_path))

    assert captured_opts["writesubtitles"] is True
    assert captured_opts["subtitleslangs"] == ["ru", "en", "ja"]
    assert captured_opts["subtitlesformat"] == "srt/best"
    pp_keys = {p["key"]: p for p in captured_opts["postprocessors"]}
    assert "FFmpegSubtitlesConvertor" in pp_keys
    assert pp_keys["FFmpegSubtitlesConvertor"]["format"] == "srt"
    assert "FFmpegEmbedSubtitle" in pp_keys
    assert pp_keys["FFmpegEmbedSubtitle"]["already_have_subtitle"] is True
    assert "YouTube" in captured_opts["outtmpl"]

    win.close()


def test_files_tab_recursive_subfolder_scan(qapp, tmp_path):
    ini = str(tmp_path / "test_files.ini")
    settings = QSettings(ini, QSettings.Format.IniFormat)
    sub_dir = tmp_path / "YouTube"
    sub_dir.mkdir(parents=True)
    vid = sub_dir / "nested_video [1080p].mp4"
    vid.write_bytes(b"1234" * 512)
    settings.setValue("save_path", str(tmp_path))

    from app.translation import Translator
    from app.main_window import MainWindow

    translator = Translator()
    with patch.object(MainWindow, 'check_ffmpeg', return_value="ffmpeg"):
        win = MainWindow(translator, settings)

    win._show_files_tab()
    import time
    deadline = time.monotonic() + 3.0
    while win.files_page.files_list.count() == 0 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    assert win.files_page.files_list.count() == 1
    w = win.files_page.files_list.itemWidget(win.files_page.files_list.item(0))
    assert os.path.normpath(w.filepath) == os.path.normpath(str(vid))
    win.close()


def test_incomplete_task_only_resume_and_delete(qapp, tmp_path):
    from app.translation import Translator
    from app.download_item_widget import DownloadItemWidget

    translator = Translator()
    task = DownloadTask("https://example.com/video")
    task.title = "Partial Video"
    task.quality_badge = "1080p"

    widget = DownloadItemWidget(task, translator)

    for incomplete_status in (DownloadTask.Status.STOPPED, DownloadTask.Status.ERROR):
        task.set_status(incomplete_status)
        assert widget.download_button.isHidden() is False
        assert widget.remove_button.isHidden() is False
        assert widget.play_button.isHidden() is True
        assert widget.timerange_button.isHidden() is True
        assert widget.folder_button.isHidden() is True
        assert widget.move_up_button.isHidden() is True
        assert widget.move_down_button.isHidden() is True
        assert widget.btn_copy_url.isHidden() is True
        assert widget.badge_quality.isEnabled() is False

    downloaded_1080 = tmp_path / "Partial Video [1080p].mp4"
    downloaded_1080.write_bytes(b"0" * 2048)
    task.set_completed(str(downloaded_1080))
    assert widget.play_button.isHidden() is False
    assert widget.folder_button.isHidden() is False
    assert widget.timerange_button.isHidden() is False
    assert widget.download_button.isHidden() is True
    assert widget.remove_button.isHidden() is False
    assert widget.badge_quality.isEnabled() is True

    # Selecting same quality keeps COMPLETED and keeps download_button hidden
    widget.apply_quality_selection({'key': '1080p', 'badge': '1080p', 'label': '1080p', 'size_bytes': 0, 'is_audio': False})
    assert task.status == DownloadTask.Status.COMPLETED
    assert widget.download_button.isHidden() is True

    # Selecting another quality resets to PENDING and shows download_button
    widget.apply_quality_selection({'key': '720p', 'badge': '720p', 'label': '720p', 'size_bytes': 0, 'is_audio': False})
    assert task.status == DownloadTask.Status.PENDING
    assert widget.download_button.isHidden() is False
    assert widget.play_button.isHidden() is True

    # Switching back to originally downloaded 1080p restores COMPLETED & Play/Folder buttons
    widget.apply_quality_selection({'key': '1080p', 'badge': '1080p', 'label': '1080p', 'size_bytes': 0, 'is_audio': False})
    assert task.status == DownloadTask.Status.COMPLETED
    assert task.final_filepath == str(downloaded_1080)
    assert widget.download_button.isHidden() is True
    assert widget.play_button.isHidden() is False
    assert widget.folder_button.isHidden() is False
    widget.disconnect_signals()

