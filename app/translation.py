import os
import json
import logging
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class Translator(QObject):
    language_changed = pyqtSignal()

    def __init__(self, project_root=None, parent=None):
        super().__init__(parent)
        self.project_root = project_root or os.path.dirname(os.path.abspath(__file__))
        self.current_language = 'ru'
        self.translations = {}
        self.load_translations()

    def _read_json(self, path):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f'Ошибка чтения файла перевода: {path} - {e}')
        else:
            logger.warning(f'Не найден файл перевода: {path}')
        return {}

    def load_translations(self):
        candidates = [
            os.path.join(self.project_root, 'assets', 'locales', f'{self.current_language}.json'),
            os.path.join(self.project_root, 'assets', f'{self.current_language}.json'),
        ]
        data = {}
        for p in candidates:
            data = self._read_json(p)
            if data:
                break
        if not data:
            for fp in [
                os.path.join(self.project_root, 'assets', 'locales', 'en.json'),
                os.path.join(self.project_root, 'assets', 'en.json'),
            ]:
                data = self._read_json(fp)
                if data:
                    break
        self.translations = data or {}

    def translate(self, key: str, fallback: str = None) -> str:
        if not isinstance(key, str):
            return fallback or str(key)
        if key in self.translations:
            return self.translations[key]
        lk = key.lower()
        if lk in self.translations:
            return self.translations[lk]
        return fallback or key

    def set_language(self, language_code: str):
        if self.current_language != language_code:
            self.current_language = language_code
            self.load_translations()
            self.language_changed.emit()
        else:
            self.load_translations()
