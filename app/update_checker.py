import os
import sys
import shutil
import logging
import subprocess
import tempfile
import zipfile
import time
from packaging import version
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QTextEdit, QMessageBox, QApplication
)
from qfluentwidgets import (
    PrimaryPushButton, PushButton, FluentIcon, CardWidget
)
from .path_manager import get_base_dir, get_updates_dir, is_dir_writable
from .__version__ import __version__ as APP_VERSION

logger = logging.getLogger(__name__)

GITHUB_REPO_OWNER = "dimalinau-lab"
GITHUB_REPO_NAME = "universal-media-downloader-2"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
PYPI_YTDLP_URL = "https://pypi.org/pypi/yt-dlp/json"


def is_installer_mode() -> bool:
    """
    Определяет тип развертывания приложения:
    - True: Установленная версия (Inno Setup: есть unins000.exe или папка Program Files только для чтения)
    - False: Портативная версия (Single EXE) или запуск из исходного кода
    """
    base_dir = get_base_dir()
    if os.path.exists(os.path.join(base_dir, "unins000.exe")):
        return True
    if getattr(sys, 'frozen', False) and not is_dir_writable(base_dir):
        return True
    return False


def apply_installer_update(installer_path: str) -> bool:
    """Запускает Inno Setup инсталлятор в тихом режиме с перезапуском приложения."""
    try:
        base_dir = get_base_dir()
        cmd = [
            installer_path,
            "/SILENT",
            "/CLOSEAPPLICATIONS",
            "/RESTARTAPPLICATIONS",
            f"/DIR={base_dir}",
        ]
        subprocess.Popen(cmd)
        app = QApplication.instance()
        if app:
            app.quit()
        return True
    except Exception as e:
        logger.error(f"Ошибка запуска инсталлятора: {e}")
        return False


def apply_portable_update(new_file_path: str) -> bool:
    """
    Выполняет обновление для портативной версии:
    1. Если запущено из исходного кода Python (dev-режим) — защищает системный python.exe,
       сохраняет файл в папку загрузок/темп и предлагает открыть её.
    2. Если запущено в скомпилированном виде (frozen) — производит In-place Atomic Swap:
       - Если ZIP: извлекает исполняемый .exe
       - Переименовывает running exe -> exe.old
       - Перемещает скачанный файл -> running exe
       - Запускает новый процесс и завершает текущий
    """
    if not getattr(sys, 'frozen', False):
        logger.info(f"Dev-режим: обновление скачано в {new_file_path}")
        msg = QMessageBox()
        msg.setWindowTitle("Обновление скачано")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(
            f"Файл обновления успешно загружен:\n{new_file_path}\n\n"
            "Поскольку сейчас программа запущена из исходного кода Python (режим разработки), "
            "автоматическая замена системного python.exe отключена для защиты рабочего окружения.\n\n"
            "В скомпилированной версии программа обновится автоматически."
        )
        btn_open = msg.addButton("Открыть папку", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()
        if msg.clickedButton() == btn_open:
            folder = os.path.dirname(os.path.abspath(new_file_path))
            os.startfile(folder)
        return True

    try:
        current_exe = sys.executable
        base_dir = os.path.dirname(os.path.abspath(current_exe))

        if new_file_path.lower().endswith('.zip'):
            staging_dir = os.path.join(tempfile.gettempdir(), f"umd_update_{int(time.time())}")
            with zipfile.ZipFile(new_file_path, 'r') as zf:
                zf.extractall(staging_dir)
            extracted_exes = []
            for root, _, files in os.walk(staging_dir):
                for f in files:
                    if f.lower().endswith('.exe') and 'unins' not in f.lower():
                        extracted_exes.append(os.path.join(root, f))
            if extracted_exes:
                new_exe = extracted_exes[0]
                new_dir = os.path.dirname(new_exe)
                # Если в архиве присутствует каталог зависимостей _internal (режим PyInstaller onedir)
                internal_src = os.path.join(new_dir, '_internal')
                if os.path.isdir(internal_src) and is_dir_writable(base_dir):
                    internal_dst = os.path.join(base_dir, '_internal')
                    internal_old = os.path.join(base_dir, '_internal.old')
                    if os.path.exists(internal_old):
                        shutil.rmtree(internal_old, ignore_errors=True)
                    if os.path.exists(internal_dst):
                        try:
                            os.rename(internal_dst, internal_old)
                        except Exception as e:
                            logger.warning(f"Не удалось переименовать _internal в _internal.old: {e}")
                    try:
                        shutil.copytree(internal_src, internal_dst, dirs_exist_ok=True)
                    except Exception as e:
                        logger.warning(f"Ошибка копирования _internal: {e}")
                new_file_path = new_exe
        old_exe = current_exe + ".old"
        if os.path.exists(old_exe):
            try:
                os.remove(old_exe)
            except Exception:
                pass

        os.rename(current_exe, old_exe)
        shutil.move(new_file_path, current_exe)
        subprocess.Popen([current_exe] + sys.argv[1:])
        app = QApplication.instance()
        if app:
            app.quit()
        return True
    except Exception as e:
        logger.error(f"Ошибка atomic swap для портативной версии: {e}")
        if os.path.exists(old_exe) and not os.path.exists(current_exe):
            try:
                os.rename(old_exe, current_exe)
            except Exception:
                pass
        return False


def update_ytdlp_wheel(wheel_url: str, target_dir: str) -> tuple[bool, str]:
    """
    Скачивает yt_dlp из GitHub Releases (tar.gz) или PyPI (.whl)
    и распаковывает модуль yt_dlp в изолированную директорию обновлений без pip.
    """
    import requests
    import tarfile
    try:
        os.makedirs(target_dir, exist_ok=True)
        fallback_tar_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.tar.gz"
        if not wheel_url:
            wheel_url = fallback_tar_url

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        try:
            resp = requests.get(wheel_url, stream=True, timeout=40, headers=headers)
            resp.raise_for_status()
        except Exception:
            if wheel_url != fallback_tar_url:
                wheel_url = fallback_tar_url
                resp = requests.get(wheel_url, stream=True, timeout=40, headers=headers)
                resp.raise_for_status()
            else:
                raise

        is_tar = wheel_url.endswith('.tar.gz') or 'tar.gz' in wheel_url

        with tempfile.NamedTemporaryFile(suffix=".tar.gz" if is_tar else ".whl", delete=False) as tf:
            tmp_archive = tf.name
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    tf.write(chunk)

        if is_tar:
            with tarfile.open(tmp_archive, 'r:gz') as tf_obj:
                for member in tf_obj.getmembers():
                    if 'yt_dlp/' in member.name or 'yt_dlp\\' in member.name:
                        idx = member.name.find('yt_dlp')
                        rel_path = member.name[idx:]
                        dest_file = os.path.join(target_dir, rel_path)
                        if member.isdir():
                            os.makedirs(dest_file, exist_ok=True)
                        elif member.isfile():
                            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                            f_in = tf_obj.extractfile(member)
                            if f_in:
                                with open(dest_file, 'wb') as f_out:
                                    f_out.write(f_in.read())
        else:
            with zipfile.ZipFile(tmp_archive, 'r') as zf:
                for member in zf.namelist():
                    if member.startswith('yt_dlp/') or member.startswith('yt_dlp\\'):
                        zf.extract(member, target_dir)

        try:
            os.remove(tmp_archive)
        except Exception:
            pass

        if target_dir not in sys.path:
            sys.path.insert(0, target_dir)

        for mod_name in list(sys.modules.keys()):
            if mod_name == 'yt_dlp' or mod_name.startswith('yt_dlp.'):
                del sys.modules[mod_name]

        return True, "Модуль yt-dlp успешно обновлен и готов к работе!"
    except Exception as e:
        logger.error(f"Ошибка распаковки yt-dlp: {e}")
        return False, str(e)


# ============================================================================
# Сигналы и воркеры
# ============================================================================

class CheckSignals(QObject):
    app_update_available = pyqtSignal(dict)
    ytdlp_update_available = pyqtSignal(dict)
    updates_ready = pyqtSignal()
    no_updates = pyqtSignal()
    check_failed = pyqtSignal(str)


class DownloadSignals(QObject):
    progress = pyqtSignal(int, int, float)  # downloaded, total, speed_kbps
    completed = pyqtSignal(bool, str)       # success, file_path_or_msg


class CheckAllUpdatesWorker(QRunnable):
    """Фоновый воркер одновременной проверки обновлений UMD и yt-dlp."""
    def __init__(self):
        super().__init__()
        self.signals = CheckSignals()

    def run(self):
        app_update = None
        ytdlp_update = None
        has_error = False
        error_msg = ""

        # 1. Проверка обновлений приложения на GitHub Releases
        try:
            import requests
            headers = {
                'Accept': 'application/vnd.github+json',
                'User-Agent': f'UniversalMediaDownloader/{APP_VERSION}'
            }
            resp = requests.get(GITHUB_API_URL, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                tag = data.get('tag_name', '').lstrip('v')
                if tag and version.parse(tag) > version.parse(APP_VERSION):
                    assets = data.get('assets', [])
                    installer_asset = None
                    portable_asset = None

                    for asset in assets:
                        name = asset.get('name', '').lower()
                        if 'setup' in name or 'installer' in name:
                            installer_asset = asset
                        elif (name.endswith('.exe') or name.endswith('.zip')) and 'unins' not in name:
                            portable_asset = asset

                    app_update = {
                        'latest_version': tag,
                        'current_version': APP_VERSION,
                        'release_name': data.get('name') or f"Релиз v{tag}",
                        'changelog': data.get('body') or "Описание изменений отсутствует.",
                        'published_at': data.get('published_at', '')[:10],
                        'html_url': data.get('html_url', ''),
                        'installer_asset': installer_asset,
                        'portable_asset': portable_asset,
                    }
        except Exception as e:
            logger.warning(f"Ошибка проверки GitHub релиза: {e}")
            has_error = True
            error_msg = f"GitHub: {e}"

        # 2. Проверка ядра yt-dlp на PyPI
        try:
            import yt_dlp
            current_ytdlp = getattr(getattr(yt_dlp, 'version', None), '__version__', 'unknown')
            import requests
            resp = requests.get(PYPI_YTDLP_URL, timeout=10, headers={'User-Agent': f'UMD/{APP_VERSION}'})
            if resp.status_code == 200:
                pypi_data = resp.json()
                latest_ytdlp = pypi_data.get('info', {}).get('version', '')
                if latest_ytdlp and current_ytdlp != 'unknown' and version.parse(latest_ytdlp) > version.parse(current_ytdlp):
                    wheel_url = None
                    for url_info in pypi_data.get('urls', []):
                        fn = url_info.get('filename', '')
                        if fn.endswith('py3-none-any.whl') or url_info.get('packagetype') == 'bdist_wheel':
                            wheel_url = url_info.get('url')
                            break

                    ytdlp_update = {
                        'current_version': current_ytdlp,
                        'latest_version': latest_ytdlp,
                        'wheel_url': wheel_url or "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.tar.gz"
                    }
        except Exception as e:
            logger.warning(f"Ошибка проверки yt-dlp на PyPI: {e}")
            if not has_error:
                error_msg = f"yt-dlp: {e}"
            has_error = True

        # Отправка результатов
        if app_update:
            self.signals.app_update_available.emit(app_update)
        if ytdlp_update:
            self.signals.ytdlp_update_available.emit(ytdlp_update)
        if app_update or ytdlp_update:
            self.signals.updates_ready.emit()
        else:
            if has_error:
                self.signals.check_failed.emit(error_msg)
            else:
                self.signals.no_updates.emit()


class AppDownloadWorker(QRunnable):
    """Потоковый загрузчик бинарника приложения с расчетом скорости."""
    def __init__(self, download_url: str, target_filename: str):
        super().__init__()
        self.download_url = download_url
        self.target_filename = target_filename
        self.signals = DownloadSignals()

    def run(self):
        import requests
        try:
            dest_dir = tempfile.gettempdir()
            dest_path = os.path.join(dest_dir, self.target_filename)

            resp = requests.get(self.download_url, stream=True, timeout=60, headers={'User-Agent': 'UMD-DownloadWorker'})
            resp.raise_for_status()

            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_emit = 0

            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    if now - last_emit > 0.15:
                        elapsed = max(now - start_time, 0.001)
                        speed_kbps = (downloaded / 1024.0) / elapsed
                        self.signals.progress.emit(downloaded, total_size, speed_kbps)
                        last_emit = now

            self.signals.progress.emit(total_size, total_size, 0)
            self.signals.completed.emit(True, dest_path)
        except Exception as e:
            logger.error(f"Ошибка загрузки обновления: {e}")
            self.signals.completed.emit(False, str(e))


class YtDlpUpdateWorker(QRunnable):
    """Фоновое обновление pure-python ядра yt-dlp."""
    def __init__(self, wheel_url: str):
        super().__init__()
        self.wheel_url = wheel_url
        self.signals = DownloadSignals()

    def run(self):
        target_dir = get_updates_dir()
        success, msg = update_ytdlp_wheel(self.wheel_url, target_dir)
        self.signals.completed.emit(success, msg)


# ============================================================================
# Современный диалог обновления (Fluent UI)
# ============================================================================

class ModernUpdateDialog(QDialog):
    """Диалог уведомления и управления автообновлением приложения и ядра yt-dlp."""
    def __init__(self, parent, translator, app_update: dict | None, ytdlp_update: dict | None, thread_pool):
        super().__init__(parent)
        self.translator = translator
        self.app_update = app_update
        self.ytdlp_update = ytdlp_update
        self.thread_pool = thread_pool
        self.is_installer = is_installer_mode()

        is_dark = True
        if parent and hasattr(parent, 'settings') and parent.settings:
            is_dark = parent.settings.value('theme', 'dark') == 'dark'

        self.bg_color = "#202020" if is_dark else "#f9f9f9"
        self.card_bg = "#2b2b2b" if is_dark else "#ffffff"
        self.card_border = "#3d3d3d" if is_dark else "#e5e5e5"
        self.text_primary = "#ffffff" if is_dark else "#1a1a1a"
        self.text_secondary = "#a0a0a0" if is_dark else "#666666"
        self.changelog_bg = "#242424" if is_dark else "#f3f3f3"
        self.changelog_border = "#383838" if is_dark else "#dcdcdc"
        self.changelog_text = "#e0e0e0" if is_dark else "#222222"

        self.setWindowTitle("Обновление Universal Media Downloader")
        self.setMinimumWidth(620)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {self.bg_color}; }}
        """)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        header = QLabel("Доступны обновления", self)
        header.setStyleSheet(f"color: {self.text_primary}; font-size: 20px; font-weight: 600; font-family: 'Segoe UI', sans-serif;")
        layout.addWidget(header)

        # Карточка обновления приложения
        if self.app_update:
            app_card = CardWidget(self)
            app_card.setStyleSheet(f"""
                CardWidget {{
                    background-color: {self.card_bg};
                    border: 1px solid {self.card_border};
                    border-radius: 8px;
                }}
            """)
            card_layout = QVBoxLayout(app_card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setSpacing(10)

            title_row = QHBoxLayout()
            title_lbl = QLabel(f"UMD v{self.app_update['latest_version']}", app_card)
            title_lbl.setStyleSheet(f"color: {self.text_primary}; font-weight: bold; font-size: 16px; font-family: 'Segoe UI', sans-serif;")
            cur_lbl = QLabel(f"(Текущая: v{self.app_update['current_version']})", app_card)
            cur_lbl.setStyleSheet(f"color: {self.text_secondary}; font-size: 13px; font-family: 'Segoe UI', sans-serif;")
            title_row.addWidget(title_lbl)
            title_row.addWidget(cur_lbl)
            title_row.addStretch()
            card_layout.addLayout(title_row)

            # Описание изменений (Changelog)
            changelog_lbl = QLabel("Что нового в этом выпуске:", app_card)
            changelog_lbl.setStyleSheet(f"color: {self.text_primary}; font-size: 13px; font-weight: 500;")
            card_layout.addWidget(changelog_lbl)

            changelog_edit = QTextEdit(app_card)
            changelog_edit.setReadOnly(True)
            changelog_edit.setMaximumHeight(130)
            changelog_edit.setPlainText(self.app_update['changelog'])
            changelog_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {self.changelog_bg};
                    color: {self.changelog_text};
                    border: 1px solid {self.changelog_border};
                    border-radius: 6px;
                    padding: 8px;
                    font-size: 13px;
                    font-family: 'Segoe UI', sans-serif;
                }}
            """)
            card_layout.addWidget(changelog_edit)

            # Кнопка обновления приложения
            btn_row = QHBoxLayout()
            mode_text = "Обновить приложение"
            self.btn_update_app = PrimaryPushButton(mode_text, app_card)
            self.btn_update_app.setIcon(FluentIcon.DOWNLOAD)
            self.btn_update_app.clicked.connect(self._start_app_download)
            btn_row.addWidget(self.btn_update_app)
            btn_row.addStretch()
            card_layout.addLayout(btn_row)

            layout.addWidget(app_card)

        # Карточка обновления ядра yt-dlp
        if self.ytdlp_update and self.ytdlp_update.get('wheel_url'):
            ytdlp_card = CardWidget(self)
            ytdlp_card.setStyleSheet(f"""
                CardWidget {{
                    background-color: {self.card_bg};
                    border: 1px solid {self.card_border};
                    border-radius: 8px;
                }}
            """)
            y_layout = QVBoxLayout(ytdlp_card)
            y_layout.setContentsMargins(16, 16, 16, 16)
            y_layout.setSpacing(8)

            y_title_row = QHBoxLayout()
            y_title = QLabel("Движок парсера YouTube (yt-dlp)", ytdlp_card)
            y_title.setStyleSheet(f"color: {self.text_primary}; font-weight: bold; font-size: 16px; font-family: 'Segoe UI', sans-serif;")
            y_badge = QLabel(f"v{self.ytdlp_update['current_version']} → v{self.ytdlp_update['latest_version']}", ytdlp_card)
            y_badge.setStyleSheet("color: #0078d4; font-size: 13px; font-weight: 600; font-family: 'Segoe UI', sans-serif;")
            y_title_row.addWidget(y_title)
            y_title_row.addWidget(y_badge)
            y_title_row.addStretch()
            y_layout.addLayout(y_title_row)

            y_desc = QLabel(
                "Автономное обновление библиотеки парсинга без перезаписи основного приложения. "
                "Рекомендуется при сбоях или изменении алгоритмов YouTube.",
                ytdlp_card
            )
            y_desc.setStyleSheet(f"color: {self.text_secondary}; font-size: 13px; font-family: 'Segoe UI', sans-serif;")
            y_desc.setWordWrap(True)
            y_layout.addWidget(y_desc)

            self.btn_update_ytdlp = PushButton("Обновить только yt-dlp", ytdlp_card)
            self.btn_update_ytdlp.setIcon(FluentIcon.SYNC)
            self.btn_update_ytdlp.clicked.connect(self._start_ytdlp_update)
            y_layout.addWidget(self.btn_update_ytdlp, alignment=Qt.AlignmentFlag.AlignLeft)

            layout.addWidget(ytdlp_card)

        # Прогресс-бар загрузки
        self.progress_container = CardWidget(self)
        self.progress_container.setStyleSheet(f"""
            CardWidget {{
                background-color: {self.card_bg};
                border: 1px solid {self.card_border};
                border-radius: 8px;
            }}
        """)
        p_layout = QVBoxLayout(self.progress_container)
        p_layout.setContentsMargins(16, 12, 16, 12)
        self.progress_label = QLabel("Скачивание обновления...", self.progress_container)
        self.progress_label.setStyleSheet(f"color: {self.text_primary}; font-size: 13px; font-weight: 500;")
        self.progress_bar = QProgressBar(self.progress_container)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                background-color: #2b2b2b;
                text-align: center;
                color: #ffffff;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 3px;
            }
        """)
        p_layout.addWidget(self.progress_label)
        p_layout.addWidget(self.progress_bar)
        self.progress_container.setVisible(False)
        layout.addWidget(self.progress_container)

        # Нижняя панель действий
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()

        self.btn_remind_later = PushButton("Напомнить позже", self)
        self.btn_remind_later.clicked.connect(self.reject)
        bottom_row.addWidget(self.btn_remind_later)

        layout.addLayout(bottom_row)

    def _start_app_download(self):
        """Запуск скачивания обновления программы."""
        if not self.app_update:
            return

        asset = self.app_update['installer_asset'] if self.is_installer else self.app_update['portable_asset']
        if not asset:
            asset = self.app_update['installer_asset'] or self.app_update['portable_asset']

        if not asset:
            QMessageBox.warning(self, "Ошибка", "В релизе на GitHub не найден подходящий исполняемый файл.")
            return

        download_url = asset['browser_download_url']
        filename = asset['name']

        self.btn_update_app.setEnabled(False)
        if hasattr(self, 'btn_update_ytdlp'):
            self.btn_update_ytdlp.setEnabled(False)
        self.progress_container.setVisible(True)

        worker = AppDownloadWorker(download_url, filename)
        worker.signals.progress.connect(self._on_download_progress)
        worker.signals.completed.connect(self._on_app_download_completed)
        self.thread_pool.start(worker)

    def _on_download_progress(self, downloaded: int, total: int, speed_kbps: float):
        if total > 0:
            percent = int((downloaded / total) * 100)
            self.progress_bar.setValue(percent)
            mb_down = downloaded / (1024 * 1024)
            mb_tot = total / (1024 * 1024)
            self.progress_label.setText(
                f"Загрузка: {mb_down:.1f} МБ из {mb_tot:.1f} МБ ({percent}%) • {speed_kbps:.0f} КБ/с"
            )
        else:
            mb_down = downloaded / (1024 * 1024)
            self.progress_label.setText(f"Загрузка: {mb_down:.1f} МБ • {speed_kbps:.0f} КБ/с")

    def _on_app_download_completed(self, success: bool, result_path_or_msg: str):
        self.progress_container.setVisible(False)
        self.btn_update_app.setEnabled(True)

        if not success:
            QMessageBox.critical(self, "Ошибка загрузки", f"Не удалось загрузить обновление:\n{result_path_or_msg}")
            return

        downloaded_file = result_path_or_msg
        file_lower = downloaded_file.lower()
        is_setup = 'setup' in file_lower or 'installer' in file_lower

        if self.is_installer or is_setup:
            # Запуск инсталлятора
            res = QMessageBox.question(
                self, "Готово к установке",
                "Инсталлятор успешно загружен. Закрыть программу и запустить обновление сейчас?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res == QMessageBox.StandardButton.Yes:
                self.accept()
                apply_installer_update(downloaded_file)
        else:
            # Запуск atomic swap для portable
            res = QMessageBox.question(
                self, "Готово к обновлению",
                "Новая версия загружена. Перезапустить приложение для применения изменений?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res == QMessageBox.StandardButton.Yes:
                self.accept()
                apply_portable_update(downloaded_file)

    def _start_ytdlp_update(self):
        """Запуск автономного обновления ядра yt-dlp."""
        if not self.ytdlp_update or not self.ytdlp_update.get('wheel_url'):
            return

        self.btn_update_ytdlp.setEnabled(False)
        self.progress_container.setVisible(True)
        self.progress_label.setText("Скачивание и распаковка пакета yt-dlp...")
        self.progress_bar.setRange(0, 0)  # Indeterminate

        worker = YtDlpUpdateWorker(self.ytdlp_update['wheel_url'])
        worker.signals.completed.connect(self._on_ytdlp_completed)
        self.thread_pool.start(worker)

    def _on_ytdlp_completed(self, success: bool, message: str):
        self.progress_container.setVisible(False)
        self.btn_update_ytdlp.setEnabled(True)

        if success:
            QMessageBox.information(
                self, "Успех",
                f"Ядро yt-dlp успешно обновлено до версии {self.ytdlp_update['latest_version']}!\n\n"
                "Новая версия готова к использованию."
            )
            self.accept()
        else:
            QMessageBox.critical(self, "Ошибка обновления yt-dlp", f"Не удалось обновить yt-dlp:\n{message}")


# ============================================================================
# Главный контроллер UpdateChecker
# ============================================================================

class UpdateChecker(QObject):
    """
    Унифицированный менеджер автообновлений:
    - Проверка релизов программы на GitHub Releases
    - Автономное обновление ядра yt-dlp через PyPI wheel
    - Поддержка Inno Setup установщика и Portable In-place Atomic Swap
    - Проверка наличия Deno
    """
    def __init__(self, parent, translator, settings, thread_pool):
        super().__init__(parent)
        self.parent = parent
        self.translator = translator
        self.settings = settings
        self.thread_pool = thread_pool
        self._silent = False

        self._pending_app_update = None
        self._pending_ytdlp_update = None

    def check_for_updates(self, silent: bool = False):
        """Запускает фоновую проверку обновлений приложения и yt-dlp."""
        if getattr(self, '_is_checking', False):
            logger.info("Проверка обновлений уже выполняется, повторный вызов пропущен.")
            return
        self._is_checking = True
        self._silent = silent
        self._pending_app_update = None
        self._pending_ytdlp_update = None

        worker = CheckAllUpdatesWorker()
        worker.signals.app_update_available.connect(self._on_app_update_available)
        worker.signals.ytdlp_update_available.connect(self._on_ytdlp_update_available)
        worker.signals.updates_ready.connect(self._show_update_dialog_if_ready)
        worker.signals.no_updates.connect(self._on_no_updates)
        worker.signals.check_failed.connect(self._on_check_failed)
        self.thread_pool.start(worker)

    def _on_app_update_available(self, update_info: dict):
        self._pending_app_update = update_info

    def _on_ytdlp_update_available(self, update_info: dict):
        self._pending_ytdlp_update = update_info

    def _show_update_dialog_if_ready(self):
        self._is_checking = False
        # Если тихий режим и версия была пропущена пользователем
        if self._silent and self._pending_app_update:
            skipped = self.settings.value('skipped_app_version', '')
            if skipped == self._pending_app_update['latest_version']:
                logger.info(f"Пропуск уведомления о версии {skipped} (пользователь нажал 'Пропустить')")
                return

        dlg = ModernUpdateDialog(
            parent=self.parent,
            translator=self.translator,
            app_update=self._pending_app_update,
            ytdlp_update=self._pending_ytdlp_update,
            thread_pool=self.thread_pool
        )
        dlg.exec()

    def _on_no_updates(self):
        self._is_checking = False
        if not self._silent:
            QMessageBox.information(
                self.parent,
                "Обновлений нет",
                f"У вас установлена самая актуальная версия {APP_VERSION}.\n"
                "Компоненты программы и движок yt-dlp не требуют обновления."
            )

    def _on_check_failed(self, error: str):
        self._is_checking = False
        if not self._silent:
            logger.warning(f"Ошибка проверки обновлений: {error}")
            QMessageBox.warning(
                self.parent,
                "Проверка обновлений",
                f"Не удалось подключиться к серверу обновлений:\n{error}\n\n"
                "Проверьте сетевое подключение."
            )

    # ------------------------------------------------------------------------
    # Проверка Deno (сохранена совместимость с main_window.py)
    # ------------------------------------------------------------------------
    def check_deno_installed(self):
        """Проверяет, установлен ли Deno в системе."""
        try:
            deno_path = shutil.which('deno')
            if not deno_path:
                user_deno = os.path.expanduser('~/.deno/bin/deno.exe' if os.name == 'nt' else '~/.deno/bin/deno')
                if os.path.exists(user_deno):
                    deno_path = user_deno
            if deno_path:
                flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                result = subprocess.run(
                    [deno_path, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=flags,
                    encoding='utf-8',
                    errors='replace'
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith('deno'):
                            return line.split()[1]
            return None
        except Exception as e:
            logger.debug(f"Deno check failed: {e}")
            return None

    def show_deno_warning(self):
        """Выводит предупреждение при отсутствии Deno."""
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
            return False

        deno_version = self.check_deno_installed()
        if deno_version is None:
            msg = QMessageBox(self.parent)
            msg.setWindowTitle(self.translator.translate('deno_required', 'Требуется Deno'))
            msg.setText(
                self.translator.translate(
                    'deno_not_found_message',
                    'Среда выполнения Deno JavaScript не найдена в системе.\n\n'
                    'Загрузка с некоторых ресурсов YouTube может работать нестабильно.\n\n'
                    'Установить Deno: https://deno.com\n'
                    'Windows (PowerShell):\nirm https://deno.land/install.ps1 | iex'
                )
            )
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.exec()
            return False
        return True
