import sys
import logging
import traceback
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon, QGuiApplication
from PyQt6.QtCore import QSettings, Qt
from app.main_window import MainWindow
from app.translation import Translator
from app.theme_manager import ThemeManager


from logging.handlers import RotatingFileHandler


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


def setup_logging():
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
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


def get_app_settings(project_root):
    data_dir = os.path.join(project_root, 'data')
    ini_path = os.path.join(data_dir, 'settings.ini')
    portable_marker = os.path.join(data_dir, 'portable.dat')

    is_portable = os.path.exists(portable_marker) or os.path.exists(ini_path)
    if not is_portable:
        reg_settings = QSettings('Magerko', 'UniversalMediaDownloader')
        if reg_settings.value('portable_mode', False, type=bool):
            is_portable = True

    if is_portable:
        os.makedirs(data_dir, exist_ok=True)
        s = QSettings(ini_path, QSettings.Format.IniFormat)
        s.setValue('portable_mode', True)
        return s
    return QSettings('Magerko', 'UniversalMediaDownloader')


def main():
    setup_logging()
    sys.excepthook = excepthook
    logger = logging.getLogger(__name__)

    try:
        # Включаем корректное масштабирование для экранов ноутбуков (125%, 150%)
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        project_root = os.path.dirname(os.path.abspath(__file__))
        app = QApplication(sys.argv)

        settings = get_app_settings(project_root)

        translator = Translator(project_root=project_root)
        saved_language = settings.value('language', 'ru')
        translator.set_language(saved_language)

        icon_path = os.path.join(project_root, 'assets', 'icon.png')
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
        else:
            logger.warning(f'Иконка не найдена по пути: {icon_path}')

        window = MainWindow(translator, settings)

        theme_manager = ThemeManager(window.settings)
        theme_manager.apply_theme()

        window.show()

        sys.exit(app.exec())

    except Exception as e:
        logger.exception('Произошла фатальная ошибка при запуске приложения.')
        traceback.print_exc()


if __name__ == '__main__':
    main()
