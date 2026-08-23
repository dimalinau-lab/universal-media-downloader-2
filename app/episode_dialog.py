from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout
from qfluentwidgets import MessageBoxBase, SubtitleLabel, ComboBox


class EpisodeSelectionDialog(MessageBoxBase):
    def __init__(self, voiceovers, seasons, episodes, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel('Выберите серию для скачивания', self)

        # Выпадающие списки
        self.voiceover_combo = ComboBox(self)
        self.voiceover_combo.addItems(voiceovers)

        self.season_combo = ComboBox(self)
        self.season_combo.addItems(seasons)

        self.episode_combo = ComboBox(self)
        self.episode_combo.addItems(episodes)

        # Добавляем на слой
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.voiceover_combo)
        self.viewLayout.addWidget(self.season_combo)
        self.viewLayout.addWidget(self.episode_combo)

        self.widget.setMinimumWidth(350)