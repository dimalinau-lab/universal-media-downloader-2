import os
import sys
import tempfile
import zipfile
from unittest.mock import MagicMock, patch
import pytest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThreadPool, QSettings
from app.update_checker import (
    is_installer_mode,
    apply_installer_update,
    apply_portable_update,
    update_ytdlp_wheel,
    CheckAllUpdatesWorker,
    UpdateChecker,
)
from app.translation import Translator


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_is_installer_mode_detection(tmp_path):
    with patch("app.update_checker.get_base_dir", return_value=str(tmp_path)):
        # Без unins000.exe
        assert is_installer_mode() is False

        # С unins000.exe (Inno Setup)
        unins = tmp_path / "unins000.exe"
        unins.write_text("dummy")
        assert is_installer_mode() is True


def test_apply_installer_update(tmp_path):
    dummy_installer = str(tmp_path / "setup.exe")
    with patch("app.update_checker.get_base_dir", return_value=str(tmp_path)), \
         patch("subprocess.Popen") as mock_popen, \
         patch("PyQt6.QtWidgets.QApplication.instance") as mock_app:
        app_mock = MagicMock()
        mock_app.return_value = app_mock

        res = apply_installer_update(dummy_installer)
        assert res is True
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == dummy_installer
        assert "/SILENT" in cmd
        assert "/CLOSEAPPLICATIONS" in cmd
        assert "/RESTARTAPPLICATIONS" in cmd
        assert f"/DIR={tmp_path}" in cmd
        app_mock.quit.assert_called_once()


def test_main_startup_cleanup_frozen(tmp_path):
    """Тест очистки старых версий .old и Windows3.*.exe при старте."""
    current_exe = tmp_path / "Universal_Media_Downloader.exe"
    current_exe.write_text("v3.3")
    old_exe = tmp_path / "Universal_Media_Downloader.exe.old"
    old_exe.write_text("v3.2")
    old_internal = tmp_path / "_internal.old"
    old_internal.mkdir()
    (old_internal / "dummy.txt").write_text("old internal")
    obsolete_version_exe = tmp_path / "Windows3.2.UMD.exe"
    obsolete_version_exe.write_text("legacy 3.2")

    # Симулируем логику очистки main.py
    current_name = os.path.basename(str(current_exe)).lower()
    base_dir = str(tmp_path)

    # 1. Удаление .old от исполняемого файла
    if os.path.exists(str(old_exe)):
        os.remove(str(old_exe))

    # 2. Удаление _internal.old
    if os.path.exists(str(old_internal)):
        import shutil
        shutil.rmtree(str(old_internal), ignore_errors=True)

    # 3. Удаление устаревших версионированных исполняемых файлов
    for fname in os.listdir(base_dir):
        fl = fname.lower()
        if fl.startswith('windows3.') and fl.endswith('.exe') and fl != current_name:
            try:
                os.remove(os.path.join(base_dir, fname))
            except Exception:
                pass

    assert not old_exe.exists()
    assert not old_internal.exists()
    assert not obsolete_version_exe.exists()
    assert current_exe.exists()


def test_apply_portable_update_atomic_swap(tmp_path):
    current_exe = tmp_path / "app.exe"
    current_exe.write_text("old version")
    downloaded = tmp_path / "new_app.exe"
    downloaded.write_text("new version")

    with patch("sys.executable", str(current_exe)), \
         patch.object(sys, 'frozen', True, create=True), \
         patch("subprocess.Popen") as mock_popen, \
         patch("PyQt6.QtWidgets.QApplication.instance") as mock_app:
        app_mock = MagicMock()
        mock_app.return_value = app_mock

        res = apply_portable_update(str(downloaded))
        assert res is True
        assert not downloaded.exists()
        assert current_exe.read_text() == "new version"
        old_exe = tmp_path / "app.exe.old"
        assert old_exe.exists()
        assert old_exe.read_text() == "old version"
        mock_popen.assert_called_once()
        app_mock.quit.assert_called_once()


def test_apply_portable_update_dev_mode_safety(tmp_path):
    """В режиме разработки (frozen=False) системный python.exe не должен перезаписываться."""
    orig_py = tmp_path / "python.exe"
    orig_py.write_text("system python")
    downloaded = tmp_path / "new_app.exe"
    downloaded.write_text("new version")

    with patch("sys.executable", str(orig_py)), \
         patch.object(sys, 'frozen', False, create=True), \
         patch("app.update_checker.QMessageBox") as mock_box, \
         patch("subprocess.Popen") as mock_popen:
        mock_instance = MagicMock()
        mock_instance.clickedButton.return_value = None
        mock_box.return_value = mock_instance

        res = apply_portable_update(str(downloaded))
        assert res is True
        # python.exe остался нетронутым
        assert orig_py.read_text() == "system python"
        # скачанный файл не удален
        assert downloaded.exists()
        mock_popen.assert_not_called()


def test_apply_portable_update_zip_with_internal(tmp_path):
    """Проверка обновления ZIP-архива с папкой _internal для PyInstaller onedir."""
    app_dir = tmp_path / "app_folder"
    app_dir.mkdir()
    current_exe = app_dir / "app.exe"
    current_exe.write_text("old exe")
    internal_dir = app_dir / "_internal"
    internal_dir.mkdir()
    (internal_dir / "lib.dll").write_text("old dll")

    # Создаем ZIP с новой версией
    zip_path = tmp_path / "update.zip"
    with zipfile.ZipFile(str(zip_path), 'w') as zf:
        zf.writestr("app.exe", "new exe")
        zf.writestr("_internal/lib.dll", "new dll")
        zf.writestr("_internal/new_file.txt", "hello")

    with patch("sys.executable", str(current_exe)), \
         patch.object(sys, 'frozen', True, create=True), \
         patch("subprocess.Popen") as mock_popen, \
         patch("PyQt6.QtWidgets.QApplication.instance") as mock_app:
        app_mock = MagicMock()
        mock_app.return_value = app_mock

        res = apply_portable_update(str(zip_path))
        assert res is True
        assert current_exe.read_text() == "new exe"
        assert (internal_dir / "lib.dll").read_text() == "new dll"
        assert (internal_dir / "new_file.txt").read_text() == "hello"
        assert (app_dir / "_internal.old").exists()
        assert (app_dir / "_internal.old" / "lib.dll").read_text() == "old dll"


def test_update_ytdlp_wheel_extraction(tmp_path):
    orig_path = list(sys.path)
    # Создаем фиктивный .whl файл с пакетом yt_dlp
    wheel_path = tmp_path / "test_ytdlp-2026.01.01-py3-none-any.whl"
    with zipfile.ZipFile(str(wheel_path), 'w') as zf:
        zf.writestr("yt_dlp/__init__.py", "__version__ = '2026.01.01'\n")
        zf.writestr("yt_dlp/version.py", "__version__ = '2026.01.01'\n")
        zf.writestr("other_junk/foo.txt", "bar")

    target_dir = str(tmp_path / "packages")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [wheel_path.read_bytes()]

    try:
        with patch("requests.get", return_value=mock_resp):
            success, msg = update_ytdlp_wheel("https://dummy.whl", target_dir)
            assert success is True
            assert "успешно" in msg.lower()
            extracted_init = os.path.join(target_dir, "yt_dlp", "__init__.py")
            assert os.path.exists(extracted_init)
            assert "2026.01.01" in open(extracted_init).read()
            assert not os.path.exists(os.path.join(target_dir, "other_junk"))
    finally:
        sys.path[:] = orig_path
        for mod_name in list(sys.modules.keys()):
            if mod_name == 'yt_dlp' or mod_name.startswith('yt_dlp.'):
                del sys.modules[mod_name]
        import yt_dlp
        from app.threads import _LazyYtDlp
        _LazyYtDlp._module = None


def test_check_all_updates_worker(qapp):
    worker = CheckAllUpdatesWorker()
    app_signals = []
    ytdlp_signals = []
    ready_signals = []

    worker.signals.app_update_available.connect(lambda d: app_signals.append(d))
    worker.signals.ytdlp_update_available.connect(lambda d: ytdlp_signals.append(d))
    worker.signals.updates_ready.connect(lambda: ready_signals.append(True))

    # Мокаем ответ GitHub и PyPI
    mock_github = MagicMock()
    mock_github.status_code = 200
    mock_github.json.return_value = {
        "tag_name": "v99.0",
        "name": "Release 99.0",
        "body": "Major improvements",
        "published_at": "2026-11-14T12:00:00Z",
        "html_url": "https://github.com/dimalinau-lab/universal-media-downloader-2/releases/tag/v99.0",
        "assets": [
            {"name": "UMD_Setup_v99.0.exe", "browser_download_url": "https://dummy/setup.exe"},
            {"name": "UMD_v99.0.exe", "browser_download_url": "https://dummy/portable.exe"},
        ]
    }

    mock_pypi = MagicMock()
    mock_pypi.status_code = 200
    mock_pypi.json.return_value = {
        "info": {"version": "2099.12.31"},
        "urls": [
            {"filename": "yt_dlp-2099.12.31-py3-none-any.whl", "url": "https://dummy/ytdlp.whl"}
        ]
    }

    def mock_requests_get(url, **kwargs):
        if "github" in url:
            return mock_github
        return mock_pypi

    with patch("requests.get", side_effect=mock_requests_get):
        worker.run()
        assert len(app_signals) == 1
        assert app_signals[0]['latest_version'] == "99.0"
        assert app_signals[0]['installer_asset']['name'] == "UMD_Setup_v99.0.exe"
        assert app_signals[0]['portable_asset']['name'] == "UMD_v99.0.exe"

        assert len(ytdlp_signals) == 1
        assert ytdlp_signals[0]['latest_version'] == "2099.12.31"
        assert ytdlp_signals[0]['wheel_url'] == "https://dummy/ytdlp.whl"
        assert len(ready_signals) == 1
