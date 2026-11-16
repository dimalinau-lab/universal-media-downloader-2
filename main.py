

import sys
import os

# Скрываем окно консоли в Windows при обычном запуске (если не передан флаг --console / --debug)
if sys.platform == 'win32' and '--console' not in sys.argv and '--debug' not in sys.argv:
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE
    except Exception:
        pass

import logging
import traceback
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon, QGuiApplication
from PyQt6.QtCore import QSettings, Qt
from app.translation import Translator
from app.theme_manager import ThemeManager


from logging.handlers import RotatingFileHandler
from app.path_manager import (
    get_base_dir,
    get_bundle_dir,
    get_logs_dir,
    get_data_dir,
    get_updates_dir,
)

# Подключение директории динамических обновлений пакетов (yt-dlp и др.) в приоритет sys.path
updates_dir = get_updates_dir()
if os.path.isdir(updates_dir) and updates_dir not in sys.path:
    sys.path.insert(0, updates_dir)

# Регистрация явного AppUserModelID в Windows для корректной группировки на панели задач
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('UMD')
    except Exception:
        pass

# Очистка резервных копий и устаревших файлов после обновления (atomic swap / portable / inno)
if getattr(sys, 'frozen', False):
    try:
        current_exe = sys.executable
        base_dir = os.path.dirname(os.path.abspath(current_exe))
        current_name = os.path.basename(current_exe).lower()

        # 1. Удаление .old от исполняемого файла
        old_exe = current_exe + ".old"
        if os.path.exists(old_exe):
            try:
                os.remove(old_exe)
            except Exception:
                pass

        # 2. Удаление резервной директории зависимостей _internal.old
        old_internal = os.path.join(base_dir, "_internal.old")
        if os.path.exists(old_internal):
            import shutil
            shutil.rmtree(old_internal, ignore_errors=True)

        # 3. Удаление устаревших версионированных исполняемых файлов (Windows3.*.exe)
        for fname in os.listdir(base_dir):
            fl = fname.lower()
            if fl.endswith('.old') and fl != os.path.basename(old_exe).lower():
                try:
                    fp = os.path.join(base_dir, fname)
                    if os.path.isfile(fp):
                        os.remove(fp)
                    elif os.path.isdir(fp):
                        import shutil
                        shutil.rmtree(fp, ignore_errors=True)
                except Exception:
                    pass
            elif fl.startswith('windows3.') and fl.endswith('.exe') and fl != current_name:
                try:
                    os.remove(os.path.join(base_dir, fname))
                except Exception:
                    pass
    except Exception:
        pass


# Обеспечиваем корректную работу UTF-8 в консоли Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

# Подавляем внутренний шум Qt Multimedia и FFmpeg в консоли (Could not update timestamps for skipped samples)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg.warning=false;qt.multimedia.*=false")
try:
    import ctypes
    from PyQt6.QtCore import QLibraryInfo
    qt_bin = QLibraryInfo.path(QLibraryInfo.LibraryPath.BinariesPath)
    for dll in ('avutil-59.dll', 'avutil-58.dll'):
        dll_path = os.path.join(qt_bin, dll)
        if os.path.exists(dll_path):
            ctypes.CDLL(dll_path).av_log_set_level(16)  # AV_LOG_ERROR
            break
except Exception:
    pass



def setup_logging():
    log_dir = get_logs_dir()
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'app.log')

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    if not root_logger.handlers:
        # Файловый логгер с ротацией (полный DEBUG)
        file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

        # Консольный логгер в реальном времени (INFO+)
        if sys.stdout:
            console_handler = logging.StreamHandler(sys.stdout)
            console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(logging.INFO)
            root_logger.addHandler(console_handler)

    # Приглушаем излишне шумные сторонние библиотеки в консоли
    logging.getLogger('selenium').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def excepthook(exc_type, exc_value, exc_tb):
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.critical(f"Unhandled exception:\n{tb_text}")
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def get_app_settings():
    data_dir = get_data_dir()
    ini_path = os.path.join(data_dir, 'settings.ini')
    portable_marker = os.path.join(data_dir, 'portable.dat')

    is_portable = os.path.exists(portable_marker) or os.path.exists(ini_path)
    if not is_portable:
        reg_settings = QSettings('Magerko', 'UniversalMediaDownloader')
        if reg_settings.value('portable_mode', False, type=bool):
            is_portable = True

    if is_portable:
        try:
            os.makedirs(data_dir, exist_ok=True)
            s = QSettings(ini_path, QSettings.Format.IniFormat)
            s.setValue('portable_mode', True)
            return s
        except Exception:
            pass
    return QSettings('Magerko', 'UniversalMediaDownloader')


def main():
    setup_logging()
    sys.excepthook = excepthook
    logger = logging.getLogger(__name__)

    try:
        # Включаем корректное масштабирование для экранов ноутбуков (125%, 150%)
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        base_dir = get_base_dir()
        bundle_dir = get_bundle_dir()
        app = QApplication(sys.argv)

        settings = get_app_settings()

        translator = Translator(project_root=bundle_dir)
        saved_language = settings.value('language', 'ru')
        translator.set_language(saved_language)

        icon_path = os.path.join(bundle_dir, 'assets', 'icon.png')
        if not os.path.exists(icon_path):
            icon_path = os.path.join(base_dir, 'assets', 'icon.png')
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
        else:
            logger.warning(f'Иконка не найдена по пути: {icon_path}')

        from app.main_window import MainWindow
        window = MainWindow(translator, settings)

        theme_manager = ThemeManager(window.settings, window)
        theme_manager.apply_theme()

        window.show()

        sys.exit(app.exec())

    except Exception:
        logger.exception('Произошла фатальная ошибка при запуске приложения.')
        traceback.print_exc()


if __name__ == '__main__':
    main()
    