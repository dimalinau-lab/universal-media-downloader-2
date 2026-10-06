from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt
import re
import logging

logger = logging.getLogger(__name__)


class EpisodeSelectionDialog(QDialog):
    def __init__(self, voiceovers, seasons, episodes, qualities, is_movie=False, voice_qualities=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Параметры загрузки")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setMinimumHeight(450 if not is_movie else 240)
        self.download_all = False

        self.voiceovers = voiceovers if isinstance(voiceovers, list) else []
        self.seasons = seasons if isinstance(seasons, list) else []
        self.episodes = episodes if isinstance(episodes, list) else []
        self.default_qualities = qualities if isinstance(qualities, list) else ["1080p", "720p", "480p", "360p"]
        self.voice_qualities = voice_qualities if isinstance(voice_qualities, dict) else {}
        self.is_movie = is_movie

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Выбор качества
        layout.addWidget(QLabel("Выберите качество:"))
        self.quality_combo = QComboBox()
        self._populate_qualities(self.default_qualities)
        layout.addWidget(self.quality_combo)

        # Выбор озвучки
        layout.addWidget(QLabel("Выберите озвучку:"))
        self.voiceover_combo = QComboBox()
        for v in self.voiceovers:
            name = v.get('name') if isinstance(v, dict) else str(v)
            self.voiceover_combo.addItem(name, userData=v)
        layout.addWidget(self.voiceover_combo)

        self.season_combo = QComboBox()
        for s in self.seasons:
            name = s.get('name') if isinstance(s, dict) else str(s)
            self.season_combo.addItem(name, userData=s)

        if not is_movie:
            layout.addWidget(QLabel("Выберите сезон:"))
            layout.addWidget(self.season_combo)

            # Панель пакетного выбора серий
            ep_header_layout = QHBoxLayout()
            self.ep_label = QLabel("Выберите серии для скачивания:")
            self.count_label = QLabel("Выбрано: 0")
            self.count_label.setStyleSheet("color: #0078D7; font-weight: bold;")
            ep_header_layout.addWidget(self.ep_label)
            ep_header_layout.addStretch()
            ep_header_layout.addWidget(self.count_label)
            layout.addLayout(ep_header_layout)

            # Быстрые кнопки выбора
            btn_toolbar = QHBoxLayout()
            btn_toolbar.setSpacing(6)

            self.btn_select_all = QPushButton("Выбрать все")
            self.btn_select_all.clicked.connect(self.select_all_episodes)
            self.btn_select_all.setFixedHeight(28)

            self.btn_deselect_all = QPushButton("Снять все")
            self.btn_deselect_all.clicked.connect(self.deselect_all_episodes)
            self.btn_deselect_all.setFixedHeight(28)

            self.btn_range = QPushButton("Диапазон...")
            self.btn_range.setToolTip("Указать диапазон (например, 1-12 или 1, 3, 5-8)")
            self.btn_range.clicked.connect(self.select_range_dialog)
            self.btn_range.setFixedHeight(28)

            btn_toolbar.addWidget(self.btn_select_all)
            btn_toolbar.addWidget(self.btn_deselect_all)
            btn_toolbar.addWidget(self.btn_range)
            layout.addLayout(btn_toolbar)

            # Список серий с чекбоксами
            self.episodes_list = QListWidget()
            self.episodes_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
            self.episodes_list.itemChanged.connect(self._on_item_changed)
            layout.addWidget(self.episodes_list, 1)

            self.season_combo.currentIndexChanged.connect(self._on_season_changed)
            self._on_season_changed()

        self.voiceover_combo.currentIndexChanged.connect(self._on_voiceover_changed)
        self._on_voiceover_changed()

        # Кнопки диалога
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.ok_btn = QPushButton("Скачать выбранные" if not is_movie else "Скачать фильм")
        self.ok_btn.setStyleSheet("background-color: #0078D7; color: white; font-weight: bold; padding: 6px 14px;")
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)
        self._update_count_label()

    def _populate_qualities(self, quals):
        current_text = self.quality_combo.currentText()
        self.quality_combo.clear()
        for q in quals:
            if isinstance(q, dict):
                label = q.get('label', str(q))
                val = q.get('key', label)
            else:
                label = str(q)
                val = label
            self.quality_combo.addItem(label, userData=val)

        idx = self.quality_combo.findText(current_text)
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        elif self.quality_combo.count() > 0:
            self.quality_combo.setCurrentIndex(0)

    def _on_voiceover_changed(self):
        v = self.get_selected_voiceover()
        v_id = str(v.get('id', ''))
        quals = self.voice_qualities.get(v_id)
        if quals:
            self._populate_qualities(quals)
        elif self.quality_combo.count() == 0:
            self._populate_qualities(self.default_qualities)

    def _on_season_changed(self):
        self.episodes_list.blockSignals(True)
        self.episodes_list.clear()
        selected_season = self.season_combo.currentData()
        season_id = str(selected_season.get('id', '1')) if isinstance(selected_season, dict) else '1'

        matching_episodes = []
        for ep in self.episodes:
            if isinstance(ep, dict):
                ep_season_id = str(ep.get('season_id', '1'))
                if ep_season_id == season_id:
                    matching_episodes.append(ep)
            else:
                matching_episodes.append({'name': str(ep), 'id': '1', 'season_id': season_id})

        if not matching_episodes and self.episodes:
            matching_episodes = self.episodes

        for ep in matching_episodes:
            name = ep.get('name', 'Серия') if isinstance(ep, dict) else str(ep)
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, ep)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # По умолчанию отмечаем все серии сезона
            item.setCheckState(Qt.CheckState.Checked)
            self.episodes_list.addItem(item)

        self.episodes_list.blockSignals(False)
        self._update_count_label()

    def _on_item_changed(self, item):
        self._update_count_label()

    def _update_count_label(self):
        if self.is_movie:
            return
        total = self.episodes_list.count()
        checked = sum(1 for i in range(total) if self.episodes_list.item(i).checkState() == Qt.CheckState.Checked)
        self.count_label.setText(f"Выбрано: {checked} из {total}")
        if hasattr(self, 'ok_btn'):
            if checked > 0:
                self.ok_btn.setText(f"Скачать выбранные ({checked})")
                self.ok_btn.setEnabled(True)
            else:
                self.ok_btn.setText("Скачать выбранные (0)")
                self.ok_btn.setEnabled(False)

    def select_all_episodes(self):
        self.episodes_list.blockSignals(True)
        for i in range(self.episodes_list.count()):
            self.episodes_list.item(i).setCheckState(Qt.CheckState.Checked)
        self.episodes_list.blockSignals(False)
        self._update_count_label()

    def deselect_all_episodes(self):
        self.episodes_list.blockSignals(True)
        for i in range(self.episodes_list.count()):
            self.episodes_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.episodes_list.blockSignals(False)
        self._update_count_label()

    def select_range_dialog(self):
        total = self.episodes_list.count()
        text, ok = QInputDialog.getText(
            self,
            "Выбор диапазона серий",
            f"Введите номера или диапазон серий (всего {total} серий):\nНапример: 1-12 или 1, 3, 5-8"
        )
        if not ok or not text.strip():
            return

        selected_indices = set()
        parts = text.split(',')
        for p in parts:
            p = p.strip()
            if '-' in p:
                sub = p.split('-')
                if len(sub) == 2 and sub[0].strip().isdigit() and sub[1].strip().isdigit():
                    start = int(sub[0].strip())
                    end = int(sub[1].strip())
                    for idx in range(min(start, end), max(start, end) + 1):
                        if 1 <= idx <= total:
                            selected_indices.add(idx - 1)
            elif p.isdigit():
                idx = int(p)
                if 1 <= idx <= total:
                    selected_indices.add(idx - 1)

        if not selected_indices:
            QMessageBox.information(self, "Диапазон", "Не найдено серий, подходящих под указанный диапазон.")
            return

        self.episodes_list.blockSignals(True)
        for i in range(total):
            state = Qt.CheckState.Checked if i in selected_indices else Qt.CheckState.Unchecked
            self.episodes_list.item(i).setCheckState(state)
        self.episodes_list.blockSignals(False)
        self._update_count_label()

    def get_selected_voiceover(self):
        data = self.voiceover_combo.currentData()
        if isinstance(data, dict):
            return data
        idx = self.voiceover_combo.currentIndex()
        return self.voiceovers[idx] if 0 <= idx < len(self.voiceovers) else {'name': 'Default', 'id': ''}

    def get_selected_season(self):
        data = self.season_combo.currentData()
        if isinstance(data, dict):
            return data
        idx = self.season_combo.currentIndex()
        return self.seasons[idx] if 0 <= idx < len(self.seasons) else {'name': '1 Сезон', 'id': '1'}

    def get_selected_targets(self):
        if self.is_movie:
            return [{'name': 'Полный фильм', 'id': '1', 'season_id': '1'}]

        targets = []
        for i in range(self.episodes_list.count()):
            item = self.episodes_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                ep_data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(ep_data, dict):
                    targets.append(ep_data)

        # Если ничего не отмечено, берем текущий выделенный элемент или первый
        if not targets and self.episodes_list.count() > 0:
            current_item = self.episodes_list.currentItem() or self.episodes_list.item(0)
            ep_data = current_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(ep_data, dict):
                targets.append(ep_data)

        return targets

    def get_selected_quality(self):
        data = self.quality_combo.currentData()
        if data is not None and str(data).strip():
            return data
        txt = self.quality_combo.currentText().strip()
        return txt if txt else "1080p"

    def accept(self):
        v = self.get_selected_voiceover()
        s = self.get_selected_season()
        q = self.get_selected_quality()
        targets = self.get_selected_targets()

        v_name = v.get('name', 'По умолчанию') if isinstance(v, dict) else str(v)
        v_id = v.get('id', '') if isinstance(v, dict) else ''
        s_name = s.get('name', '1 Сезон') if isinstance(s, dict) else str(s)
        s_id = s.get('id', '1') if isinstance(s, dict) else '1'

        logger.info(f"[EpisodeDialog] Нажата кнопка подтверждения выбора.")
        logger.info(f"[EpisodeDialog] Озвучка: '{v_name}' (ID: '{v_id}') | Сезон: '{s_name}' (ID: '{s_id}') | Качество: '{q}'")
        logger.info(f"[EpisodeDialog] Выбрано серий для загрузки: {len(targets)}")

        if not targets:
            logger.warning("[EpisodeDialog] ВНИМАНИЕ: Список выбранных серий пуст!")
            QMessageBox.warning(self, "Выбор серий", "Не выбрано ни одной серии для скачивания.")
            return

        for idx, t in enumerate(targets[:5]):
            t_name = t.get('name', f"Серия {idx+1}") if isinstance(t, dict) else str(t)
            t_id = t.get('id', '') if isinstance(t, dict) else ''
            logger.info(f"   -> [{idx+1}/{len(targets)}] {t_name} (ID: {t_id})")
        if len(targets) > 5:
            logger.info(f"   ... и ещё {len(targets) - 5} серий")

        super().accept()

    def reject(self):
        logger.info("[EpisodeDialog] Диалог выбора серий отменен пользователем.")
        super().reject()