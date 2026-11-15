import logging
import os
import shutil
import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFrame
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap, QPainter, QPainterPath, QColor
from qfluentwidgets import (
    SingleDirectionScrollArea, PushButton, PrimaryPushButton,
    FluentIcon, BodyLabel, TitleLabel, SubtitleLabel, CaptionLabel, IconWidget
)
import yt_dlp
from .__version__ import __version__
from .translation import Translator

logger = logging.getLogger(__name__)


class AboutTab(QWidget):
    def __init__(self, translator: Translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.parent_window = parent
        self.initUI()
        self.translator.language_changed.connect(self.update_translations)

    def initUI(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Orientation.Vertical, parent=self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.enableTransparentBackground()
        self.scroll_area.setStyleSheet("SingleDirectionScrollArea, QScrollArea { border: none; background: transparent; }")

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self.scroll_content)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 1. Верхняя Bento карточка-визитка (Hero Banner)
        self.create_hero_card(layout)

        # 2. Bento Grid: 2 колонки (Компоненты / Возможности)
        bento_layout = QHBoxLayout()
        bento_layout.setSpacing(16)
        bento_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.create_components_card(bento_layout)
        self.create_features_card(bento_layout)
        layout.addLayout(bento_layout)

        layout.addStretch(1)

        self.scroll_area.setWidget(self.scroll_content)
        outer_layout.addWidget(self.scroll_area)

        self.update_translations()
        self.update_theme_icons()

    def _round_pixmap(self, pm: QPixmap, size=80, radius=16):
        scaled = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, size, size, radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        return out

    def create_hero_card(self, layout):
        card = QFrame()
        card.setObjectName('AboutCard')
        c_layout = QHBoxLayout(card)
        c_layout.setContentsMargins(20, 18, 20, 18)
        c_layout.setSpacing(20)

        # Логотип приложения (высокое разрешение 80x80 с плавной рамкой)
        self.lbl_logo = QLabel()
        self.lbl_logo.setFixedSize(80, 80)
        logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'icon.png'))
        if os.path.exists(logo_path):
            pm = QPixmap(logo_path)
            self.lbl_logo.setPixmap(self._round_pixmap(pm, 80, 16))
        c_layout.addWidget(self.lbl_logo, 0, Qt.AlignmentFlag.AlignTop)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        # Заголовок + бейдж версии
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_title = TitleLabel()
        self.lbl_title.setObjectName('AboutTitleLabel')
        title_row.addWidget(self.lbl_title)

        self.lbl_version_badge = QLabel(f"v{__version__}")
        self.lbl_version_badge.setObjectName('AboutVersionBadge')
        self.lbl_version_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_version_badge.setFixedHeight(22)
        title_row.addWidget(self.lbl_version_badge)
        title_row.addStretch(1)
        info_layout.addLayout(title_row)

        # Описание
        self.lbl_desc = BodyLabel()
        self.lbl_desc.setObjectName('AboutDescriptionLabel')
        self.lbl_desc.setWordWrap(True)
        info_layout.addWidget(self.lbl_desc)

        # Авторы
        self.lbl_author = CaptionLabel()
        self.lbl_author.setObjectName('AboutAuthorLabel')
        self.lbl_author.setWordWrap(True)
        info_layout.addWidget(self.lbl_author)

        info_layout.addSpacing(6)

        # Кнопки действий
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.btn_github = PrimaryPushButton(FluentIcon.SHARE, "")
        self.btn_github.setFixedHeight(34)
        self.btn_github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://github.com/dimalinau-lab')))
        btn_row.addWidget(self.btn_github)

        self.btn_check_update = PushButton(FluentIcon.SYNC, "")
        self.btn_check_update.setFixedHeight(34)
        self.btn_check_update.clicked.connect(self.on_check_update_clicked)
        btn_row.addWidget(self.btn_check_update)

        btn_row.addStretch(1)
        info_layout.addLayout(btn_row)

        c_layout.addLayout(info_layout, 1)
        layout.addWidget(card)

    def create_components_card(self, parent_layout):
        card = QFrame()
        card.setObjectName('AboutCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Заголовок
        h_row = QHBoxLayout()
        h_row.setSpacing(8)
        self.icon_comp = IconWidget()
        self.icon_comp.setFixedSize(18, 18)
        self.lbl_comp_head = SubtitleLabel()
        h_row.addWidget(self.icon_comp)
        h_row.addWidget(self.lbl_comp_head)
        h_row.addStretch(1)
        layout.addLayout(h_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: rgba(128, 128, 128, 0.2); max-height: 1px;")
        layout.addWidget(line)

        # Строки компонентов
        ytdlp_ver = getattr(yt_dlp.version, '__version__', '2026.11.04')
        self.row_ytdlp_lbl, self.row_ytdlp_val = self._add_stat_row(layout, "about_ytdlp_engine", f"v{ytdlp_ver}", status_ok=True)

        ffmpeg_ok = bool(hasattr(self.parent_window, 'ffmpeg_path') and self.parent_window.ffmpeg_path and os.path.exists(self.parent_window.ffmpeg_path))
        ffmpeg_text = "Встроен в сборку (v7.1)" if ffmpeg_ok else "Не найден"
        self.row_ffmpeg_lbl, self.row_ffmpeg_val = self._add_stat_row(layout, "about_ffmpeg_engine", ffmpeg_text, status_ok=ffmpeg_ok)

        deno_ok = bool(shutil.which('deno') or os.path.exists(os.path.expanduser('~/.deno/bin/deno.exe')))
        deno_text = "Активен (n-sig обход)" if deno_ok else "Не обнаружен"
        self.row_deno_lbl, self.row_deno_val = self._add_stat_row(layout, "about_deno_engine", deno_text, status_ok=deno_ok)

        py_ver = sys.version.split()[0]
        self.row_gui_lbl, self.row_gui_val = self._add_stat_row(layout, "about_gui_platform", f"Python {py_ver} • PyQt6 Fluent", status_ok=True)

        layout.addStretch(1)
        parent_layout.addWidget(card, 1)

    def create_features_card(self, parent_layout):
        card = QFrame()
        card.setObjectName('AboutCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Заголовок
        h_row = QHBoxLayout()
        h_row.setSpacing(8)
        self.icon_feat = IconWidget()
        self.icon_feat.setFixedSize(18, 18)
        self.lbl_feat_head = SubtitleLabel()
        h_row.addWidget(self.icon_feat)
        h_row.addWidget(self.lbl_feat_head)
        h_row.addStretch(1)
        layout.addLayout(h_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: rgba(128, 128, 128, 0.2); max-height: 1px;")
        layout.addWidget(line)

        features = [
            (FluentIcon.MOVIE, "about_feat_cinemas", "about_feat_cinemas_desc"),
            (FluentIcon.SPEED_HIGH, "about_feat_speed", "about_feat_speed_desc"),
            (FluentIcon.MUSIC, "about_feat_tools", "about_feat_tools_desc"),
            (FluentIcon.SEND, "about_feat_bot", "about_feat_bot_desc"),
        ]

        self.feature_widgets = []
        self.feature_icons = []
        for icon_enum, title_key, desc_key in features:
            f_box = QHBoxLayout()
            f_box.setSpacing(12)
            f_box.setAlignment(Qt.AlignmentFlag.AlignTop)

            badge = QFrame()
            badge.setObjectName('FeatureIconBadge')
            badge.setFixedSize(32, 32)
            b_layout = QVBoxLayout(badge)
            b_layout.setContentsMargins(0, 0, 0, 0)
            b_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            icon_widget = IconWidget(icon_enum.colored(QColor('#005fb8'), QColor('#60cdff')))
            icon_widget.setFixedSize(16, 16)
            b_layout.addWidget(icon_widget)
            self.feature_icons.append((icon_widget, icon_enum))

            t_box = QVBoxLayout()
            t_box.setSpacing(2)
            lbl_t = BodyLabel()
            f = lbl_t.font()
            f.setBold(True)
            lbl_t.setFont(f)

            lbl_d = CaptionLabel()
            lbl_d.setWordWrap(True)
            lbl_d.setStyleSheet("color: #888888;")

            t_box.addWidget(lbl_t)
            t_box.addWidget(lbl_d)

            f_box.addWidget(badge)
            f_box.addLayout(t_box, 1)
            layout.addLayout(f_box)

            self.feature_widgets.append((lbl_t, title_key, lbl_d, desc_key))

        layout.addStretch(1)
        parent_layout.addWidget(card, 1)

    def _add_stat_row(self, layout, label_key, value_text, status_ok=True):
        row = QHBoxLayout()
        row.setSpacing(10)

        lbl = BodyLabel()
        f = lbl.font()
        f.setBold(True)
        lbl.setFont(f)
        row.addWidget(lbl)

        row.addStretch(1)

        val = BodyLabel(value_text)
        val_color = '#10b981' if status_ok else '#f59e0b'
        val.setStyleSheet(f"color: {val_color}; font-weight: 600; font-family: monospace, sans-serif;")
        row.addWidget(val)

        layout.addLayout(row)
        return lbl, val

    def update_translations(self):
        self.lbl_title.setText(self.translator.translate('app_title', 'Универсальный загрузчик медиа'))
        self.lbl_desc.setText(self.translator.translate('about_desc_full', 'Быстрая и надежная загрузка видео, аудио, серий и плейлистов с различных платформ и онлайн-кинотеатров.'))
        self.lbl_author.setText(self.translator.translate('about_author_detail', 'Magerko (оригинальный концепт) • MrPablo & dimalinau-lab (развитие и доработки)'))

        self.btn_github.setText(self.translator.translate('about_github', 'GitHub Проект'))
        self.btn_check_update.setText(self.translator.translate('about_check_updates', 'Проверить обновления'))

        if hasattr(self, 'lbl_comp_head'):
            self.lbl_comp_head.setText(self.translator.translate('about_components_title', 'Системные компоненты и ядро'))
        if hasattr(self, 'lbl_feat_head'):
            self.lbl_feat_head.setText(self.translator.translate('about_features_title', 'Ключевые возможности'))

        if hasattr(self, 'row_ytdlp_lbl'):
            self.row_ytdlp_lbl.setText(self.translator.translate('about_ytdlp_engine', 'Ядро yt-dlp:'))
        if hasattr(self, 'row_ffmpeg_lbl'):
            self.row_ffmpeg_lbl.setText(self.translator.translate('about_ffmpeg_engine', 'Мультимедиа FFmpeg:'))
        if hasattr(self, 'row_deno_lbl'):
            self.row_deno_lbl.setText(self.translator.translate('about_deno_engine', 'Среда Deno:'))
        if hasattr(self, 'row_gui_lbl'):
            self.row_gui_lbl.setText(self.translator.translate('about_gui_platform', 'Платформа GUI:'))

        if hasattr(self, 'feature_widgets'):
            for lbl_t, title_key, lbl_d, desc_key in self.feature_widgets:
                lbl_t.setText(self.translator.translate(title_key))
                lbl_d.setText(self.translator.translate(desc_key))

    def update_theme_icons(self):
        if hasattr(self, 'btn_github'):
            self.btn_github.setIcon(FluentIcon.SHARE)
        if hasattr(self, 'btn_check_update'):
            self.btn_check_update.setIcon(FluentIcon.SYNC)
        if hasattr(self, 'icon_comp'):
            self.icon_comp.setIcon(FluentIcon.DEVELOPER_TOOLS.colored(QColor('#005fb8'), QColor('#60cdff')))
        if hasattr(self, 'icon_feat'):
            self.icon_feat.setIcon(FluentIcon.APPLICATION.colored(QColor('#005fb8'), QColor('#60cdff')))
        if hasattr(self, 'feature_icons'):
            for icon_widget, icon_enum in self.feature_icons:
                icon_widget.setIcon(icon_enum.colored(QColor('#005fb8'), QColor('#60cdff')))

    def on_check_update_clicked(self):
        if hasattr(self.parent_window, 'update_checker') and self.parent_window.update_checker:
            self.parent_window.update_checker.check_for_updates(silent=False)
