import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
import qfluentwidgets
qfluentwidgets.setTheme = lambda *a, **kw: None
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings

from app.translation import Translator
from app.download_task import DownloadTask
from app.main_window import MainWindow

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app

@pytest.fixture
def test_settings(tmp_path):
    ini_path = str(tmp_path / "test_settings.ini")
    s = QSettings(ini_path, QSettings.Format.IniFormat)
    s.clear()
    return s

@pytest.fixture
def translator():
    return Translator(project_root=os.getcwd())

def test_autostart_disabled_by_default(qapp, test_settings, translator):
    """Test that auto_start_downloads is False by default and task stays in PENDING."""
    win = MainWindow(translator, test_settings)
    win.download_manager.fetch_video_info = lambda task: None

    # Check setting default
    assert test_settings.value('auto_start_downloads', False, type=bool) is False

    started_tasks = []
    win.download_manager.start_or_retry_task = lambda t: started_tasks.append(t)

    task = DownloadTask("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    task.is_from_bot = False
    task.prompt_time_range = False

    # Simulate info fetched and task becomes PENDING
    win._on_task_status_changed(task, DownloadTask.Status.PENDING)

    # Must NOT have started
    assert len(started_tasks) == 0

def test_autostart_enabled_behavior(qapp, test_settings, translator):
    """Test that when auto_start_downloads is True, task automatically starts."""
    test_settings.setValue('auto_start_downloads', True)
    win = MainWindow(translator, test_settings)
    win.download_manager.fetch_video_info = lambda task: None

    started_tasks = []
    win.download_manager.start_or_retry_task = lambda t: started_tasks.append(t)

    task = DownloadTask("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    task.is_from_bot = False
    task.prompt_time_range = False

    win._on_task_status_changed(task, DownloadTask.Status.PENDING)

    # Must have started
    assert len(started_tasks) == 1
    assert started_tasks[0] == task

def test_bot_always_autostarts_even_when_setting_disabled(qapp, test_settings, translator):
    """Test that telegram bot links always auto-start even if auto_start_downloads is False."""
    test_settings.setValue('auto_start_downloads', False)
    win = MainWindow(translator, test_settings)
    win.download_manager.fetch_video_info = lambda task: None

    started_tasks = []
    win.download_manager.start_or_retry_task = lambda t: started_tasks.append(t)

    task = DownloadTask("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    task.is_from_bot = True
    task.prompt_time_range = False

    win._on_task_status_changed(task, DownloadTask.Status.PENDING)

    # Must have started because is_from_bot is True
    assert len(started_tasks) == 1
    assert started_tasks[0] == task

def test_settings_tab_autostart_toggle(qapp, test_settings, translator):
    """Test that SettingsTab has auto_start_checkbox and toggling updates settings."""
    win = MainWindow(translator, test_settings)
    win.download_manager.fetch_video_info = lambda task: None

    settings_page = win.settings_page
    assert hasattr(settings_page, 'auto_start_checkbox')

    # Initially False
    assert settings_page.auto_start_checkbox.isChecked() is False

    # Toggle to True
    settings_page.auto_start_checkbox.setChecked(True)
    assert test_settings.value('auto_start_downloads', False, type=bool) is True

    # Toggle to False
    settings_page.auto_start_checkbox.setChecked(False)
    assert test_settings.value('auto_start_downloads', False, type=bool) is False
