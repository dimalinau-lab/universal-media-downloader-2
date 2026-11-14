import os
from PyQt6.QtCore import Qt, pyqtSignal
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
