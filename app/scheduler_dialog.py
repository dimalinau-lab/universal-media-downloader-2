import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QMessageBox, QFrame
)
from PyQt6.QtCore import QTime
from qfluentwidgets import (
    PrimaryPushButton, PushButton, RadioButton,
    ComboBox, StrongBodyLabel, BodyLabel, CaptionLabel,
    FluentIcon, TimePicker
)
from qfluentwidgets.components.date_time.time_picker import MiniuteFormatter


class SchedulerDialog(QDialog):
    """
    Диалог настройки отложенного запуска очереди загрузок (Ночной режим).
    Позволяет назначить автозапуск через N часов/минут или в заданное время,
    а также выбрать действие по завершению (выключение ПК / сон).
    """
    def __init__(self, current_schedule: dict | None, translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.current_schedule = current_schedule or {}
        self.result_schedule = None

        self.setWindowTitle(self.translator.translate('scheduler_title', "Планировщик загрузок"))
        self.setFixedSize(510, 420)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        # Шапка
        header_layout = QVBoxLayout()
        header_layout.setSpacing(3)
        title = StrongBodyLabel(self.translator.translate('scheduler_header', "Автозапуск очереди по таймеру"))
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        desc = CaptionLabel(self.translator.translate(
            'scheduler_desc',
            "Автоматический запуск очереди в заданное время."
        ))
        desc.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        layout.addLayout(header_layout)

        card_qss = """
            QFrame#SchedulerCard {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """

        # Карточка 1: Выбор времени старта
        self.card_time = QFrame()
        self.card_time.setObjectName("SchedulerCard")
        self.card_time.setStyleSheet(card_qss)
        card_time_layout = QVBoxLayout(self.card_time)
        card_time_layout.setContentsMargins(16, 14, 16, 14)
        card_time_layout.setSpacing(12)

        # Режим 1: Через интервал
        self.rb_interval = RadioButton(self.translator.translate('sched_mode_delay', "Через указанное время:"))
        card_time_layout.addWidget(self.rb_interval)

        interval_row = QHBoxLayout()
        interval_row.setContentsMargins(28, 0, 0, 0)
        interval_row.setSpacing(10)

        self.combo_hours = ComboBox()
        self.combo_hours.setFixedHeight(32)
        self.combo_hours.setFixedWidth(130)
        saved_h = self.current_schedule.get('delay_hours', 1)
        h_suffix = self.translator.translate('hours_short', "ч.")
        for h in range(25):
            self.combo_hours.addItem(f"{h} {h_suffix}", userData=h)
        for i in range(self.combo_hours.count()):
            if self.combo_hours.itemData(i) == saved_h:
                self.combo_hours.setCurrentIndex(i)
                break

        self.combo_minutes = ComboBox()
        self.combo_minutes.setFixedHeight(32)
        self.combo_minutes.setFixedWidth(130)
        saved_m = self.current_schedule.get('delay_minutes', 0)
        m_suffix = self.translator.translate('minutes_short', "мин.")
        for m in range(60):
            self.combo_minutes.addItem(f"{m} {m_suffix}", userData=m)
        for i in range(self.combo_minutes.count()):
            if self.combo_minutes.itemData(i) == saved_m:
                self.combo_minutes.setCurrentIndex(i)
                break

        interval_row.addWidget(self.combo_hours)
        interval_row.addWidget(self.combo_minutes)
        interval_row.addStretch()
        card_time_layout.addLayout(interval_row)

        # Разделитель между опциями
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.06); max-height: 1px;")
        card_time_layout.addWidget(sep)

        # Режим 2: В точное время суток
        self.rb_exact = RadioButton(self.translator.translate('sched_mode_exact', "В точное время (сегодня / завтра):"))
        card_time_layout.addWidget(self.rb_exact)

        exact_row = QHBoxLayout()
        exact_row.setContentsMargins(28, 0, 0, 0)
        exact_row.setSpacing(10)

        self.time_picker = TimePicker(self, showSeconds=False)
        self.time_picker.setColumnFormatter(0, MiniuteFormatter())
        self.time_picker.columns[0].setFixedWidth(135)
        self.time_picker.columns[1].setFixedWidth(135)
        self.time_picker.setFixedWidth(270)
        self.time_picker.setFixedHeight(32)
        now_time = QTime.currentTime()
        default_target = now_time.addSecs(3600 * 2)
        saved_target = self.current_schedule.get('target_time')
        if saved_target:
            self.time_picker.setTime(QTime.fromString(saved_target, "HH:mm"))
        else:
            self.time_picker.setTime(default_target)

        exact_row.addWidget(self.time_picker)
        exact_row.addStretch()
        card_time_layout.addLayout(exact_row)

        layout.addWidget(self.card_time)

        # Переключение активности радио-кнопок
        is_exact = self.current_schedule.get('mode') == 'exact'
        self.rb_exact.setChecked(is_exact)
        self.rb_interval.setChecked(not is_exact)

        self.rb_interval.toggled.connect(self._update_input_states)
        self.rb_exact.toggled.connect(self._update_input_states)
        self._update_input_states()

        # Карточка 2: Действие после окончания очереди
        self.card_action = QFrame()
        self.card_action.setObjectName("SchedulerCard")
        self.card_action.setStyleSheet(card_qss)
        card_action_layout = QHBoxLayout(self.card_action)
        card_action_layout.setContentsMargins(16, 12, 16, 12)
        card_action_layout.setSpacing(10)

        lbl_post = BodyLabel(self.translator.translate('sched_on_finish', "После окончания загрузок:"))
        self.combo_post = ComboBox()
        self.combo_post.setMinimumWidth(210)
        self.combo_post.setFixedHeight(32)
        self.combo_post.addItem(self.translator.translate('sched_action_none', "Ничего не делать"), userData="none")
        self.combo_post.addItem(self.translator.translate('sched_action_shutdown', "Выключить ПК"), userData="shutdown")
        self.combo_post.addItem(self.translator.translate('sched_action_sleep', "Перевести в спящий режим"), userData="sleep")
        self.combo_post.addItem(self.translator.translate('sched_action_exit', "Закрыть программу"), userData="exit_app")

        saved_action = self.current_schedule.get('action', 'none')
        for i in range(self.combo_post.count()):
            if self.combo_post.itemData(i) == saved_action:
                self.combo_post.setCurrentIndex(i)
                break

        card_action_layout.addWidget(lbl_post)
        card_action_layout.addStretch()
        card_action_layout.addWidget(self.combo_post)
        layout.addWidget(self.card_action)

        # Нижняя панель
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        if self.current_schedule.get('active'):
            self.btn_disable = PushButton(
                FluentIcon.CANCEL,
                self.translator.translate('cancel_schedule', "Отменить расписание")
            )
            self.btn_disable.setFixedHeight(32)
            self.btn_disable.setStyleSheet("color: #d32f2f;")
            self.btn_disable.clicked.connect(self._on_disable_clicked)
            bottom_layout.addWidget(self.btn_disable)

        bottom_layout.addStretch()

        self.btn_cancel = PushButton(self.translator.translate('cancel_action', "Закрыть"))
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_apply = PrimaryPushButton(
            FluentIcon.ACCEPT,
            self.translator.translate('activate_scheduler', "Активировать таймер")
        )
        self.btn_apply.setFixedHeight(32)
        self.btn_apply.clicked.connect(self._on_apply)

        bottom_layout.addWidget(self.btn_cancel)
        bottom_layout.addWidget(self.btn_apply)
        layout.addLayout(bottom_layout)

    def _update_input_states(self):
        use_interval = self.rb_interval.isChecked()
        self.combo_hours.setEnabled(use_interval)
        self.combo_minutes.setEnabled(use_interval)
        self.time_picker.setEnabled(not use_interval)

    def _on_disable_clicked(self):
        self.result_schedule = {'active': False}
        self.accept()

    def _on_apply(self):
        now = datetime.datetime.now()
        h = int(self.combo_hours.currentData() or 0)
        m = int(self.combo_minutes.currentData() or 0)

        if self.rb_interval.isChecked():
            total_seconds = h * 3600 + m * 60
            if total_seconds <= 0:
                QMessageBox.warning(
                    self,
                    self.translator.translate('warning', "Предупреждение"),
                    self.translator.translate('invalid_interval', "Укажите ненулевое время запуска.")
                )
                return
            target_dt = now + datetime.timedelta(seconds=total_seconds)
            mode = 'delay'
            target_time_str = target_dt.strftime("%H:%M:%S")
        else:
            qtime = self.time_picker.getTime()
            target_dt = now.replace(hour=qtime.hour(), minute=qtime.minute(), second=0, microsecond=0)
            if target_dt <= now:
                target_dt += datetime.timedelta(days=1)
            mode = 'exact'
            target_time_str = target_dt.strftime("%H:%M:%S")

        self.result_schedule = {
            'active': True,
            'mode': mode,
            'target_timestamp': target_dt.timestamp(),
            'target_time_str': target_time_str,
            'delay_hours': h,
            'delay_minutes': m,
            'target_time': self.time_picker.getTime().toString("HH:mm"),
            'action': self.combo_post.currentData()
        }
        self.accept()
