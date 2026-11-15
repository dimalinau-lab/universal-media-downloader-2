import os
import sys
import logging

logger = logging.getLogger(__name__)


def is_admin() -> bool:
    """Проверяет, запущен ли текущий процесс с правами администратора на Windows."""
    if os.name != 'nt':
        return True
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate_privileges() -> bool:
    """
    Если процесс запущен без прав администратора на Windows,
    перезапускает приложение с запросом повышения прав UAC (runas).
    """
    if os.name != 'nt':
        return True
    if is_admin():
        return True

    # Запрашиваем повышение прав через ShellExecuteW 'runas'
    try:
        import ctypes
        if getattr(sys, 'frozen', False):
            executable = sys.executable
            params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        else:
            executable = sys.executable
            params = " ".join([f'"{arg}"' for arg in sys.argv])

        show_cmd = 0 if not getattr(sys, 'frozen', False) else 1
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, show_cmd)
        if ret > 32:
            # Успешно запущен повышенный процесс — завершаем текущий непривилегированный
            sys.exit(0)
    except Exception as e:
        logger.warning(f"Не удалось запросить повышение прав UAC: {e}")
    return False


def get_base_dir() -> str:
    """Возвращает базовую директорию приложения (папку исполняемого файла или корня проекта)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def get_bundle_dir() -> str:
    """Возвращает директорию с ресурсами приложения (для PyInstaller _MEIPASS или корень проекта)."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.join(os.path.dirname(sys.executable), '_internal'))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def is_dir_writable(path: str) -> bool:
    """Проверяет, доступна ли директория для создания и записи файлов."""
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, f'.perm_test_{os.getpid()}')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('ok')
        if os.path.exists(test_file):
            try:
                os.remove(test_file)
            except Exception:
                pass
        return True
    except (PermissionError, OSError):
        return False


def get_writable_dir(subfolder: str = "") -> str:
    """
    Возвращает гарантированно доступный для записи путь.
    1. Сначала пробует путь в папке программы (base_dir/subfolder).
    2. Если доступ запрещен (например, C:\\Program Files\\... без прав админа),
       автоматически перенаправляет в %LOCALAPPDATA%\\Universal Media Downloader\\subfolder.
    """
    base_dir = get_base_dir()
    target_dir = os.path.join(base_dir, subfolder) if subfolder else base_dir
    if is_dir_writable(target_dir):
        return target_dir

    local_app_data = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    fallback_base = os.path.join(local_app_data, 'Universal Media Downloader')
    fallback_dir = os.path.join(fallback_base, subfolder) if subfolder else fallback_base
    try:
        os.makedirs(fallback_dir, exist_ok=True)
    except Exception:
        pass
    return fallback_dir


def get_logs_dir() -> str:
    """Возвращает директорию для логов приложения."""
    return get_writable_dir('logs')


def get_data_dir() -> str:
    """Возвращает директорию для хранения данных (настроек, истории и т.д.)."""
    return get_writable_dir('data')


def get_browser_profile_dir() -> str:
    """Возвращает директорию для профиля браузера (Selenium/Cookies)."""
    return get_writable_dir('browser_profile')


def get_updates_dir() -> str:
    """Возвращает директорию для изолированных внешних обновлений модулей (yt-dlp и др.)."""
    return get_writable_dir(os.path.join('updates', 'packages'))


def get_aria2c_path() -> str:
    """
    Проверяет наличие aria2c в комплекте приложения (assets/ffmpeg/bin или assets/bin)
    или в системном PATH. Возвращает путь или пустую строку, если не найден.
    """
    import shutil
    base_dir = get_base_dir()
    bundle_dir = get_bundle_dir()
    for root in (bundle_dir, base_dir):
        candidate1 = os.path.join(root, 'assets', 'ffmpeg', 'bin', 'aria2c.exe')
        if os.path.isfile(candidate1):
            return candidate1
        candidate2 = os.path.join(root, 'assets', 'bin', 'aria2c.exe')
        if os.path.isfile(candidate2):
            return candidate2

    system_path = shutil.which('aria2c')
    return system_path or ""


