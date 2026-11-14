import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from PyQt6.QtCore import QSettings, Qt, QThreadPool
from PyQt6.QtWidgets import QApplication

# Configure headless offscreen mode
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app

@pytest.fixture
def test_settings(tmp_path):
    ini_path = str(tmp_path / "test_settings.ini")
    return QSettings(ini_path, QSettings.Format.IniFormat)

@pytest.fixture
def translator():
    from app.translation import Translator
    return Translator()


# ============================================================================
# PART B: Tests for DownloadTask, DownloadManager, Threads & Extractors
# ============================================================================

def test_download_task_states_and_badges(qapp):
    from app.download_task import DownloadTask
    task = DownloadTask("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert task.status == DownloadTask.Status.FETCHING_INFO
    assert task.platform == "Unknown"
    task.platform = "YouTube"
    assert task.platform == "YouTube"

    task.set_file_size(10485760)  # 10 MB
    assert "10.0 MB" in task.file_size_str

    task.update_progress(50, "50% (2.5 MB/s)")
    assert task.progress == 50
    assert "50%" in task.progress_text

    task.set_completed("C:/dummy/video.mp4")
    assert task.status == DownloadTask.Status.COMPLETED
    assert task.final_filepath == "C:/dummy/video.mp4"

def test_download_manager_duplicates_and_normalization(test_settings, qapp, translator):
    from app.download_manager import DownloadManager
    from app.download_task import DownloadTask

    pool = QThreadPool()
    dm = DownloadManager(test_settings, "assets/ffmpeg/bin/ffmpeg.exe", pool, translator)

    # Test URL normalization on Kick video URLs
    url_kick = "https://kick.com/streamer/videos/abcdef12"
    norm = dm._normalize_url(url_kick)
    assert norm == "https://kick.com/video/abcdef12"

    # Add URL with timerange
    dm.add_urls(["https://www.youtube.com/watch?v=dQw4w9WgXcQ"], prompt_time_range=True)
    assert len(dm.tasks) == 1
    t = dm.tasks[0]
    assert t.prompt_time_range is True

    # Duplicate active task should be skipped
    t.set_status(DownloadTask.Status.DOWNLOADING)
    dm.add_urls(["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
    assert len(dm.tasks) == 1

def test_custom_extractors_matching():
    from app.extractors import find_extractor_for_url
    assert find_extractor_for_url("https://www.youtube.com/watch?v=123") is None

    ext_pin = find_extractor_for_url("https://pinterest.com/pin/123456")
    assert ext_pin is not None
    assert hasattr(ext_pin, 'fetch_metadata')

def test_threads_youtube_premium_format_filtering(test_settings):
    from app.threads import DownloadWorker
    from app.download_task import DownloadTask
    from app.translation import Translator

    task = DownloadTask("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    worker = DownloadWorker(task, test_settings, "assets/ffmpeg/bin/ffmpeg.exe", Translator())

    fmt, merge_fmt, pps = worker._resolve_format_and_pps()
    assert "[format_note!*=Premium]" in fmt
    # Verify no bare bestvideo without premium exclusion
    parts = fmt.split('/')
    for part in parts:
        if 'bestvideo' in part:
            assert '[format_note!*=Premium]' in part


# ============================================================================
# PART C: Tests for GUI (MainWindow, Tabs, Dialogs, Theme & Language)
# ============================================================================

def test_main_window_init_and_tabs(qapp, test_settings, translator):
    from app.main_window import MainWindow
    win = MainWindow(translator, test_settings)
    win.download_manager.fetch_video_info = lambda task: None
    win.resize(1000, 700)
    win.show()

    # Verify button is TransparentToggleToolButton 35x35
    assert win.btn_timerange_mode is not None
    assert win.btn_timerange_mode.size().width() == 35
    assert win.btn_timerange_mode.size().height() == 35

    # Verify tabs lazy-loading
    hist = win.history_page
    assert hist is not None
    files = win.files_page
    assert files is not None
    sett = win.settings_page
    assert sett is not None
    about = win.about_page
    assert about is not None
    tg = win.telegram_page
    assert tg is not None

def test_theme_switching(qapp, test_settings, translator):
    from app.main_window import MainWindow
    from app.theme_manager import ThemeManager

    win = MainWindow(translator, test_settings)
    win.download_manager.fetch_video_info = lambda task: None
    tm = ThemeManager(test_settings, win)

    test_settings.setValue('theme', 'dark')
    tm.apply_theme()
    assert "#MainWindow, QDialog" in tm.get_dark_theme()
    assert "#TimerangeButton" in tm.get_dark_theme()

    test_settings.setValue('theme', 'light')
    tm.apply_theme()
    assert "#MainWindow, QDialog" in tm.get_light_theme()
    assert "#TimerangeButton" in tm.get_light_theme()

    # Revert to dark
    test_settings.setValue('theme', 'dark')
    tm.apply_theme()

def test_language_switching(qapp, test_settings, translator):
    from app.main_window import MainWindow
    win = MainWindow(translator, test_settings)
    win.download_manager.fetch_video_info = lambda task: None

    # Switch languages: 0: en, 1: ru, 2: uk
    win.on_language_change(0)
    assert translator.current_language == 'en'
    assert win.translator.translate('downloads') != ''

    win.on_language_change(1)
    assert translator.current_language == 'ru'

    win.on_language_change(2)
    assert translator.current_language == 'uk'

    win.on_language_change(1)
    assert translator.current_language == 'ru'

def test_dialogs_instantiation(qapp, translator):
    from app.download_task import DownloadTask
    from app.download_item_widget import TimeRangeDialog
    from app.batch_dialog import BatchAddDialog
    from app.scheduler_dialog import SchedulerDialog

    task = DownloadTask("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    task.info = {'duration': 212}

    # TimeRangeDialog
    dlg_tr = TimeRangeDialog(task, translator, is_pre_download=True)
    assert dlg_tr is not None
    assert dlg_tr.input_start.text() == "00:00:00"
    assert dlg_tr.input_end.text() == "00:03:32"

    # BatchAddDialog
    dlg_batch = BatchAddDialog(translator)
    assert dlg_batch is not None

    # SchedulerDialog
    dlg_sched = SchedulerDialog(None, translator)
    assert dlg_sched is not None

def test_recent_and_history_timerange_integration(qapp, test_settings, translator):
    from app.main_window import MainWindow
    win = MainWindow(translator, test_settings)
    win.download_manager.fetch_video_info = lambda task: None

    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # With timerange mode active
    win.btn_timerange_mode.setChecked(True)
    win.download_manager.tasks.clear()
    win._add_recent_and_queue(url)
    assert len(win.download_manager.tasks) == 1
    assert win.download_manager.tasks[0].prompt_time_range is True

    win.download_manager.tasks.clear()
    win._redownload_from_history(url)
    assert len(win.download_manager.tasks) == 1
    assert win.download_manager.tasks[0].prompt_time_range is True

    # With timerange mode inactive but force_timerange=True (context menu)
    win.btn_timerange_mode.setChecked(False)
    win.download_manager.tasks.clear()
    win._add_recent_and_queue(url, force_timerange=True)
    assert len(win.download_manager.tasks) == 1
    assert win.download_manager.tasks[0].prompt_time_range is True

    win.download_manager.tasks.clear()
    win._redownload_from_history(url, force_timerange=True)
    assert len(win.download_manager.tasks) == 1
    assert win.download_manager.tasks[0].prompt_time_range is True
