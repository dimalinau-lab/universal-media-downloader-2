import os
import json
import subprocess
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QGridLayout, QLabel, QApplication
)
from PyQt6.QtCore import Qt, QRunnable, QObject, pyqtSignal, QThreadPool
from qfluentwidgets import (
    PrimaryPushButton, PushButton, FluentIcon,
    InfoBar, InfoBarPosition, SingleDirectionScrollArea
)


class FFprobeSignals(QObject):
    data_ready = pyqtSignal(dict)
    error = pyqtSignal(str)


class FFprobeWorker(QRunnable):
    def __init__(self, filepath: str, ffprobe_path: str):
        super().__init__()
        self.filepath = filepath
        self.ffprobe_path = ffprobe_path
        self.signals = FFprobeSignals()

    def run(self):
        try:
            cmd = [
                self.ffprobe_path,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                self.filepath
            ]
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            res = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags, encoding='utf-8', errors='replace')
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                self.signals.data_ready.emit(data)
            else:
                self.signals.error.emit(res.stderr or "FFprobe вернул пустой результат")
        except Exception as e:
            self.signals.error.emit(str(e))


class MediaInfoDialog(QDialog):
    """
    Диалог детального анализа медиафайла через FFprobe.
    Показывает видео/аудио кодеки, разрешение, битрейт, частоту кадров и аудиодорожки.
    """
    def __init__(self, filepath: str, ffprobe_path: str, translator, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.ffprobe_path = ffprobe_path
        self.translator = translator
        self.raw_data = None

        self.setWindowTitle(self.translator.translate('mediainfo_title', "Свойства медиафайла (FFprobe)"))
        self.setMinimumSize(600, 560)
        self.initUI()
        self._load_probe_info()

    def initUI(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(24, 20, 24, 20)
        self.layout.setSpacing(12)

        # Шапка файла
        filename = os.path.basename(self.filepath)
        header_title = QLabel(filename)
        header_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff; padding: 2px 0;")
        header_title.setWordWrap(True)
        self.layout.addWidget(header_title)

        self.lbl_path = QLabel(self.filepath)
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setStyleSheet("color: #888888; font-size: 12px; padding: 0;")
        self.lbl_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.layout.addWidget(self.lbl_path)

        # Статус / индикатор загрузки
        self.lbl_status = QLabel(self.translator.translate('analyzing_file', "Анализ структуры файла..."))
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("color: #0078D7; font-size: 14px; padding: 30px 0;")
        self.layout.addWidget(self.lbl_status)

        # Скролл-область для свойств
        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Orientation.Vertical)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll_area.hide()

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(6, 6, 6, 6)
        self.grid_layout.setHorizontalSpacing(24)
        self.grid_layout.setVerticalSpacing(4)
        self.scroll_area.setWidget(self.grid_container)
        self.layout.addWidget(self.scroll_area, 1)

        # Нижняя панель
        btn_box = QHBoxLayout()
        self.btn_copy = PushButton(FluentIcon.COPY, self.translator.translate('copy_report', "Копировать отчёт"))
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._copy_to_clipboard)

        self.btn_close = PrimaryPushButton(self.translator.translate('close', "Закрыть"))
        self.btn_close.clicked.connect(self.accept)

        btn_box.addWidget(self.btn_copy)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_close)
        self.layout.addLayout(btn_box)

    def _load_probe_info(self):
        if not os.path.exists(self.filepath):
            self.lbl_status.setText(self.translator.translate('file_not_exists', "Файл не существует."))
            self.lbl_status.show()
            self.scroll_area.hide()
            return

        self.lbl_status.setText(self.translator.translate('analyzing_file', "Анализ структуры файла..."))
        self.lbl_status.show()
        self.scroll_area.hide()

        worker = FFprobeWorker(self.filepath, self.ffprobe_path)
        worker.signals.data_ready.connect(self._on_data_ready)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_data_ready(self, data: dict):
        self.raw_data = data
        self.btn_copy.setEnabled(True)
        self.lbl_status.hide()
        self.scroll_area.show()

        # Очищаем сетку
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        fmt = data.get('format', {})
        streams = data.get('streams', [])

        video_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
        audio_stream = next((s for s in streams if s.get('codec_type') == 'audio'), None)

        row = 0

        def add_section(title: str):
            nonlocal row
            lbl = QLabel(title)
            lbl.setStyleSheet("color: #409cff; font-size: 14px; font-weight: bold; padding-top: 16px; padding-bottom: 6px;")
            self.grid_layout.addWidget(lbl, row, 0, 1, 2)
            row += 1

        def add_row(k: str, v: str):
            nonlocal row
            k_lbl = QLabel(k + ":")
            k_lbl.setStyleSheet("color: #aaaaaa; font-size: 13px; padding: 4px 0; min-height: 24px;")
            v_lbl = QLabel(v)
            v_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v_lbl.setStyleSheet("color: #f0f0f0; font-size: 13px; font-weight: 500; padding: 4px 0; min-height: 24px;")
            self.grid_layout.addWidget(k_lbl, row, 0)
            self.grid_layout.addWidget(v_lbl, row, 1)
            row += 1

        add_section(self.translator.translate('general_info', "Общие сведения"))
        size_bytes = int(fmt.get('size', 0))
        size_mb = size_bytes / (1024 * 1024)
        add_row(self.translator.translate('file_size', "Размер"), f"{size_mb:.2f} МБ ({size_bytes:,} байт)")

        dur_sec = float(fmt.get('duration', 0))
        m, s = divmod(int(dur_sec), 60)
        h, m = divmod(m, 60)
        dur_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        add_row(self.translator.translate('duration', "Длительность"), f"{dur_str} ({dur_sec:.1f} сек)")

        bitrate = int(fmt.get('bit_rate', 0))
        if bitrate > 0:
            add_row(self.translator.translate('bitrate', "Общий битрейт"), f"{bitrate // 1000} кбит/с")

        fmt_name = fmt.get('format_long_name', fmt.get('format_name', ''))
        add_row(self.translator.translate('container', "Контейнер"), fmt_name)

        # Видеодорожка
        if video_stream:
            add_section(self.translator.translate('video_stream', "Видеопоток"))
            codec = video_stream.get('codec_name', '').upper()
            profile = video_stream.get('profile', '')
            add_row(self.translator.translate('codec', "Видеокодек"), f"{codec} ({profile})" if profile else codec)

            w = video_stream.get('width', 0)
            h_res = video_stream.get('height', 0)
            aspect = video_stream.get('display_aspect_ratio', '')
            res_str = f"{w}x{h_res}" + (f" ({aspect})" if aspect else "")
            add_row(self.translator.translate('resolution', "Разрешение"), res_str)

            r_frame = video_stream.get('r_frame_rate', '0/1')
            try:
                num, den = map(int, r_frame.split('/'))
                fps = num / den if den != 0 else 0
                add_row(self.translator.translate('fps', "Частота кадров"), f"{fps:.2f} кадр/с")
            except Exception:
                pass

            v_bitrate = int(video_stream.get('bit_rate', 0))
            if v_bitrate > 0:
                add_row(self.translator.translate('video_bitrate', "Битрейт видео"), f"{v_bitrate // 1000} кбит/с")

            pix_fmt = video_stream.get('pix_fmt', '')
            if pix_fmt:
                add_row(self.translator.translate('pixel_format', "Формат пикселей"), pix_fmt)

        # Аудиодорожка
        if audio_stream:
            add_section(self.translator.translate('audio_stream', "Аудиопоток"))
            a_codec = audio_stream.get('codec_name', '').upper()
            add_row(self.translator.translate('audio_codec', "Аудиокодек"), a_codec)

            channels = audio_stream.get('channels', 0)
            ch_layout = audio_stream.get('channel_layout', '')
            add_row(self.translator.translate('channels', "Каналы"), f"{channels} ({ch_layout})" if ch_layout else str(channels))

            sample_rate = audio_stream.get('sample_rate', 0)
            if sample_rate:
                add_row(self.translator.translate('sample_rate', "Частота дискретизации"), f"{sample_rate} Гц")

            a_bitrate = int(audio_stream.get('bit_rate', 0))
            if a_bitrate > 0:
                add_row(self.translator.translate('audio_bitrate', "Битрейт аудио"), f"{a_bitrate // 1000} кбит/с")

        self.grid_layout.setRowStretch(row, 1)

    def _on_error(self, err_msg: str):
        self.lbl_status.setText(f"{self.translator.translate('error', 'Ошибка')}:\n{err_msg}")
        self.lbl_status.setStyleSheet("color: #d32f2f; font-size: 13px;")

    def _copy_to_clipboard(self):
        if not self.raw_data:
            return
        report = []
        filename = os.path.basename(self.filepath)
        report.append(f"Файл: {filename}")
        report.append(f"Путь: {self.filepath}")

        fmt = self.raw_data.get('format', {})
        report.append(f"Размер: {int(fmt.get('size', 0)) / (1024*1024):.2f} МБ")
        report.append(f"Длительность: {float(fmt.get('duration', 0)):.1f} сек")

        for s in self.raw_data.get('streams', []):
            ctype = s.get('codec_type')
            if ctype == 'video':
                report.append(f"Видео: {s.get('codec_name')} | {s.get('width')}x{s.get('height')} | FPS: {s.get('r_frame_rate')}")
            elif ctype == 'audio':
                report.append(f"Аудио: {s.get('codec_name')} | {s.get('channels')} ch | {s.get('sample_rate')} Hz")

        text = "\n".join(report)
        QApplication.clipboard().setText(text)
        InfoBar.success(
            title=self.translator.translate('copied', "Скопировано"),
            content=self.translator.translate('report_copied_tip', "Свойства файла скопированы в буфер обмена."),
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self
        )
