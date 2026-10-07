import os
import re
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QFrame, QPushButton, QWidget, QPlainTextEdit)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QCursor
from qfluentwidgets import (ProgressBar, PrimaryPushButton, PushButton,
                            SubtitleLabel, BodyLabel, CaptionLabel,
                            StrongBodyLabel, FluentIcon, IconWidget,
                            TransparentPushButton)


def format_kinopub_error(raw_error: str) -> dict:
    """
    Разбирает сырые ошибки Selenium / WebDriver / сети и преобразует их
    в понятный человеку формат.
    """
    err_str = str(raw_error)

    # 1. Выделяем сетевой код net::ERR_...
    net_err_match = re.search(r'net::(ERR_[A-Z0-9_]+)', err_str)
    net_code = net_err_match.group(1) if net_err_match else None

    # 2. Выделяем читабельную часть сообщения (без стектрейса драйвера)
    clean_msg = err_str
    if "Stacktrace:" in clean_msg:
        clean_msg = clean_msg.split("Stacktrace:")[0].strip()
    if "Message:" in clean_msg:
        clean_msg = clean_msg.split("Message:")[-1].strip()
    if "(Session info:" in clean_msg:
        clean_msg = clean_msg.split("(Session info:")[0].strip()
    clean_msg = re.sub(r'\s+', ' ', clean_msg).strip()

    # По умолчанию
    title = "Не удалось получить данные о видео"
    description = "Сайт не отвечает или соединение заблокировано."
    solution = (
        "• Включите VPN (или средство обхода блокировок DPI).\n"
        "• Проверьте, открывается ли ссылка в обычном браузере.\n"
        "• Нажмите «Повторить»."
    )
    short_status = "Ошибка подключения к сайту"

    if net_code == "ERR_CONNECTION_RESET":
        title = "Доступ заблокирован провайдером"
        description = (
            "Соединение сброшено (net::ERR_CONNECTION_RESET).\n"
            "Сайты KinoPub и Rezka блокируются большинством провайдеров РФ."
        )
        solution = (
            "• Включите VPN или утилиту обхода блокировок (GoodbyeDPI / zapret).\n"
            "• Либо откройте сайт через VPN в браузере и скопируйте рабочее зеркало.\n"
            "• После включения VPN нажмите «Повторить» ниже."
        )
        short_status = "Сайт заблокирован провайдером (ERR_CONNECTION_RESET). Нужен VPN."

    elif net_code == "ERR_NAME_NOT_RESOLVED":
        title = "Адрес сайта не найден (DNS ошибка)"
        description = (
            "Не удалось определить IP-адрес сайта (net::ERR_NAME_NOT_RESOLVED).\n"
            "Домен заблокирован на уровне DNS или ссылка устарела."
        )
        solution = (
            "• Включите VPN или настройте публичные DNS (1.1.1.1 или 8.8.8.8).\n"
            "• Проверьте правильность ссылки."
        )
        short_status = "DNS ошибка: сайт не найден (ERR_NAME_NOT_RESOLVED)."

    elif net_code in ("ERR_CONNECTION_TIMED_OUT", "ERR_TIMED_OUT") or "TimeoutException" in err_str:
        title = "Превышено время ожидания ответа"
        description = "Сервер сайта слишком долго не отвечает на запросы."
        solution = (
            "• Сервер перегружен или блокируется провайдером.\n"
            "• Включите VPN и нажмите «Повторить»."
        )
        short_status = "Таймаут подключения к сайту."

    elif net_code == "ERR_CONNECTION_REFUSED":
        title = "Подключение отклонено сервером"
        description = "Сервер сбросил соединение (net::ERR_CONNECTION_REFUSED)."
        solution = "• Проверьте, доступен ли сайт в браузере.\n• Попробуйте повторить попытку позже."
        short_status = "Подключение отклонено сервером."

    elif net_code and "SSL" in net_code:
        title = "Ошибка защищенного SSL-соединения"
        description = f"Не удалось установить безопасное соединение ({net_code})."
        solution = "• Проверьте дату и время на компьютере.\n• Включите VPN."
        short_status = f"Ошибка SSL ({net_code})."

    elif "SessionNotCreatedException" in err_str or ("WebDriverException" in err_str and "Edge" in err_str):
        title = "Ошибка запуска браузера Edge"
        description = "Не удалось инициализировать Microsoft Edge для проверки ссылки."
        solution = "• Убедитесь, что Microsoft Edge установлен в системе.\n• Перезапустите приложение."
        short_status = "Ошибка запуска браузера Microsoft Edge."

    elif any(k in err_str.lower() for k in ["правообладател", "недоступно в вашей стране", "видео изъято", "заблокировано"]):
        title = "Видео заблокировано правообладателем"
        description = "Видеопоток заблокирован на сайте по требованию правообладателя или недоступен для вашего IP-адреса."
        solution = "• Попробуйте включить VPN другой страны.\n• Выберите другой релиз, перевод или серию."
        short_status = "Видео заблокировано правообладателем (нужен VPN)."

    elif any(k in err_str.lower() for k in ["within.website", "о, привет", "cloudflare", "cf-browser-verification", "ddos"]):
        title = "Сработала защита от ботов (Cloudflare / DDoS-Guard)"
        description = "Сайт запросил подтверждение браузера для доступа к видео."
        solution = "• Включите VPN.\n• Откройте сайт в обычном браузере, чтобы обновить сессию."
        short_status = "Защита от ботов: требуется VPN или обновление сессии."

    else:
        if clean_msg:
            description = f"Детали: {clean_msg[:200]}"
            short_status = f"Ошибка: {clean_msg[:50]}"

    return {
        'title': title,
        'description': description,
        'solution': solution,
        'short_status': short_status,
        'raw_error': err_str
    }


class KinoPubScanDialog(QDialog):
    """
    Интерактивное модальное окно для отслеживания прогресса и ошибок
    при анализе страниц KinoPub / HDRezka.
    """
    cancelled = pyqtSignal()
    retry_requested = pyqtSignal()

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.is_cancelled = False
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Анализ KinoPub / Rezka")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.resize(520, 430)
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

        # 1. Верхний блок: Логотип / Иконка + Заголовок
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        icon_label = QLabel()
        logo_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'logos', 'hdrezka.png')
        if os.path.exists(logo_path):
            pm = QPixmap(logo_path)
            if not pm.isNull():
                icon_label.setPixmap(pm.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if not icon_label.pixmap():
            self.icon_widget = IconWidget(FluentIcon.SEARCH)
            self.icon_widget.setFixedSize(36, 36)
            header_layout.addWidget(self.icon_widget)
        else:
            header_layout.addWidget(icon_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = SubtitleLabel("Анализ KinoPub / Rezka")
        self.title_label.setStyleSheet("font-size: 17px; font-weight: bold;")
        
        display_url = self.url if len(self.url) <= 55 else self.url[:35] + "..." + self.url[-15:]
        self.url_label = CaptionLabel(display_url)
        self.url_label.setStyleSheet("color: #888888;")
        self.url_label.setToolTip(self.url)

        title_box.addWidget(self.title_label)
        title_box.addWidget(self.url_label)
        header_layout.addLayout(title_box, 1)

        layout.addLayout(header_layout)

        # 2. Карточка шагов (Steps card)
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
        steps_layout.setSpacing(10)

        self.step_raw_texts = {
            'browser': "1. Инициализация защищенного браузера",
            'connect': "2. Подключение к сайту и обход защиты Cloudflare",
            'parse': "3. Поиск озвучек, сезонов и серий",
            'streams': "4. Определение доступных разрешений видео"
        }
        self.step_labels = {
            k: QLabel(f"• {txt}") for k, txt in self.step_raw_texts.items()
        }
        for lbl in self.step_labels.values():
            lbl.setStyleSheet("color: #a0a0a0; font-size: 13px;")
            steps_layout.addWidget(lbl)

        layout.addWidget(self.steps_card)

        # 3. Индикатор прогресса и статусная строка
        self.progress_container = QWidget()
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(6)

        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(5)

        self.status_label = BodyLabel("Подготовка к сканированию...")
        self.status_label.setStyleSheet("color: #007acc; font-weight: 500; font-size: 13px;")

        prog_layout.addWidget(self.progress_bar)
        prog_layout.addWidget(self.status_label)
        layout.addWidget(self.progress_container)

        # 4. Блок ошибок (скрыт по умолчанию)
        self.error_card = QFrame()
        self.error_card.setObjectName("ErrorCard")
        self.error_card.setStyleSheet("""
            QFrame#ErrorCard {
                background-color: rgba(244, 67, 54, 0.12);
                border: 1px solid rgba(244, 67, 54, 0.45);
                border-radius: 8px;
                padding: 14px;
            }
        """)
        error_layout = QVBoxLayout(self.error_card)
        error_layout.setSpacing(8)

        self.error_title = StrongBodyLabel("Не удалось получить данные о видео")
        self.error_title.setStyleSheet("color: #ff5252; font-size: 14px; font-weight: bold;")
        
        self.error_text = BodyLabel("")
        self.error_text.setWordWrap(True)
        self.error_text.setStyleSheet("color: #ffffff; font-size: 13px; line-height: 1.3;")

        self.error_hint = CaptionLabel("")
        self.error_hint.setWordWrap(True)
        self.error_hint.setStyleSheet("color: #d0d0d0; font-size: 11px;")

        # Кнопка раскрытия технических деталей ошибки
        self.btn_details = TransparentPushButton("Технические подробности")
        self.btn_details.setIcon(FluentIcon.DOWN)
        self.btn_details.setStyleSheet("color: #888888; font-size: 11px; text-align: left; padding: 2px 0;")
        self.btn_details.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_details.clicked.connect(self._toggle_details)

        self.raw_error_box = QPlainTextEdit()
        self.raw_error_box.setReadOnly(True)
        self.raw_error_box.setMaximumHeight(85)
        self.raw_error_box.setStyleSheet("""
            QPlainTextEdit {
                background-color: #161616;
                color: #a0a0a0;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 6px;
            }
        """)
        self.raw_error_box.hide()

        error_layout.addWidget(self.error_title)
        error_layout.addWidget(self.error_text)
        error_layout.addWidget(self.error_hint)
        error_layout.addWidget(self.btn_details)
        error_layout.addWidget(self.raw_error_box)

        self.error_card.hide()
        layout.addWidget(self.error_card)

        # 5. Нижняя панель кнопок
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_retry = PrimaryPushButton("Повторить")
        self.btn_retry.setIcon(FluentIcon.SYNC)
        self.btn_retry.clicked.connect(self.on_retry_clicked)
        self.btn_retry.hide()

        self.btn_close = PushButton("Закрыть")
        self.btn_close.clicked.connect(self.reject)
        self.btn_close.hide()

        self.btn_cancel = PushButton("Отмена")
        self.btn_cancel.clicked.connect(self.on_cancel_clicked)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_retry)
        btn_layout.addWidget(self.btn_close)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def _toggle_details(self):
        if self.raw_error_box.isHidden():
            self.raw_error_box.show()
            self.btn_details.setText("Скрыть подробности")
            self.btn_details.setIcon(FluentIcon.UP)
        else:
            self.raw_error_box.hide()
            self.btn_details.setText("Технические подробности")
            self.btn_details.setIcon(FluentIcon.DOWN)
        self.adjustSize()

    def set_step_progress(self, percent: int, current_step_key: str, message: str):
        """Обновляет индикатор прогресса и визуальный статус текущего шага."""
        if self.is_cancelled:
            return

        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

        reached_current = False
        for key in ['browser', 'connect', 'parse', 'streams']:
            lbl = self.step_labels.get(key)
            if not lbl:
                continue
            raw_text = self.step_raw_texts.get(key, lbl.text())
            if key == current_step_key:
                lbl.setText("• " + raw_text)
                lbl.setStyleSheet("color: #29b6f6; font-weight: bold; font-size: 13px;")
                reached_current = True
            elif not reached_current:
                lbl.setText("• " + raw_text)
                lbl.setStyleSheet("color: #4caf50; font-weight: bold; font-size: 13px;")
            else:
                lbl.setText("  " + raw_text)
                lbl.setStyleSheet("color: #777777; font-size: 13px;")

    def show_error(self, error_message: str):
        """Переводит диалог в режим ошибки с подробным описанием и кнопкой повтора."""
        self.progress_container.hide()
        self.steps_card.hide()

        info = format_kinopub_error(error_message)
        self.error_title.setText(info['title'])
        self.error_text.setText(info['description'])
        self.error_hint.setText(f"Решение:\n{info['solution']}")
        self.raw_error_box.setPlainText(info['raw_error'])
        self.raw_error_box.hide()
        self.btn_details.setText("Технические подробности")
        self.btn_details.setIcon(FluentIcon.DOWN)

        self.error_card.show()
        self.btn_cancel.hide()
        self.btn_retry.show()
        self.btn_close.show()
        self.adjustSize()

    def on_cancel_clicked(self):
        self.is_cancelled = True
        self.cancelled.emit()
        self.reject()

    def on_retry_clicked(self):
        self.is_cancelled = False
        self.error_card.hide()
        self.raw_error_box.hide()
        self.btn_retry.hide()
        self.btn_close.hide()
        self.btn_cancel.show()

        self.steps_card.show()
        self.progress_container.show()
        self.progress_bar.setValue(5)
        self.status_label.setText("Повторная попытка сканирования...")

        for key, lbl in self.step_labels.items():
            raw_text = self.step_raw_texts.get(key, lbl.text())
            lbl.setText("• " + raw_text)
            lbl.setStyleSheet("color: #a0a0a0; font-size: 13px;")

        self.adjustSize()
        self.retry_requested.emit()


class KinoPubSeriesProgressDialog(QDialog):
    """
    Диалоговое окно отображения прогресса получения прямых ссылок на серии.
    """
    cancel_requested = pyqtSignal()

    def __init__(self, total_episodes: int, parent=None):
        super().__init__(parent)
        self.total = total_episodes
        self.is_cancelled = False
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Получение ссылок на серии")
        self.setModal(True)
        self.setFixedSize(500, 240)
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

        header_layout = QHBoxLayout()
        icon = IconWidget(FluentIcon.DOWNLOAD)
        icon.setFixedSize(30, 30)
        header_layout.addWidget(icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = SubtitleLabel("Сбор ссылок на серии")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.desc = CaptionLabel(f"Всего выбрано серий: {self.total}")
        self.desc.setStyleSheet("color: #888888;")
        title_box.addWidget(title)
        title_box.addWidget(self.desc)
        header_layout.addLayout(title_box, 1)

        layout.addLayout(header_layout)

        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setRange(0, self.total)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = BodyLabel("Подготовка запросов...")
        self.status_label.setStyleSheet("color: #007acc; font-size: 13px;")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        self.btn_cancel = PushButton("Прервать (добавить найденные)")
        self.btn_cancel.clicked.connect(self.on_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def update_progress(self, current: int, episode_title: str):
        if self.is_cancelled:
            return
        self.progress_bar.setValue(current)
        percent = int((current / max(self.total, 1)) * 100)
        self.status_label.setText(f"Получение ссылки {current} из {self.total} ({percent}%):\n{episode_title}")

    def on_cancel(self):
        self.is_cancelled = True
        self.status_label.setText("Остановка сбора ссылок...")
        self.btn_cancel.setEnabled(False)
        self.cancel_requested.emit()
        self.accept()
