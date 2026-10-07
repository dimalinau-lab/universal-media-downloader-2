import os
import subprocess
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QMessageBox
)
from PyQt6.QtCore import Qt, QRunnable, QObject, pyqtSignal, QThreadPool
from qfluentwidgets import (
    PrimaryPushButton, PushButton, ComboBox, Slider,
    SwitchButton, StrongBodyLabel, BodyLabel, CaptionLabel,
    FluentIcon, LineEdit
)


class AudioWorkerSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)


class AudioConvertWorker(QRunnable):
    def __init__(self, cmd: list[str], out_path: str):
        super().__init__()
        self.cmd = cmd
        self.out_path = out_path
        self.signals = AudioWorkerSignals()

    def run(self):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            res = subprocess.run(self.cmd, capture_output=True, text=True, creationflags=flags, encoding='utf-8', errors='replace')
            if res.returncode == 0 or (os.path.exists(self.out_path) and os.path.getsize(self.out_path) > 1024):
                self.signals.finished.emit(self.out_path)
            else:
                self.signals.error.emit(res.stderr or "FFmpeg audio conversion error")
        except Exception as e:
            self.signals.error.emit(str(e))


class AudioConvertDialog(QDialog):
    """
    Диалог извлечения и конвертации аудиодорожки из видеофайла.
    Поддерживает MP3, M4A, FLAC, WAV, OGG, OPUS, а также нормализацию громкости
    (EBU R128) и усиление звука.
    """
    def __init__(self, filepath: str, ffmpeg_path: str, translator, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.ffmpeg_path = ffmpeg_path
        self.translator = translator
        self.out_path = ""

        self.setWindowTitle(self.translator.translate('audio_tool_title', "Извлечение и конвертация аудио"))
        self.setFixedSize(500, 440)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Шапка
        filename = os.path.basename(self.filepath)
        title = StrongBodyLabel(filename)
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        desc = CaptionLabel(self.translator.translate(
            'audio_tool_desc',
            "Извлеките чистый звук в нужном формате с фильтрами улучшения звучания."
        ))
        desc.setStyleSheet("color: #888888;")
        layout.addWidget(desc)

        # Выбор формата
        fmt_layout = QHBoxLayout()
        lbl_fmt = BodyLabel(self.translator.translate('target_format', "Формат файла:"))
        self.combo_format = ComboBox()
        self.combo_format.setFixedWidth(200)
        self.combo_format.addItem("MP3 (.mp3)", userData="mp3")
        self.combo_format.addItem("M4A / AAC (.m4a)", userData="m4a")
        self.combo_format.addItem("FLAC Lossless (.flac)", userData="flac")
        self.combo_format.addItem("WAV PCM (.wav)", userData="wav")
        self.combo_format.addItem("OGG Vorbis (.ogg)", userData="ogg")
        self.combo_format.addItem("OPUS (.opus)", userData="opus")
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)

        fmt_layout.addWidget(lbl_fmt)
        fmt_layout.addStretch()
        fmt_layout.addWidget(self.combo_format)
        layout.addLayout(fmt_layout)

        # Битрейт
        bitrate_layout = QHBoxLayout()
        self.lbl_bitrate = BodyLabel(self.translator.translate('audio_bitrate_label', "Битрейт аудио:"))
        self.combo_bitrate = ComboBox()
        self.combo_bitrate.setFixedWidth(200)
        self.combo_bitrate.addItem("320 kbps (High Quality)", userData="320k")
        self.combo_bitrate.addItem("256 kbps (Very Good)", userData="256k")
        self.combo_bitrate.addItem("192 kbps (Standard)", userData="192k")
        self.combo_bitrate.addItem("128 kbps (Compact)", userData="128k")
        self.combo_bitrate.addItem("96 kbps (Speech/Podcast)", userData="96k")

        bitrate_layout.addWidget(self.lbl_bitrate)
        bitrate_layout.addStretch()
        bitrate_layout.addWidget(self.combo_bitrate)
        layout.addLayout(bitrate_layout)

        # Нормализация громкости (EBU R128)
        norm_layout = QHBoxLayout()
        lbl_norm = BodyLabel(self.translator.translate('audio_loudnorm', "Нормализация звука (EBU R128):"))
        self.switch_norm = SwitchButton()
        self.switch_norm.setOnText(self.translator.translate('on', "Вкл"))
        self.switch_norm.setOffText(self.translator.translate('off', "Выкл"))
        norm_layout.addWidget(lbl_norm)
        norm_layout.addStretch()
        norm_layout.addWidget(self.switch_norm)
        layout.addLayout(norm_layout)

        # Усиление громкости (Volume boost)
        vol_layout = QHBoxLayout()
        self.lbl_vol = BodyLabel(self.translator.translate('audio_volume_boost', "Громкость: 100%"))
        self.slider_vol = Slider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(50, 250)
        self.slider_vol.setValue(100)
        self.slider_vol.setFixedWidth(180)
        self.slider_vol.valueChanged.connect(lambda v: self.lbl_vol.setText(
            f"{self.translator.translate('audio_volume_boost', 'Громкость')}: {v}%"
        ))

        vol_layout.addWidget(self.lbl_vol)
        vol_layout.addStretch()
        vol_layout.addWidget(self.slider_vol)
        layout.addLayout(vol_layout)

        # Имя выходного файла
        out_layout = QHBoxLayout()
        lbl_out = BodyLabel(self.translator.translate('output_name', "Имя файла:"))
        self.input_name = LineEdit()
        base_name, _ = os.path.splitext(filename)
        self.input_name.setText(f"{base_name}")
        out_layout.addWidget(lbl_out)
        out_layout.addWidget(self.input_name, 1)
        layout.addLayout(out_layout)

        # Кнопки
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)

        self.btn_cancel = PushButton(self.translator.translate('cancel_action', "Отмена"))
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_convert = PrimaryPushButton(
            FluentIcon.MUSIC,
            self.translator.translate('extract_audio_btn', "Извлечь аудио")
        )
        self.btn_convert.clicked.connect(self._process_convert)

        btn_box.addStretch()
        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(self.btn_convert)
        layout.addLayout(btn_box)

    def _on_format_changed(self):
        ext = self.combo_format.currentData()
        is_lossless = ext in ('flac', 'wav')
        self.combo_bitrate.setEnabled(not is_lossless)
        if is_lossless:
            self.lbl_bitrate.setText(self.translator.translate('audio_bitrate_lossless', "Битрейт: Lossless (Без потерь)"))
        else:
            self.lbl_bitrate.setText(self.translator.translate('audio_bitrate_label', "Битрейт аудио:"))

    def _process_convert(self):
        ext = self.combo_format.currentData()
        bitrate = self.combo_bitrate.currentData()
        do_norm = self.switch_norm.isChecked()
        vol_val = self.slider_vol.value()

        out_name = self.input_name.text().strip()
        if not out_name:
            out_name = os.path.splitext(os.path.basename(self.filepath))[0]

        dir_path = os.path.dirname(self.filepath)
        self.out_path = os.path.join(dir_path, f"{out_name}.{ext}")

        # Построение аудиофильтров (-af)
        filters = []
        if vol_val != 100:
            gain_factor = vol_val / 100.0
            filters.append(f"volume={gain_factor:.2f}")
        if do_norm:
            filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

        cmd = [
            self.ffmpeg_path, '-y',
            '-fflags', '+genpts+discardcorrupt',
            '-err_detect', 'ignore_err',
            '-max_error_rate', '1.0',
            '-i', self.filepath,
            '-vn'
        ]

        if filters:
            cmd.extend(['-af', ','.join(filters)])

        if ext == 'mp3':
            cmd.extend(['-c:a', 'libmp3lame', '-b:a', bitrate])
        elif ext == 'm4a':
            cmd.extend(['-c:a', 'aac', '-b:a', bitrate])
        elif ext == 'flac':
            cmd.extend(['-c:a', 'flac'])
        elif ext == 'wav':
            cmd.extend(['-c:a', 'pcm_s16le'])
        elif ext == 'ogg':
            cmd.extend(['-c:a', 'libvorbis', '-b:a', bitrate])
        elif ext == 'opus':
            cmd.extend(['-c:a', 'libopus', '-b:a', bitrate])

        cmd.append(self.out_path)

        self.btn_convert.setText(self.translator.translate('converting_progress', "Извлечение..."))
        self.btn_convert.setEnabled(False)
        self.btn_cancel.setEnabled(False)

        worker = AudioConvertWorker(cmd, self.out_path)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_finished(self, out_path: str):
        size_mb = os.path.getsize(out_path) / (1024 * 1024) if os.path.exists(out_path) else 0
        QMessageBox.information(
            self,
            self.translator.translate('success', "Успешно"),
            f"{self.translator.translate('audio_extracted_success', 'Аудиодорожка успешно извлечена!')}\n\n"
            f"Файл: {os.path.basename(out_path)}\n"
            f"Размер: {size_mb:.2f} МБ"
        )
        self.accept()

    def _on_error(self, err: str):
        QMessageBox.critical(
            self,
            self.translator.translate('error', "Ошибка"),
            f"{self.translator.translate('audio_convert_failed', 'Не удалось извлечь аудио:')}\n{err}"
        )
        self.btn_convert.setText(self.translator.translate('extract_audio_btn', "Извлечь аудио"))
        self.btn_convert.setEnabled(True)
        self.btn_cancel.setEnabled(True)
