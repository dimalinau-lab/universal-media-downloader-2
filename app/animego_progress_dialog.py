import os
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRunnable
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QWidget
)
from PyQt6.QtGui import QPixmap
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel, StrongBodyLabel,
    ProgressBar, PushButton, FluentIcon, IconWidget
)


class AnimeGoScanDialog(QDialog):
    """
    Модальное окно прогресса анализа страницы AnimeGO в общем Fluent-стиле.
    Отображает текущий этап анализа, шкалу в процентах и кнопку Отмена.
    """
    cancelled = pyqtSignal()

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.is_cancelled = False
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Анализ AnimeGO")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.resize(500, 360)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #202020;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 1. Верхний блок: Иконка + Заголовок
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        icon_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'logos', 'animego.png')
        if os.path.exists(logo_path):
            pm = QPixmap(logo_path)
            if not pm.isNull():
                icon_label.setPixmap(pm.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if not icon_label.pixmap():
            self.icon_widget = IconWidget(FluentIcon.VIDEO)
            self.icon_widget.setFixedSize(36, 36)
            header_layout.addWidget(self.icon_widget)
        else:
            header_layout.addWidget(icon_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = SubtitleLabel("Анализ AnimeGO")
        self.title_label.setStyleSheet("font-size: 17px; font-weight: bold; color: #ffffff;")

        display_url = self.url if len(self.url) <= 50 else self.url[:32] + "..." + self.url[-15:]
        self.url_label = CaptionLabel(display_url)
        self.url_label.setStyleSheet("color: #888888;")
        self.url_label.setToolTip(self.url)

        title_box.addWidget(self.title_label)
        title_box.addWidget(self.url_label)
        header_layout.addLayout(title_box, 1)

        layout.addLayout(header_layout)

        # 2. Карточка шагов анализа
        self.steps_card = QFrame()
        self.steps_card.setObjectName("StepsCard")
        self.steps_card.setStyleSheet("""
            QFrame#StepsCard {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 12px;
            }
        """)
        steps_layout = QVBoxLayout(self.steps_card)
        steps_layout.setSpacing(8)

        self.step_1 = QLabel("• 1. Подключение к сайту и загрузка страницы (15%)")
        self.step_2 = QLabel("• 2. Получение списка плееров и озвучек (60%)")
        self.step_3 = QLabel("• 3. Получение списка доступных серий (85%)")

        for lbl in (self.step_1, self.step_2, self.step_3):
            lbl.setStyleSheet("color: #a0a0a0; font-size: 13px;")
            steps_layout.addWidget(lbl)

        layout.addWidget(self.steps_card)

        # 3. Прогресс-бар и текстовый статус
        prog_layout = QVBoxLayout()
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(6)

        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(10)

        self.status_label = BodyLabel("Подготовка к анализу AnimeGO...")
        self.status_label.setStyleSheet("color: #007acc; font-weight: 500; font-size: 13px;")

        prog_layout.addWidget(self.progress_bar)
        prog_layout.addWidget(self.status_label)
        layout.addWidget(self.progress_container_widget(prog_layout))

        # 4. Блок ошибок (скрыт по умолчанию)
        self.error_card = QFrame()
        self.error_card.setStyleSheet("""
            QFrame {
                background-color: rgba(244, 67, 54, 0.12);
                border: 1px solid rgba(244, 67, 54, 0.45);
                border-radius: 8px;
                padding: 10px;
            }
        """)
        err_box = QVBoxLayout(self.error_card)
        err_box.setSpacing(4)
        self.error_title = StrongBodyLabel("Ошибка при анализе")
        self.error_title.setStyleSheet("color: #ff5252; font-size: 13px; font-weight: bold;")
        self.error_text = BodyLabel("")
        self.error_text.setStyleSheet("color: #ffffff; font-size: 12px;")
        self.error_text.setWordWrap(True)
        err_box.addWidget(self.error_title)
        err_box.addWidget(self.error_text)
        self.error_card.hide()
        layout.addWidget(self.error_card)

        layout.addStretch()

        # 5. Кнопка Отмена
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = PushButton("Отмена")
        self.btn_cancel.setFixedWidth(110)
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def progress_container_widget(self, inner_layout):
        w = QWidget()
        w.setLayout(inner_layout)
        return w

    def update_progress(self, percent: int, status_text: str):
        if self.is_cancelled:
            return
        self.progress_bar.setValue(percent)
        self.status_label.setText(f"{status_text} ({percent}%)")

        # Подсветка выполненных этапов
        active_style = "color: #29b6f6; font-weight: bold; font-size: 13px;"
        done_style = "color: #4caf50; font-size: 13px;"
        pending_style = "color: #a0a0a0; font-size: 13px;"

        if percent < 35:
            self.step_1.setStyleSheet(active_style)
            self.step_2.setStyleSheet(pending_style)
            self.step_3.setStyleSheet(pending_style)
        elif percent < 75:
            self.step_1.setStyleSheet(done_style)
            self.step_2.setStyleSheet(active_style)
            self.step_3.setStyleSheet(pending_style)
        elif percent < 100:
            self.step_1.setStyleSheet(done_style)
            self.step_2.setStyleSheet(done_style)
            self.step_3.setStyleSheet(active_style)
        else:
            self.step_1.setStyleSheet(done_style)
            self.step_2.setStyleSheet(done_style)
            self.step_3.setStyleSheet(done_style)

    def show_error(self, err_msg: str):
        self.progress_bar.hide()
        self.status_label.hide()
        self.error_text.setText(err_msg)
        self.error_card.show()
        self.btn_cancel.setText("Закрыть")

    def on_cancel_clicked(self):
        self.is_cancelled = True
        self.cancelled.emit()
        self.reject()


class ResolveSignals(QObject):
    progress = pyqtSignal(int, int, str)  # current, total, episode_name
    episode_resolved = pyqtSignal(dict)   # info dict: {'direct_url', 'q_badge', 'ep'}
    finished = pyqtSignal(int)            # total added
    error = pyqtSignal(str)


class AnimeGoEpisodesResolveWorker(QRunnable):
    """Фоновый воркер опроса прямых потоков выбранных серий AnimeGO/Kodik."""
    def __init__(self, selected_targets, extractor, meta, selected_v, selected_q):
        super().__init__()
        self.selected_targets = selected_targets
        self.extractor = extractor
        self.meta = meta
        self.selected_v = selected_v
        self.selected_q = selected_q
        self.signals = ResolveSignals()
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        import logging
        logger = logging.getLogger(__name__)
        total = len(self.selected_targets)
        added_count = 0
        for i, ep in enumerate(self.selected_targets, 1):
            if self.is_cancelled:
                break
            ep_name = ep.get('name', f"Серия {i}")
            self.signals.progress.emit(i, total, ep_name)

            ep_meta = dict(self.meta)
            ep_meta.update(ep)
            ep_meta['selected_voiceover'] = self.selected_v
            try:
                direct_url, q_badge = self.extractor.resolve_stream(ep_meta, quality=self.selected_q)
            except Exception as e:
                logger.error(f"[{self.extractor.name}] Ошибка получения потока: {e}")
                direct_url = None

            if direct_url:
                self.signals.episode_resolved.emit({
                    'direct_url': direct_url,
                    'q_badge': q_badge,
                    'ep': ep,
                })
                added_count += 1

        self.signals.finished.emit(added_count)


class AnimeGoEpisodesResolveDialog(QDialog):
    """
    Модальное окно прогресса сбора прямых ссылок на выбранные серии AnimeGO.
    Отображает текущую обрабатываемую серию, шкалу прогресса и кнопку отмены.
    """
    cancelled = pyqtSignal()

    def __init__(self, anime_title: str, total_episodes: int, voiceover: str = "", quality: str = "", parent=None):
        super().__init__(parent)
        self.anime_title = anime_title
        self.total_episodes = max(total_episodes, 1)
        self.voiceover = voiceover
        self.quality = quality
        self.is_cancelled = False
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Сбор ссылок серий")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.resize(480, 260)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #202020;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # Header with Logo
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        icon_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'logos', 'animego.png')
        if os.path.exists(logo_path):
            pm = QPixmap(logo_path)
            if not pm.isNull():
                icon_label.setPixmap(pm.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if not icon_label.pixmap():
            icon_widget = IconWidget(FluentIcon.VIDEO)
            icon_widget.setFixedSize(36, 36)
            header_layout.addWidget(icon_widget)
        else:
            header_layout.addWidget(icon_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_lbl = SubtitleLabel("Сбор ссылок для скачивания серий")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")

        details = self.anime_title
        if self.voiceover:
            details += f" • {self.voiceover}"
        if self.quality:
            details += f" • {self.quality}"
        sub_lbl = CaptionLabel(details)
        sub_lbl.setStyleSheet("color: #888888; font-size: 12px;")

        title_box.addWidget(title_lbl)
        title_box.addWidget(sub_lbl)
        header_layout.addLayout(title_box, 1)
        layout.addLayout(header_layout)

        # Progress bar & status card
        prog_card = QFrame()
        prog_card.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 12px;
            }
        """)
        prog_layout = QVBoxLayout(prog_card)
        prog_layout.setSpacing(8)

        self.status_label = BodyLabel(f"Подготовка к сбору ссылок (0 из {self.total_episodes})...")
        self.status_label.setStyleSheet("color: #29b6f6; font-size: 13px; font-weight: 500;")
        prog_layout.addWidget(self.status_label)

        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setRange(0, self.total_episodes)
        self.progress_bar.setValue(0)
        prog_layout.addWidget(self.progress_bar)

        self.count_label = CaptionLabel(f"Обработано: 0 из {self.total_episodes} серий")
        self.count_label.setStyleSheet("color: #a0a0a0; font-size: 12px;")
        prog_layout.addWidget(self.count_label)

        layout.addWidget(prog_card)
        layout.addStretch()

        # Cancel button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = PushButton("Отмена")
        self.btn_cancel.setFixedWidth(100)
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def update_progress(self, current: int, total: int, episode_name: str):
        if self.is_cancelled:
            return
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Получение видеопотока: {episode_name}")
        self.count_label.setText(f"Обработано: {current} из {total} серий")

    def on_cancel_clicked(self):
        self.is_cancelled = True
        self.cancelled.emit()
        self.reject()
