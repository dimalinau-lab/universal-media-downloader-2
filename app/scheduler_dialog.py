import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QTimeEdit, QLabel, QMessageBox
)
from PyQt6.QtCore import Qt, QTime
from qfluentwidgets import (
    PrimaryPushButton, PushButton, RadioButton,
    SpinBox, ComboBox, StrongBodyLabel, BodyLabel, CaptionLabel,
    FluentIcon
)


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

        self.setWindowTitle(self.translator.translate('scheduler_title', "Планировщик загрузок (Ночной режим)"))
        self.setFixedSize(500, 420)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Шапка
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        title = StrongBodyLabel(self.translator.translate('scheduler_header', "Автозапуск очереди по таймеру"))
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        desc = CaptionLabel(self.translator.translate(
            'scheduler_desc',
            "Настройте старт скачивания в часы наименьшей нагрузки на сеть или ночью."
        ))
        desc.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        layout.addLayout(header_layout)

        # Режим 1: Через интервал
        self.rb_interval = RadioButton(self.translator.translate('sched_mode_delay', "Запустить через указанное время:"))
        layout.addWidget(self.rb_interval)

        interval_container = QWidget()
        ic_layout = QHBoxLayout(interval_container)
        ic_layout.setContentsMargins(28, 0, 0, 0)
        ic_layout.setSpacing(10)

        self.spin_hours = SpinBox()
        self.spin_hours.setRange(0, 72)
        self.spin_hours.setValue(self.current_schedule.get('delay_hours', 1))
        self.spin_hours.setFixedWidth(140)

        self.spin_minutes = SpinBox()
        self.spin_minutes.setRange(0, 59)
        self.spin_minutes.setValue(self.current_schedule.get('delay_minutes', 0))
        self.spin_minutes.setFixedWidth(140)

        ic_layout.addWidget(self.spin_hours)
        ic_layout.addWidget(BodyLabel(self.translator.translate('hours_short', "ч.")))
        ic_layout.addSpacing(20)
        ic_layout.addWidget(self.spin_minutes)
        ic_layout.addWidget(BodyLabel(self.translator.translate('minutes_short', "мин.")))
        ic_layout.addStretch()
        layout.addWidget(interval_container)

        # Режим 2: В точное время суток
        self.rb_exact = RadioButton(self.translator.translate('sched_mode_exact', "Запустить в точное время (сегодня / завтра):"))
        layout.addWidget(self.rb_exact)

        exact_container = QWidget()
        ec_layout = QHBoxLayout(exact_container)
        ec_layout.setContentsMargins(28, 0, 0, 0)
        ec_layout.setSpacing(10)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        now_time = QTime.currentTime()
        default_target = now_time.addSecs(3600 * 2)  # +2 часа по умолчанию
        saved_target = self.current_schedule.get('target_time')
        if saved_target:
            self.time_edit.setTime(QTime.fromString(saved_target, "HH:mm"))
        else:
            self.time_edit.setTime(default_target)
        self.time_edit.setFixedWidth(135)
        self.time_edit.setStyleSheet("font-size: 13px; font-weight: bold; padding: 2px 6px;")

        ec_layout.addWidget(self.time_edit)
        ec_layout.addStretch()
        layout.addWidget(exact_container)

        # Переключение активности радио-кнопок
        is_exact = self.current_schedule.get('mode') == 'exact'
        self.rb_exact.setChecked(is_exact)
        self.rb_interval.setChecked(not is_exact)

        self.rb_interval.toggled.connect(self._update_input_states)
        self.rb_exact.toggled.connect(self._update_input_states)
        self._update_input_states()

        # Действие после окончания очереди
        post_box = QHBoxLayout()
        post_box.setSpacing(10)
        lbl_post = BodyLabel(self.translator.translate('sched_on_finish', "После окончания загрузок:"))
        self.combo_post = ComboBox()
        self.combo_post.setMinimumWidth(220)
        self.combo_post.addItem(self.translator.translate('sched_action_none', "Ничего не делать"), userData="none")
        self.combo_post.addItem(self.translator.translate('sched_action_shutdown', "Выключить ПК"), userData="shutdown")
        self.combo_post.addItem(self.translator.translate('sched_action_sleep', "Перевести в спящий режим"), userData="sleep")
        self.combo_post.addItem(self.translator.translate('sched_action_exit', "Закрыть программу"), userData="exit_app")

        saved_action = self.current_schedule.get('action', 'none')
        for i in range(self.combo_post.count()):
            if self.combo_post.itemData(i) == saved_action:
                self.combo_post.setCurrentIndex(i)
                break

        post_box.addWidget(lbl_post)
        post_box.addWidget(self.combo_post)
        post_box.addStretch()
        layout.addLayout(post_box)

        # Нижняя панель
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        if self.current_schedule.get('active'):
            self.btn_disable = PushButton(
                FluentIcon.CANCEL,
                self.translator.translate('cancel_schedule', "Отменить расписание")
            )
            self.btn_disable.setStyleSheet("color: #d32f2f;")
            self.btn_disable.clicked.connect(self._on_disable_clicked)
            bottom_layout.addWidget(self.btn_disable)

        bottom_layout.addStretch()

        self.btn_cancel = PushButton(self.translator.translate('cancel_action', "Закрыть"))
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_apply = PrimaryPushButton(
            FluentIcon.ACCEPT,
            self.translator.translate('activate_scheduler', "Активировать таймер")
        )
        self.btn_apply.clicked.connect(self._on_apply)

        bottom_layout.addWidget(self.btn_cancel)
        bottom_layout.addWidget(self.btn_apply)
        layout.addLayout(bottom_layout)

    def _update_input_states(self):
        use_interval = self.rb_interval.isChecked()
        self.spin_hours.setEnabled(use_interval)
        self.spin_minutes.setEnabled(use_interval)
        self.time_edit.setEnabled(not use_interval)

    def _on_disable_clicked(self):
        self.result_schedule = {'active': False}
        self.accept()

    def _on_apply(self):
        now = datetime.datetime.now()
        if self.rb_interval.isChecked():
            h = self.spin_hours.value()
            m = self.spin_minutes.value()
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
        else:
            qtime = self.time_edit.time()
            target_dt = now.replace(hour=qtime.hour(), minute=qtime.minute(), second=0, microsecond=0)
            if target_dt <= now:
                target_dt += datetime.timedelta(days=1)
            total_seconds = int((target_dt - now).total_seconds())
            mode = 'exact'

        self.result_schedule = {
            'active': True,
            'mode': mode,
            'target_timestamp': target_dt.timestamp(),
            'target_time_str': target_dt.strftime("%H:%M:%S"),
            'delay_hours': self.spin_hours.value(),
            'delay_minutes': self.spin_minutes.value(),
            'target_time': self.time_edit.time().toString("HH:mm"),
            'action': self.combo_post.currentData()
        }
        self.accept()
