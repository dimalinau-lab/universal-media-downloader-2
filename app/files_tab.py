import os
import math
import subprocess
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QListWidget, QListWidgetItem, QPushButton, QLabel, QMessageBox,
                             QDialog, QLineEdit)
from PyQt6.QtCore import Qt, QUrl, QRunnable, pyqtSignal, QObject
from PyQt6.QtGui import QDesktopServices, QPixmap
from qfluentwidgets import TransparentToolButton, FluentIcon
from PyQt6.QtWidgets import QSlider, QLineEdit, QDialog
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

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


class VideoCutterDialog(QDialog):
    def __init__(self, filepath, ffmpeg_path, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.ffmpeg_path = ffmpeg_path
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Обрезать видео")
        self.setFixedSize(320, 150)
        layout = QVBoxLayout(self)


        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Начало (ЧЧ:ММ:СС):"))
        self.start_input = QLineEdit("00:00:00")
        start_layout.addWidget(self.start_input)
        layout.addLayout(start_layout)


        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("Конец (ЧЧ:ММ:СС):"))
        self.end_input = QLineEdit("00:00:00")
        end_layout.addWidget(self.end_input)
        layout.addLayout(end_layout)


        btn_layout = QHBoxLayout()
        self.btn_cut = QPushButton("Обрезать")
        self.btn_cut.setObjectName('ActionButton')
        self.btn_cut.clicked.connect(self.process_cut)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setObjectName('SecondaryButton')
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_cut)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def process_cut(self):
        start_time = self.start_input.text().strip()
        end_time = self.end_input.text().strip()


        base, ext = os.path.splitext(self.filepath)
        out_path = f"{base}_cut{ext}"

        cmd = [
            self.ffmpeg_path,
            '-y',
            '-i', self.filepath,
            '-ss', start_time,
            '-to', end_time,
            '-c', 'copy',
            out_path
        ]

        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self.btn_cut.setText("Режем...")
            self.btn_cut.setEnabled(False)

            subprocess.run(cmd, check=True, creationflags=flags)
            QMessageBox.information(self, "Успех", "Видео успешно обрезано!\nНовый файл сохранен рядом с оригиналом.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось обрезать видео:\n{e}")
            self.btn_cut.setText("Обрезать")
            self.btn_cut.setEnabled(True)

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

        self.btn_cut = TransparentToolButton(FluentIcon.CUT)
        self.btn_cut.setFixedSize(34, 34)
        self.btn_cut.clicked.connect(self.cut_file)

        self.btn_folder = TransparentToolButton(FluentIcon.FOLDER)
        self.btn_folder.setFixedSize(34, 34)
        self.btn_folder.clicked.connect(self.open_folder)

        self.btn_delete = TransparentToolButton(FluentIcon.DELETE)
        self.btn_delete.setFixedSize(34, 34)
        self.btn_delete.clicked.connect(self.delete_file)

        btn_layout.addWidget(self.btn_open)
        btn_layout.addWidget(self.btn_cut)
        btn_layout.addWidget(self.btn_folder)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()

        main_layout.addLayout(btn_layout)


        self.update_translations()

    def update_translations(self):
        self.status_label.setText(self.translator.translate('status_downloaded', 'Скачано ✓'))
        self.btn_open.setToolTip(self.translator.translate('play_video', 'Воспроизвести видео'))
        self.btn_cut.setToolTip(self.translator.translate('cut_video', 'Обрезать по таймингу')) # <-- Добавлено
        self.btn_folder.setToolTip(self.translator.translate('show_in_folder', 'Показать в папке'))
        self.btn_delete.setToolTip(self.translator.translate('delete_file_forever', 'Удалить файл навсегда'))

    def cut_file(self):
        if not os.path.exists(self.filepath):
            QMessageBox.warning(self, self.translator.translate('error', 'Ошибка'),
                                self.translator.translate('file_not_exists',
                                                          'Файл больше не существует. Обновите список.'))
            return

        ffmpeg_path = self.parent_tab.parent_window.ffmpeg_path

        dialog = VideoCutterDialog(self.filepath, ffmpeg_path, self)
        if dialog.exec():
            self.parent_tab.load_files()
            return
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


class VideoCutterDialog(QDialog):
    def __init__(self, filepath, ffmpeg_path, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.ffmpeg_path = ffmpeg_path
        self.initUI()
        self.init_player()

    def initUI(self):
        self.setWindowTitle("Визуальная обрезка видео")
        self.setMinimumSize(720, 480)
        layout = QVBoxLayout(self)

        # 1. Видеоплеер
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        layout.addWidget(self.video_widget, stretch=1)

        # 2. Ползунок времени
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self.set_position)
        layout.addWidget(self.slider)

        # 3. Управление плеером (Play / Pause)
        controls_layout = QHBoxLayout()
        self.btn_play = QPushButton("▶ Play / Pause")
        self.btn_play.clicked.connect(self.toggle_play)

        self.lbl_time = QLabel("00:00:00 / 00:00:00")

        controls_layout.addWidget(self.btn_play)
        controls_layout.addWidget(self.lbl_time)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        times_layout = QHBoxLayout()

        self.btn_set_start = QPushButton("⬅ Начать отсюда")
        self.btn_set_start.setObjectName('SecondaryButton')
        self.btn_set_start.clicked.connect(self.set_start_time)
        self.start_input = QLineEdit("00:00:00")
        self.start_input.setFixedWidth(80)

        self.btn_set_end = QPushButton("Закончить здесь ➡")
        self.btn_set_end.setObjectName('SecondaryButton')
        self.btn_set_end.clicked.connect(self.set_end_time)
        self.end_input = QLineEdit("00:00:00")
        self.end_input.setFixedWidth(80)

        times_layout.addWidget(self.btn_set_start)
        times_layout.addWidget(self.start_input)
        times_layout.addStretch()
        times_layout.addWidget(self.end_input)
        times_layout.addWidget(self.btn_set_end)
        layout.addLayout(times_layout)

        # 5. Финальные кнопки обрезки
        btn_layout = QHBoxLayout()
        self.btn_cut = QPushButton("✂ Обрезать и сохранить")
        self.btn_cut.setObjectName('ActionButton')
        self.btn_cut.clicked.connect(self.process_cut)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setObjectName('SecondaryButton')
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cut)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def init_player(self):
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)

        self.media_player.setSource(QUrl.fromLocalFile(self.filepath))

    def toggle_play(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def position_changed(self, position):
        self.slider.setValue(position)
        self.update_time_label()

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label()

    def set_position(self, position):
        self.media_player.setPosition(position)

    def update_time_label(self):
        pos = self.format_time(self.media_player.position())
        dur = self.format_time(self.media_player.duration())
        self.lbl_time.setText(f"{pos} / {dur}")

    def format_time(self, ms):
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def set_start_time(self):
        self.start_input.setText(self.format_time(self.media_player.position()))

    def set_end_time(self):
        self.end_input.setText(self.format_time(self.media_player.position()))

    def process_cut(self):
        self.media_player.pause()  # Ставим на паузу перед обрезкой
        start_time = self.start_input.text().strip()
        end_time = self.end_input.text().strip()

        base, ext = os.path.splitext(self.filepath)
        out_path = f"{base}_cut{ext}"

        cmd = [
            self.ffmpeg_path, '-y',
            '-i', self.filepath,
            '-ss', start_time,
            '-to', end_time,
            '-c', 'copy',
            out_path
        ]

        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self.btn_cut.setText("Режем...")
            self.btn_cut.setEnabled(False)

            subprocess.run(cmd, check=True, creationflags=flags)
            QMessageBox.information(self, "Успех", "Видео успешно обрезано!\nСохранено рядом с оригиналом.")

            self.media_player.setSource(QUrl())  # Освобождаем файл
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось обрезать видео:\n{e}")
            self.btn_cut.setText("✂ Обрезать и сохранить")
            self.btn_cut.setEnabled(True)

    def closeEvent(self, event):
        self.media_player.setSource(QUrl())  # Защита от блокировки файла
        super().closeEvent(event)

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