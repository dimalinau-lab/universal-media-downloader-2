import os
import math
import subprocess
import traceback
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QListWidget, QListWidgetItem, QPushButton, QLabel, QMessageBox,
                             QDialog, QFormLayout, QTimeEdit, QSlider, QStyle)
from PyQt6.QtCore import Qt, QUrl, QRunnable, pyqtSignal, QObject, QTime
from PyQt6.QtGui import QDesktopServices, QPixmap

# --- ДОБАВЛЕНЫ БИБЛИОТЕКИ ДЛЯ ВИДЕОПЛЕЕРА ---
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from qfluentwidgets import TransparentToolButton, FluentIcon


class ThumbSignals(QObject):
    loaded = pyqtSignal(QPixmap)


class LocalThumbWorker(QRunnable):
    def __init__(self, filepath, ffmpeg_path):
        super().__init__()
        self.filepath = filepath
        self.ffmpeg_path = ffmpeg_path
        self.signals = ThumbSignals()

    def run(self):
        try:
            cmd = [
                self.ffmpeg_path,
                '-y',
                '-ss', '00:00:01',
                '-i', self.filepath,
                '-vframes', '1',
                '-q:v', '2',
                '-f', 'image2pipe',
                '-vcodec', 'mjpeg',
                '-'
            ]
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
            stdout, _ = process.communicate()

            if stdout:
                pixmap = QPixmap()
                pixmap.loadFromData(stdout)
                self.signals.loaded.emit(pixmap)
        except Exception:
            pass


# ==========================================
# --- ЛОГИКА ТРИММЕРА (ОБРЕЗКА ВИДЕО) ---
# ==========================================
class TrimSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)


class TrimWorker(QRunnable):
    def __init__(self, ffmpeg_path, input_path, output_path, start_str, end_str):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.input_path = input_path
        self.output_path = output_path
        self.start_str = start_str
        self.end_str = end_str
        self.signals = TrimSignals()

    def run(self):
        try:
            cmd = [
                self.ffmpeg_path, '-y',
                '-i', self.input_path,
                '-ss', self.start_str,
                '-to', self.end_str,
                '-c', 'copy',
                self.output_path
            ]
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)

            if process.returncode == 0:
                self.signals.finished.emit(self.output_path)
            else:
                self.signals.error.emit(process.stderr.decode('utf-8', errors='ignore'))
        except Exception as e:
            self.signals.error.emit(str(e))


class TrimDialog(QDialog):
    def __init__(self, translator, filepath, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.filepath = filepath
        self.setWindowTitle(self.translator.translate('trim_video', 'Визуальная обрезка файла'))
        self.resize(650, 500)  # Увеличили окно для плеера
        self.initUI()
        self.init_player()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # 1. Видеоплеер (Превью)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(300)
        self.video_widget.setStyleSheet("background-color: black; border-radius: 8px;")
        layout.addWidget(self.video_widget)

        # 2. Управление плеером (Play/Pause и Ползунок)
        playback_layout = QHBoxLayout()

        self.btn_play = QPushButton()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_play.setFixedSize(35, 35)
        self.btn_play.clicked.connect(self.toggle_play)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setFixedWidth(100)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        playback_layout.addWidget(self.btn_play)
        playback_layout.addWidget(self.slider)
        playback_layout.addWidget(self.time_label)
        layout.addLayout(playback_layout)

        # 3. Маркеры времени (Задать начало и конец)
        markers_layout = QHBoxLayout()

        self.btn_set_start = QPushButton("⬅️ Старт отсюда")
        self.btn_set_start.setObjectName('SecondaryButton')
        self.btn_set_start.clicked.connect(self.mark_start)

        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("HH:mm:ss")
        self.start_time.setTime(QTime(0, 0, 0))

        markers_layout.addWidget(self.btn_set_start)
        markers_layout.addWidget(self.start_time)
        markers_layout.addStretch()

        self.end_time = QTimeEdit()
        self.end_time.setDisplayFormat("HH:mm:ss")
        self.end_time.setTime(QTime(0, 0, 0))

        self.btn_set_end = QPushButton("Финиш здесь ➡️")
        self.btn_set_end.setObjectName('SecondaryButton')
        self.btn_set_end.clicked.connect(self.mark_end)

        markers_layout.addWidget(self.end_time)
        markers_layout.addWidget(self.btn_set_end)
        layout.addLayout(markers_layout)

        # 4. Финальные кнопки Обрезать / Отмена
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton(self.translator.translate('cut_btn', '✂️ Обрезать файл'))
        self.btn_ok.setObjectName('ActionButton')
        self.btn_ok.setFixedHeight(40)
        self.btn_ok.clicked.connect(self.accept_trim)

        self.btn_cancel = QPushButton(self.translator.translate('cancel', 'Отмена'))
        self.btn_cancel.setObjectName('SecondaryButton')
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

    def init_player(self):
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)

        self.player.setSource(QUrl.fromLocalFile(self.filepath))
        self.player.pause()  # Оставляем на паузе при старте

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            self.player.play()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def position_changed(self, position):
        self.slider.setValue(position)
        self.update_time_label()

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label()

        # Автоматически ставим "Конец" на общую длину видео
        total_seconds = duration // 1000
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        self.end_time.setTime(QTime(h, m, s))

    def set_position(self, position):
        self.player.setPosition(position)

    def update_time_label(self):
        pos = self.player.position() // 1000
        dur = self.player.duration() // 1000
        self.time_label.setText(f"{self.format_time(pos)} / {self.format_time(dur)}")

    def format_time(self, seconds):
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def mark_start(self):
        pos = self.player.position() // 1000
        h = pos // 3600
        m = (pos % 3600) // 60
        s = pos % 60
        self.start_time.setTime(QTime(h, m, s))

    def mark_end(self):
        pos = self.player.position() // 1000
        h = pos // 3600
        m = (pos % 3600) // 60
        s = pos % 60
        self.end_time.setTime(QTime(h, m, s))

    def accept_trim(self):
        self.player.stop()  # Обязательно глушим плеер перед обрезкой, чтобы файл не был "занят"
        self.accept()

    def reject(self):
        self.player.stop()
        super().reject()


# ==========================================


class LocalFileItemWidget(QWidget):
    def __init__(self, filepath, parent_tab):
        super().__init__()
        self.filepath = filepath
        self.parent_tab = parent_tab
        self.translator = parent_tab.translator
        self.setObjectName('DownloadItem')
        self.initUI()
        self.load_thumbnail()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(128, 72)
        self.thumbnail_label.setObjectName('Thumbnail')
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("background-color: #2b2b2b; border-radius: 8px;")
        main_layout.addWidget(self.thumbnail_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)

        filename = os.path.basename(self.filepath)
        self.title_label = QLabel(filename)
        self.title_label.setObjectName('TitleLabel')
        self.title_label.setWordWrap(True)

        self.url_label = QLabel(self.filepath)
        self.url_label.setObjectName('UrlLabel')
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        status_layout = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setObjectName('StatusLabelItem')
        self.status_label.setStyleSheet("color: #007acc; font-weight: bold;")

        size_bytes = os.path.getsize(self.filepath) if os.path.exists(self.filepath) else 0
        self.size_label = QLabel(self.format_size(size_bytes))
        self.size_label.setObjectName('SizeLabelItem')
        self.size_label.setStyleSheet("color: #007acc; font-weight: bold; font-size: 13px;")
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.size_label)

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.url_label)
        info_layout.addLayout(status_layout)
        info_layout.addStretch()

        main_layout.addLayout(info_layout, 1)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(6)

        self.btn_open = TransparentToolButton(FluentIcon.PLAY)
        self.btn_open.setFixedSize(34, 34)
        self.btn_open.clicked.connect(self.open_file)

        self.btn_folder = TransparentToolButton(FluentIcon.FOLDER)
        self.btn_folder.setFixedSize(34, 34)
        self.btn_folder.clicked.connect(self.open_folder)

        self.btn_trim = TransparentToolButton(FluentIcon.CUT)
        self.btn_trim.setFixedSize(34, 34)
        self.btn_trim.clicked.connect(self.trim_file)

        self.btn_delete = TransparentToolButton(FluentIcon.DELETE)
        self.btn_delete.setFixedSize(34, 34)
        self.btn_delete.clicked.connect(self.delete_file)

        btn_layout.addWidget(self.btn_open)
        btn_layout.addWidget(self.btn_folder)
        btn_layout.addWidget(self.btn_trim)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()

        main_layout.addLayout(btn_layout)

        self.update_translations()

    def update_translations(self):
        self.status_label.setText(self.translator.translate('status_downloaded', 'Скачано ✓'))
        self.btn_open.setToolTip(self.translator.translate('play_video', 'Воспроизвести видео'))
        self.btn_folder.setToolTip(self.translator.translate('show_in_folder', 'Показать в папке'))
        self.btn_trim.setToolTip(self.translator.translate('trim_file_tooltip', 'Обрезать фрагмент'))
        self.btn_delete.setToolTip(self.translator.translate('delete_file_forever', 'Удалить файл навсегда'))

    def load_thumbnail(self):
        ffmpeg_path = self.parent_tab.parent_window.ffmpeg_path
        worker = LocalThumbWorker(self.filepath, ffmpeg_path)
        worker.signals.loaded.connect(self.set_thumbnail)
        self.parent_tab.parent_window.thread_pool.start(worker)

    def set_thumbnail(self, pixmap):
        if not pixmap.isNull():
            scaled = pixmap.scaled(self.thumbnail_label.size(),
                                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            self.thumbnail_label.setPixmap(scaled)

    def format_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    def open_file(self):
        if os.path.exists(self.filepath):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.filepath))
        else:
            QMessageBox.warning(self, self.translator.translate('error', 'Ошибка'),
                                self.translator.translate('file_not_exists',
                                                          'Файл больше не существует. Обновите список.'))

    def open_folder(self):
        if os.path.exists(self.filepath):
            folder = os.path.dirname(self.filepath)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def trim_file(self):
        try:
            if not os.path.exists(self.filepath):
                QMessageBox.warning(self, "Ошибка",
                                    f"Файл не найден на диске! Возможно, он был перемещен.\nПуть: {self.filepath}")
                return

            dialog = TrimDialog(self.translator, self.filepath, self)
            if dialog.exec():
                start_str = dialog.start_time.time().toString("HH:mm:ss")
                end_str = dialog.end_time.time().toString("HH:mm:ss")

                if start_str == "00:00:00" and end_str == "00:00:00":
                    return

                base, ext = os.path.splitext(self.filepath)
                output_path = f"{base}_trimmed{ext}"

                self.status_label.setText("Режем... ✂️")
                self.btn_trim.setEnabled(False)

                ffmpeg_path = self.parent_tab.parent_window.ffmpeg_path
                worker = TrimWorker(ffmpeg_path, self.filepath, output_path, start_str, end_str)
                worker.signals.finished.connect(self._on_trim_finished)
                worker.signals.error.connect(self._on_trim_error)
                self.parent_tab.parent_window.thread_pool.start(worker)

        except Exception as e:
            QMessageBox.critical(self, "Скрытая ошибка Python",
                                 f"Произошел сбой:\n{str(e)}\n\n{traceback.format_exc()}")

    def _on_trim_finished(self, out_path):
        self.status_label.setText(self.translator.translate('status_downloaded', 'Скачано ✓'))
        self.btn_trim.setEnabled(True)
        QMessageBox.information(self, "Готово",
                                f"Видео успешно обрезано!\nСохранено как:\n{os.path.basename(out_path)}")
        self.parent_tab.load_files()

    def _on_trim_error(self, err_msg):
        self.status_label.setText(self.translator.translate('status_downloaded', 'Скачано ✓'))
        self.btn_trim.setEnabled(True)
        QMessageBox.warning(self, "Ошибка обрезки FFmpeg", f"Не удалось обрезать файл:\n{err_msg}")

    def delete_file(self):
        filename = os.path.basename(self.filepath)
        confirm_text = self.translator.translate('delete_file_confirm',
                                                 'Вы уверены, что хотите безвозвратно удалить файл:\n{filename}?').replace(
            '{filename}', filename)

        reply = QMessageBox.question(
            self,
            self.translator.translate('delete_file_title', 'Удаление файла'),
            confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self.filepath)
                self.parent_tab.load_files()
            except Exception as e:
                err_text = self.translator.translate('failed_to_delete', 'Не удалось удалить файл:\n{error}').replace(
                    '{error}', str(e))
                QMessageBox.warning(self, self.translator.translate('error', 'Ошибка'), err_text)


class FilesTab(QWidget):
    def __init__(self, translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.parent_window = parent
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header_layout = QHBoxLayout()
        self.header_label = QLabel()
        self.header_label.setStyleSheet('font-size: 18px; font-weight: bold;')

        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName('SecondaryButton')
        self.btn_refresh.clicked.connect(self.load_files)

        self.btn_open_folder = QPushButton()
        self.btn_open_folder.setObjectName('SecondaryButton')
        self.btn_open_folder.clicked.connect(self.open_folder)

        header_layout.addWidget(self.header_label)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_refresh)
        header_layout.addWidget(self.btn_open_folder)

        layout.addLayout(header_layout)

        self.files_list = QListWidget()
        self.files_list.setObjectName('DownloadsList')
        self.files_list.setSpacing(5)
        layout.addWidget(self.files_list)

        self.update_translations()

    def load_files(self):
        self.files_list.clear()
        folder = self.parent_window.settings.value('save_path', '')

        if not folder or not os.path.isdir(folder):
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            folder = os.path.join(project_root, 'downloads')

        if os.path.isdir(folder):
            valid_extensions = ('.mp4', '.mkv', '.avi', '.webm', '.mp3', '.m4a', '.mov')

            files = []
            for filename in os.listdir(folder):
                if filename.lower().endswith(valid_extensions):
                    filepath = os.path.join(folder, filename)
                    files.append((filepath, os.path.getctime(filepath)))

            files.sort(key=lambda x: x[1], reverse=True)

            for filepath, _ in files:
                item_widget = LocalFileItemWidget(filepath, self)
                list_item = QListWidgetItem(self.files_list)
                list_item.setSizeHint(item_widget.sizeHint())

                self.files_list.addItem(list_item)
                self.files_list.setItemWidget(list_item, item_widget)

    def open_folder(self):
        self.parent_window.open_save_folder()

    def update_translations(self):
        self.header_label.setText(self.translator.translate('downloaded_files', 'Скачанные файлы'))
        self.btn_refresh.setText(self.translator.translate('refresh', 'Обновить список'))
        self.btn_open_folder.setText(self.translator.translate('open_save_folder', 'Открыть папку'))

        for i in range(self.files_list.count()):
            item = self.files_list.item(i)
            widget = self.files_list.itemWidget(item)
            if hasattr(widget, 'update_translations'):
                widget.update_translations()