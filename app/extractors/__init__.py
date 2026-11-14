from .animego import AnimeGoExtractor
from .pinterest import PinterestExtractor

EXTRACTORS = [
    AnimeGoExtractor,
    PinterestExtractor,
]


def find_extractor_for_url(url: str):
    """
    Возвращает экземпляр подходящего экстрактора для URL или None.
    """
    for ext_cls in EXTRACTORS:
        if ext_cls.can_handle(url):
            return ext_cls()
    return None
