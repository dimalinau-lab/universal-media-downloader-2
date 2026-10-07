import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """
    Базовый интерфейс для модульных экстракторов медиа-сервисов и онлайн-кинотеатров.
    """
    name: str = "Base"
    platform_id: str = "other"

    @classmethod
    @abstractmethod
    def can_handle(cls, url: str) -> bool:
        """
        Возвращает True, если данный экстрактор может обработать переданный URL.
        """
        return False

    def fetch_metadata(self, url: str) -> dict:
        """
        Собирает метаданные страницы: название, постер, список озвучек, сезонов и серий.
        Возвращает dict со структурой для диалога выбора серий.
        """
        raise NotImplementedError

    def resolve_stream(self, episode_data: dict, quality: str = "1080p") -> tuple[str, str]:
        """
        Извлекает прямую рабочую ссылку (.m3u8 или .mp4) для выбранной серии.
        Возвращает (direct_url, quality_badge).
        """
        raise NotImplementedError
