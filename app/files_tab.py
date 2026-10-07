import os
import math
import subprocess
import traceback
import hashlib
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QListWidget, QListWidgetItem, QPushButton, QLabel, QMessageBox,
                             QDialog, QLineEdit, QSlider, QMenu)
from PyQt6.QtCore import Qt, QUrl, QRunnable, pyqtSignal, QObject, QThreadPool
from PyQt6.QtGui import QDesktopServices, QPixmap, QImage, QAction
from qfluentwidgets import (TransparentToolButton, FluentIcon, Slider,
                            PushButton, PrimaryPushButton, LineEdit, BodyLabel,
                            ComboBox, StrongBodyLabel, CaptionLabel, SwitchButton)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from .audio_convert_dialog import AudioConvertDialog
from .media_info_dialog import MediaInfoDialog


class CutSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)


class CutWorker(QRunnable):
    def __init__(self, cmd, out_path):
        super().__init__()
        self.cmd = cmd
        self.out_path = out_path
        self.signals = CutSignals()

    def run(self):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            res = subprocess.run(self.cmd, capture_output=True, text=True, creationflags=flags, encoding='utf-8', errors='replace')
            if res.returncode == 0 or (os.path.exists(self.out_path) and os.path.getsize(self.out_path) > 1024):
                self.signals.finished.emit(self.out_path)
            else:
                self.signals.error.emit(res.stderr or "FFmpeg execution failed")
        except Exception as e:
            self.signals.error.emit(str(e))


class ThumbSignals(QObject):
    loaded = pyqtSignal(QImage)
    error = pyqtSignal(str)


class LocalThumbWorker(QRunnable):
    def __init__(self, filepath, ffmpeg_path):
        super().__init__()
        self.filepath = filepath
        self.ffmpeg_path = ffmpeg_path
        self.signals = ThumbSignals()

    def run(self):
        try:
            cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'thumbs_cache')
            os.makedirs(cache_dir, exist_ok=True)
            mtime = os.path.getmtime(self.filepath) if os.path.exists(self.filepath) else 0
            cache_key = hashlib.md5(f"{self.filepath}_{mtime}".encode('utf-8')).hexdigest() + ".jpg"
            cache_file = os.path.join(cache_dir, cache_key)

            if os.path.exists(cache_file):
                cached_image = QImage(cache_file)
                if not cached_image.isNull():
                    self.signals.loaded.emit(cached_image)
                    return

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
            image_data, _ = process.communicate()
            if image_data:
                image = QImage()
                image.loadFromData(image_data)
                if not image.isNull():
                    try:
                        image.save(cache_file, "JPG")
                    except Exception:
                        pass
                    self.signals.loaded.emit(image)
        except Exception as e:
            self.signals.error.emit(str(e))


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
        self.thumbnail_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumbnail_label.mousePressEvent = lambda e: self.preview_file()
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
        self.url_label.setWordWrap(True)
        self.url_label.setMinimumWidth(50)

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

        btn_grid = QGridLayout()
        btn_grid.setSpacing(4)
        btn_grid.setContentsMargins(0, 0, 0, 0)

        self.btn_open = TransparentToolButton(FluentIcon.PLAY)
        self.btn_open.setFixedSize(32, 32)
        self.btn_open.clicked.connect(self.open_file)

        self.btn_cut = TransparentToolButton(FluentIcon.CUT)
        self.btn_cut.setFixedSize(32, 32)
        self.btn_cut.clicked.connect(self.cut_file)

        self.btn_compress = TransparentToolButton(FluentIcon.SAVE)
        self.btn_compress.setFixedSize(32, 32)
        self.btn_compress.clicked.connect(self.compress_file)

        self.btn_audio = TransparentToolButton(FluentIcon.MUSIC)
        self.btn_audio.setFixedSize(32, 32)
        self.btn_audio.clicked.connect(self.extract_audio)

        self.btn_info = TransparentToolButton(FluentIcon.INFO)
        self.btn_info.setFixedSize(32, 32)
        self.btn_info.clicked.connect(self.show_media_info)

        self.btn_folder = TransparentToolButton(FluentIcon.FOLDER)
        self.btn_folder.setFixedSize(32, 32)
        self.btn_folder.clicked.connect(self.open_folder)

        self.btn_delete = TransparentToolButton(FluentIcon.DELETE)
        self.btn_delete.setFixedSize(32, 32)
        self.btn_delete.clicked.connect(self.delete_file)

        btn_grid.addWidget(self.btn_open, 0, 0)
        btn_grid.addWidget(self.btn_cut, 0, 1)
        btn_grid.addWidget(self.btn_compress, 1, 0)
        btn_grid.addWidget(self.btn_audio, 1, 1)
        btn_grid.addWidget(self.btn_info, 2, 0)
        btn_grid.addWidget(self.btn_folder, 2, 1)
        btn_grid.addWidget(self.btn_delete, 3, 0, 1, 2)

        main_layout.addLayout(btn_grid)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.update_translations()

    def show_context_menu(self, pos):
        menu = QMenu(self)
        act_preview = QAction(self.translator.translate('quick_preview', 'Быстрый просмотр (Мини-плеер)'), self)
        act_preview.triggered.connect(self.preview_file)
        act_open_ext = QAction(self.translator.translate('open_in_external_player', 'Открыть в системном плеере...'), self)
        act_open_ext.triggered.connect(self.open_file_external)
        act_info = QAction(self.translator.translate('mediainfo_menu', 'Свойства медиафайла (FFprobe)...'), self)
        act_info.triggered.connect(self.show_media_info)
        act_cut = QAction("Обрезать / Создать GIF...", self)
        act_cut.triggered.connect(self.cut_file)
        act_compress = QAction("Сжать видео (Telegram / Discord)...", self)
        act_compress.triggered.connect(self.compress_file)
        act_extract = QAction(self.translator.translate('extract_audio_menu', 'Извлечь / конвертировать аудио...'), self)
        act_extract.triggered.connect(self.extract_audio)
        act_folder = QAction("Показать в папке", self)
        act_folder.triggered.connect(self.open_folder)
        act_del = QAction("Удалить файл", self)
        act_del.triggered.connect(self.delete_file)

        menu.addAction(act_preview)
        menu.addAction(act_open_ext)
        menu.addAction(act_info)
        menu.addSeparator()
        menu.addAction(act_cut)
        menu.addAction(act_compress)
        menu.addAction(act_extract)
        menu.addSeparator()
        menu.addAction(act_folder)
        menu.addAction(act_del)
        menu.exec(self.mapToGlobal(pos))

    def update_translations(self):
        self.status_label.setText(self.translator.translate('status_downloaded', 'Скачано'))
        self.btn_open.setToolTip(self.translator.translate('quick_preview', 'Быстрый просмотр (Мини-плеер)'))
        self.thumbnail_label.setToolTip(self.translator.translate('quick_preview', 'Быстрый просмотр (Мини-плеер)'))
        self.btn_cut.setToolTip(self.translator.translate('cut_video', 'Обрезать / GIF'))
        self.btn_compress.setToolTip(self.translator.translate('compress_video', 'Сжать видео'))
        self.btn_audio.setToolTip(self.translator.translate('extract_audio_tooltip', 'Извлечь / конвертировать аудио'))
        self.btn_info.setToolTip(self.translator.translate('mediainfo_tooltip', 'Свойства медиафайла (FFprobe)'))
        self.btn_folder.setToolTip(self.translator.translate('show_in_folder', 'Показать в папке'))
        self.btn_delete.setToolTip(self.translator.translate('delete_file_forever', 'Удалить файл навсегда'))

    def compress_file(self):
        if not os.path.exists(self.filepath):
            return
        ffmpeg_path = self.parent_tab.parent_window.ffmpeg_path
        dialog = VideoCompressDialog(self.filepath, ffmpeg_path, self.translator, self)
        if dialog.exec():
            self.parent_tab.load_files()

    def extract_audio(self):
        if not os.path.exists(self.filepath):
            return
        ffmpeg_path = getattr(self.parent_tab.parent_window, 'ffmpeg_path', None)
        if not ffmpeg_path:
            return
        dialog = AudioConvertDialog(self.filepath, ffmpeg_path, self.translator, self)
        if dialog.exec():
            self.parent_tab.load_files()

    def show_media_info(self):
        if not os.path.exists(self.filepath):
            return
        parent_win = self.parent_tab.parent_window
        ffprobe_path = getattr(parent_win, 'ffprobe_path', None)
        if not ffprobe_path and hasattr(parent_win, 'ffmpeg_path') and parent_win.ffmpeg_path:
            ffprobe_path = os.path.join(os.path.dirname(parent_win.ffmpeg_path), 'ffprobe.exe' if os.name == 'nt' else 'ffprobe')
        if not ffprobe_path or not os.path.exists(ffprobe_path):
            QMessageBox.warning(self, "Ошибка", "FFprobe не найден в системе.")
            return
        dialog = MediaInfoDialog(self.filepath, ffprobe_path, self.translator, self)
        dialog.exec()

    def cut_file(self):
        if not os.path.exists(self.filepath):
            QMessageBox.warning(self, self.translator.translate('error', 'Ошибка'),
                                self.translator.translate('file_not_exists', 'Файл больше не существует.'))
            return

        ffmpeg_path = self.parent_tab.parent_window.ffmpeg_path
        dialog = VideoCutterDialog(self.filepath, ffmpeg_path, self)
        if dialog.exec():
            self.parent_tab.load_files()

    def load_thumbnail(self):
        ffmpeg_path = self.parent_tab.parent_window.ffmpeg_path
        worker = LocalThumbWorker(self.filepath, ffmpeg_path)
        worker.signals.loaded.connect(self.set_thumbnail)
        self.parent_tab.parent_window.thread_pool.start(worker)

    def set_thumbnail(self, image_or_pixmap):
        if isinstance(image_or_pixmap, QImage):
            pixmap = QPixmap.fromImage(image_or_pixmap)
        elif isinstance(image_or_pixmap, QPixmap):
            pixmap = image_or_pixmap
        else:
            return
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

    def preview_file(self):
        if not os.path.exists(self.filepath):
            QMessageBox.warning(self, self.translator.translate('error', 'Ошибка'),
                                self.translator.translate('file_not_exists', 'Файл больше не существует.'))
            return
        ffmpeg_path = getattr(self.parent_tab.parent_window, 'ffmpeg_path', None)
        dialog = VideoPreviewDialog(self.filepath, ffmpeg_path=ffmpeg_path, translator=self.translator, parent=self.parent_tab.parent_window)
        dialog.exec()

    def open_file(self):
        self.preview_file()

    def open_file_external(self):
        if os.path.exists(self.filepath):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.filepath))

    def open_folder(self):
        if os.path.exists(self.filepath):
            folder = os.path.dirname(self.filepath)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def delete_file(self):
        filename = os.path.basename(self.filepath)
        reply = QMessageBox.question(self, 'Удаление файла', f'Вы уверены, что хотите удалить файл:\n{filename}?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self.filepath)
                self.parent_tab.load_files()
            except Exception as e:
                QMessageBox.warning(self, 'Ошибка', f'Не удалось удалить файл:\n{str(e)}')


class VideoPreviewDialog(QDialog):
    """
    Встроенный быстрый медиаплеер Fluent UI для мгновенного предпросмотра
    скачанных видео и аудио прямо в приложении.
    """
    def __init__(self, filepath, ffmpeg_path=None, translator=None, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.ffmpeg_path = ffmpeg_path
        self.translator = translator
        self.is_muted = False
        self.last_volume = 70
        self.initUI()
        self.init_player()

    def initUI(self):
        filename = os.path.basename(self.filepath)
        self.setWindowTitle(f"Быстрый просмотр: {filename}")
        self.setMinimumSize(820, 560)
        self.resize(880, 580)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        # 1. Экран видео
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: #0c0c0c; border-radius: 8px;")
        self.video_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.video_widget, stretch=1)

        # 2. Ползунок позиции
        self.slider = Slider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self.set_position)
        layout.addWidget(self.slider)

        # 3. Панель управления воспроизведением
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        self.btn_play = PrimaryPushButton(FluentIcon.PLAY, "Пауза")
        self.btn_play.setFixedHeight(34)
        self.btn_play.clicked.connect(self.toggle_play)
        controls_layout.addWidget(self.btn_play)

        self.btn_rewind = TransparentToolButton(FluentIcon.LEFT_ARROW)
        self.btn_rewind.setToolTip("Назад на 5 секунд (Стрелка влево)")
        self.btn_rewind.setFixedSize(34, 34)
        self.btn_rewind.clicked.connect(lambda: self.seek_relative(-5000))
        controls_layout.addWidget(self.btn_rewind)

        self.btn_forward = TransparentToolButton(FluentIcon.RIGHT_ARROW)
        self.btn_forward.setToolTip("Вперед на 5 секунд (Стрелка вправо)")
        self.btn_forward.setFixedSize(34, 34)
        self.btn_forward.clicked.connect(lambda: self.seek_relative(5000))
        controls_layout.addWidget(self.btn_forward)

        self.lbl_time = BodyLabel("00:00:00 / 00:00:00")
        self.lbl_time.setStyleSheet("color: #cccccc; font-family: monospace; font-size: 13px;")
        controls_layout.addWidget(self.lbl_time)

        controls_layout.addStretch()

        # Выбор скорости
        self.speed_combo = ComboBox()
        self.speed_combo.setFixedWidth(85)
        self.speed_combo.addItem("0.5x", userData=0.5)
        self.speed_combo.addItem("0.75x", userData=0.75)
        self.speed_combo.addItem("1.0x", userData=1.0)
        self.speed_combo.addItem("1.25x", userData=1.25)
        self.speed_combo.addItem("1.5x", userData=1.5)
        self.speed_combo.addItem("2.0x", userData=2.0)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.currentIndexChanged.connect(self.on_speed_changed)
        controls_layout.addWidget(self.speed_combo)

        # Звук и громкость
        self.btn_mute = TransparentToolButton(FluentIcon.VOLUME)
        self.btn_mute.setFixedSize(34, 34)
        self.btn_mute.clicked.connect(self.toggle_mute)
        controls_layout.addWidget(self.btn_mute)

        self.volume_slider = Slider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.valueChanged.connect(self.set_volume)
        controls_layout.addWidget(self.volume_slider)

        # Полноэкранный режим
        self.btn_fs = TransparentToolButton(FluentIcon.ZOOM)
        self.btn_fs.setToolTip("Полноэкранный режим (F / Esc)")
        self.btn_fs.setFixedSize(34, 34)
        self.btn_fs.clicked.connect(self.toggle_fullscreen)
        controls_layout.addWidget(self.btn_fs)

        layout.addLayout(controls_layout)

        # 4. Панель дополнительных действий
        tools_layout = QHBoxLayout()
        tools_layout.setSpacing(10)

        self.btn_ext_player = PushButton(FluentIcon.SHARE, "В системном плеере")
        self.btn_ext_player.clicked.connect(self.open_external)
        tools_layout.addWidget(self.btn_ext_player)

        if self.ffmpeg_path:
            self.btn_cut = PushButton(FluentIcon.CUT, "Обрезать / GIF...")
            self.btn_cut.clicked.connect(self.open_cut)
            tools_layout.addWidget(self.btn_cut)

        tools_layout.addStretch()

        self.btn_close = PushButton("Закрыть")
        self.btn_close.clicked.connect(self.close)
        tools_layout.addWidget(self.btn_close)

        layout.addLayout(tools_layout)

    def init_player(self):
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(0.7)

        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)
        self.media_player.playbackStateChanged.connect(self.playback_state_changed)

        self.media_player.setSource(QUrl.fromLocalFile(self.filepath))
        self.media_player.play()

    def playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText("Пауза")
            self.btn_play.setIcon(FluentIcon.PAUSE.icon())
        else:
            self.btn_play.setText("Играть")
            self.btn_play.setIcon(FluentIcon.PLAY.icon())

    def toggle_play(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def seek_relative(self, delta_ms):
        dur = max(self.media_player.duration(), 0)
        new_pos = max(0, min(dur, self.media_player.position() + delta_ms))
        self.media_player.setPosition(new_pos)

    def position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.update_time_label()

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label()

    def set_position(self, position):
        self.media_player.setPosition(position)

    def on_speed_changed(self):
        rate = float(self.speed_combo.currentData() or 1.0)
        self.media_player.setPlaybackRate(rate)

    def set_volume(self, value):
        self.audio_output.setVolume(value / 100.0)
        if value > 0:
            self.is_muted = False
            self.btn_mute.setIcon(FluentIcon.VOLUME.icon())
        else:
            self.is_muted = True
            self.btn_mute.setIcon(FluentIcon.MUTE.icon())

    def toggle_mute(self):
        if self.is_muted:
            self.volume_slider.setValue(self.last_volume if self.last_volume > 0 else 70)
        else:
            self.last_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def update_time_label(self):
        pos = self.format_time(self.media_player.position())
        dur = self.format_time(self.media_player.duration())
        self.lbl_time.setText(f"{pos} / {dur}")

    def format_time(self, ms):
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def open_external(self):
        self.media_player.pause()
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.filepath))

    def open_cut(self):
        self.media_player.pause()
        if self.ffmpeg_path:
            dialog = VideoCutterDialog(self.filepath, self.ffmpeg_path, self)
            dialog.exec()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_play()
        elif key == Qt.Key.Key_Left:
            self.seek_relative(-5000)
        elif key == Qt.Key.Key_Right:
            self.seek_relative(5000)
        elif key == Qt.Key.Key_Up:
            self.volume_slider.setValue(min(100, self.volume_slider.value() + 5))
        elif key == Qt.Key.Key_Down:
            self.volume_slider.setValue(max(0, self.volume_slider.value() - 5))
        elif key == Qt.Key.Key_M:
            self.toggle_mute()
        elif key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        super().closeEvent(event)


class VideoCompressDialog(QDialog):
    def __init__(self, filepath, ffmpeg_path, translator=None, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.ffmpeg_path = ffmpeg_path
        self.translator = translator
        self.setWindowTitle("Сжатие видео для мессенджеров")
        self.setMinimumWidth(440)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        filename = os.path.basename(self.filepath)
        file_size_mb = os.path.getsize(self.filepath) / (1024 * 1024) if os.path.exists(self.filepath) else 0

        title = StrongBodyLabel(filename)
        title.setWordWrap(True)
        layout.addWidget(title)

        curr_size = CaptionLabel(f"Текущий размер файла: {file_size_mb:.1f} МБ")
        curr_size.setStyleSheet("color: #29b6f6; font-weight: bold;")
        layout.addWidget(curr_size)

        lbl_mode = BodyLabel("Выберите профиль сжатия:")
        layout.addWidget(lbl_mode)

        self.combo_preset = ComboBox()
        self.combo_preset.addItem("Для Discord / Telegram (< 25 МБ)", userData="telegram_25")
        self.combo_preset.addItem("Средний размер (< 50 МБ)", userData="medium_50")
        self.combo_preset.addItem("Сбалансированное качество (CRF 28, 720p)", userData="crf_28")
        self.combo_preset.addItem("Максимальное сжатие (CRF 34, 480p)", userData="crf_34")
        layout.addWidget(self.combo_preset)

        norm_box = QHBoxLayout()
        lbl_norm = BodyLabel("Нормализовать звук (EBU R128):")
        self.switch_norm = SwitchButton()
        self.switch_norm.setOnText("Вкл")
        self.switch_norm.setOffText("Выкл")
        norm_box.addWidget(lbl_norm)
        norm_box.addStretch()
        norm_box.addWidget(self.switch_norm)
        layout.addLayout(norm_box)

        btn_box = QHBoxLayout()
        self.btn_compress = PrimaryPushButton(FluentIcon.SAVE, "Сжать видео")
        self.btn_compress.clicked.connect(self.process_compress)
        self.btn_cancel = PushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)

        btn_box.addStretch()
        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(self.btn_compress)
        layout.addLayout(btn_box)

    def process_compress(self):
        preset = self.combo_preset.currentData()
        base, _ = os.path.splitext(self.filepath)
        out_path = f"{base}_compressed.mp4"

        vf = 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
        crf = '28'

        if preset == 'telegram_25':
            vf = 'scale=trunc(min(1280\\,iw)/2)*2:-2'
            crf = '30'
        elif preset == 'medium_50':
            vf = 'scale=trunc(min(1280\\,iw)/2)*2:-2'
            crf = '27'
        elif preset == 'crf_28':
            vf = 'scale=trunc(min(1280\\,iw)/2)*2:-2'
            crf = '28'
        elif preset == 'crf_34':
            vf = 'scale=trunc(min(854\\,iw)/2)*2:-2'
            crf = '34'

        cmd = [
            self.ffmpeg_path, '-y',
            '-fflags', '+genpts+discardcorrupt',
            '-err_detect', 'ignore_err',
            '-max_error_rate', '1.0',
            '-i', self.filepath,
            '-vf', vf,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', crf,
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '128k',
        ]
        if hasattr(self, 'switch_norm') and self.switch_norm.isChecked():
            cmd.extend(['-af', 'loudnorm=I=-16:TP=-1.5:LRA=11'])
        cmd.extend(['-movflags', '+faststart', out_path])

        self.btn_compress.setText("Сжимаем (в фоне)...")
        self.btn_compress.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.combo_preset.setEnabled(False)

        worker = CutWorker(cmd, out_path)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_finished(self, out_path):
        new_size_mb = os.path.getsize(out_path) / (1024 * 1024) if os.path.exists(out_path) else 0
        QMessageBox.information(
            self, "Успех",
            f"Видео успешно сжато!\nНовый размер: {new_size_mb:.1f} МБ\nФайл:\n{os.path.basename(out_path)}"
        )
        self.accept()

    def _on_error(self, err):
        QMessageBox.critical(self, "Ошибка сжатия", f"Сбой FFmpeg:\n{err}")
        self.btn_compress.setText("Сжать видео")
        self.btn_compress.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.combo_preset.setEnabled(True)


class VideoCutterDialog(QDialog):
    def __init__(self, filepath, ffmpeg_path, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.ffmpeg_path = ffmpeg_path
        self.initUI()
        self.init_player()

    def initUI(self):
        self.setWindowTitle("Визуальная обрезка видео")
        self.setMinimumSize(760, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(15)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black; border-radius: 8px;")
        layout.addWidget(self.video_widget, stretch=1)

        self.slider = Slider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self.set_position)
        layout.addWidget(self.slider)

        controls_layout = QHBoxLayout()
        self.btn_play = PushButton(FluentIcon.PLAY, "Play / Pause")
        self.btn_play.clicked.connect(self.toggle_play)

        self.lbl_time = BodyLabel("00:00:00 / 00:00:00")

        self.btn_mute = TransparentToolButton(FluentIcon.VOLUME)
        self.btn_mute.setFixedSize(32, 32)
        self.btn_mute.clicked.connect(self.toggle_mute)

        self.volume_slider = Slider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.set_volume)

        controls_layout.addWidget(self.btn_play)
        controls_layout.addSpacing(15)
        controls_layout.addWidget(self.lbl_time)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_mute)
        controls_layout.addWidget(self.volume_slider)
        layout.addLayout(controls_layout)

        times_layout = QHBoxLayout()

        self.btn_set_start = PushButton(FluentIcon.LEFT_ARROW, "Начать отсюда")
        self.btn_set_start.clicked.connect(self.set_start_time)

        self.start_input = LineEdit()
        self.start_input.setText("00:00:00")
        self.start_input.setFixedWidth(110)
        self.start_input.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_set_end = PushButton(FluentIcon.RIGHT_ARROW, "Закончить здесь")
        self.btn_set_end.clicked.connect(self.set_end_time)

        self.end_input = LineEdit()
        self.end_input.setText("00:00:00")
        self.end_input.setFixedWidth(110)
        self.end_input.setAlignment(Qt.AlignmentFlag.AlignCenter)

        times_layout.addWidget(self.btn_set_start)
        times_layout.addWidget(self.start_input)
        times_layout.addStretch()
        times_layout.addWidget(self.end_input)
        times_layout.addWidget(self.btn_set_end)
        layout.addLayout(times_layout)

        btn_layout = QHBoxLayout()

        self.btn_gif = PushButton(FluentIcon.PHOTO, "Создать GIF")
        self.btn_gif.clicked.connect(self.process_gif)

        self.btn_cut = PrimaryPushButton(FluentIcon.CUT, "Обрезать и сохранить")
        self.btn_cut.clicked.connect(self.process_cut)

        self.btn_cancel = PushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_gif)
        btn_layout.addWidget(self.btn_cut)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def init_player(self):
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()

        self.audio_output.setVolume(0.5)

        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)

        self.media_player.setSource(QUrl.fromLocalFile(self.filepath))

        self.is_muted = False
        self.last_volume = 50

    def set_volume(self, value):
        volume = value / 100.0
        self.audio_output.setVolume(volume)
        if value > 0:
            self.is_muted = False
            self.btn_mute.setIcon(FluentIcon.VOLUME.icon())
        else:
            self.is_muted = True
            self.btn_mute.setIcon(FluentIcon.MUTE.icon())

    def toggle_mute(self):
        if self.is_muted:
            self.volume_slider.setValue(self.last_volume if self.last_volume > 0 else 50)
        else:
            self.last_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)

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
        if self.end_input.text() in ("00:00:00", "") and duration > 0:
            self.end_input.setText(self.format_time(duration))

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
        self.media_player.pause()
        start_time = self.start_input.text().strip()
        end_time = self.end_input.text().strip()

        if start_time == end_time:
            QMessageBox.warning(self, "Предупреждение", "Время начала и окончания совпадают. Пожалуйста, укажите отрезок для обрезки видео.")
            return

        base, ext = os.path.splitext(self.filepath)
        out_path = f"{base}_cut.mp4"

        cmd = [
            self.ffmpeg_path, '-y',
            '-fflags', '+genpts+discardcorrupt',
            '-err_detect', 'ignore_err',
            '-max_error_rate', '1.0',
            '-ss', start_time,
            '-to', end_time,
            '-i', self.filepath,
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '22',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-movflags', '+faststart',
            out_path
        ]

        self.btn_cut.setText("Режем (в фоне)...")
        self.btn_cut.setEnabled(False)
        self.btn_gif.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.start_input.setEnabled(False)
        self.end_input.setEnabled(False)

        worker = CutWorker(cmd, out_path)
        worker.signals.finished.connect(self._on_cut_finished)
        worker.signals.error.connect(self._on_cut_error)
        QThreadPool.globalInstance().start(worker)

    def _on_cut_finished(self, out_path):
        QMessageBox.information(self, "Успех", f"Видео обрезано и сохранено!\nФайл:\n{os.path.basename(out_path)}")
        self.media_player.setSource(QUrl())
        self.accept()

    def process_gif(self):
        self.media_player.pause()
        start_time = self.start_input.text().strip()
        end_time = self.end_input.text().strip()

        if start_time == end_time:
            QMessageBox.warning(self, "Предупреждение", "Время начала и окончания совпадают. Пожалуйста, укажите отрезок для создания GIF.")
            return

        base, _ = os.path.splitext(self.filepath)
        out_path = f"{base}_clip.gif"

        cmd = [
            self.ffmpeg_path, '-y',
            '-ss', start_time,
            '-to', end_time,
            '-i', self.filepath,
            '-vf', 'fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse',
            out_path
        ]

        self.btn_gif.setText("Создаем GIF...")
        self.btn_gif.setEnabled(False)
        self.btn_cut.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.start_input.setEnabled(False)
        self.end_input.setEnabled(False)

        worker = CutWorker(cmd, out_path)
        worker.signals.finished.connect(self._on_gif_finished)
        worker.signals.error.connect(self._on_cut_error)
        QThreadPool.globalInstance().start(worker)

    def _on_gif_finished(self, out_path):
        QMessageBox.information(self, "Успех", f"GIF успешно создан и сохранен!\nФайл:\n{os.path.basename(out_path)}")
        self.media_player.setSource(QUrl())
        self.accept()

    def _on_cut_error(self, err_msg):
        self.btn_cut.setText("Обрезать и сохранить")
        self.btn_cut.setEnabled(True)
        self.btn_gif.setText("Создать GIF")
        self.btn_gif.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.start_input.setEnabled(True)
        self.end_input.setEnabled(True)
        QMessageBox.critical(self, "Ошибка обработки", f"Сбой FFmpeg при нарезке видео:\n{err_msg}")

    def closeEvent(self, event):
        self.media_player.setSource(QUrl())
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
        self.files_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.files_list)

        self.update_translations()

    def _on_item_double_clicked(self, item):
        widget = self.files_list.itemWidget(item)
        if hasattr(widget, 'preview_file'):
            widget.preview_file()

    def load_files(self):
        self.files_list.clear()
        folder = self.parent_window.settings.value('save_path', '')

        if not folder or not os.path.isdir(folder):
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            folder = os.path.join(base_dir, 'downloads')

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