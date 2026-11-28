import json
import logging
import os
from datetime import datetime

from PyQt6.QtCore import QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    SubtitleLabel,
    TransparentToolButton,
    isDarkTheme,
)

from .ui_components import EmptyStateCard

logger = logging.getLogger(__name__)


class HistoryManager:
    """JSON-backed download history storage (max 500 entries)."""

    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.history_file = os.path.join(data_dir, 'history.json')
        self._history = []
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self._history = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            self._history = []

    def _save(self):
        try:
            tmp_file = f"{self.history_file}.tmp.{os.getpid()}"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(self._history, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.history_file)
        except Exception as e:
            logger.error(f"Failed to save history: {e}")

    def add_entry(self, url, title, platform, status, file_path=None):
        # Update a recent matching entry instead of duplicating it.
        for existing in self._history[:30]:
            if existing.get('url') == url:
                existing['title'] = title or existing.get('title')
                existing['platform'] = platform or existing.get('platform')
                existing['status'] = status
                if file_path:
                    existing['file_path'] = file_path
                existing['date'] = datetime.now().isoformat()
                self._save()
                return existing

        max_id = max((e.get('id', 0) for e in self._history if isinstance(e.get('id'), int)), default=0)
        entry = {
            'id': max_id + 1,
            'url': url,
            'title': title,
            'platform': platform,
            'status': status,
            'file_path': file_path,
            'date': datetime.now().isoformat(),
        }
        self._history.insert(0, entry)

        if len(self._history) > 500:
            self._history = self._history[:500]

        self._save()
        return entry

    def get_all(self):
        return self._history.copy()

    def search(self, query):
        query = query.lower()
        return [
            entry
            for entry in self._history
            if query in entry.get('title', '').lower() or query in entry.get('url', '').lower()
        ]

    def clear(self):
        self._history = []
        self._save()

    def remove_entry(self, entry_id):
        self._history = [e for e in self._history if e.get('id') != entry_id]
        self._save()


def _format_entry_date(date_str: str) -> str:
    if not date_str:
        return ''
    try:
        return datetime.fromisoformat(date_str).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return date_str[:16] if len(date_str) > 16 else date_str


def _status_badge_object_name(status: str) -> str:
    if status == 'completed':
        return 'StatusBadgeSuccess'
    if status == 'error':
        return 'StatusBadgeDanger'
    if status == 'stopped':
        return 'StatusBadgeWarning'
    return 'StatusBadgeMuted'


class HistoryItemWidget(QFrame):
    """Compact Fluent card for a single history entry matching DownloadItem geometry."""

    redownload_requested = pyqtSignal(dict)
    open_file_requested = pyqtSignal(dict)
    copy_link_requested = pyqtSignal(dict)
    remove_requested = pyqtSignal(dict)

    def __init__(self, entry: dict, translator, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.translator = translator
        self._is_selected = False
        self.setObjectName('HistoryItem')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        full_title = entry.get('title') or 'Unknown'
        display_title = full_title if len(full_title) <= 90 else f"{full_title[:87]}..."
        self.title_label = StrongBodyLabel(display_title, self)
        self.title_label.setObjectName('TitleLabel')
        self.title_label.setToolTip(full_title)
        self.title_label.setWordWrap(False)
        info_layout.addWidget(self.title_label)

        url = entry.get('url', '') or ''
        display_url = url if len(url) <= 80 else f"{url[:77]}..."
        self.url_label = CaptionLabel(display_url, self)
        self.url_label.setObjectName('UrlLabel')
        self.url_label.setToolTip(url)
        info_layout.addWidget(self.url_label)

        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(6)
        meta_layout.setContentsMargins(0, 2, 0, 0)

        platform_name = entry.get('platform') or 'Unknown'
        self.platform_badge = QLabel(platform_name, self)
        self.platform_badge.setObjectName('StatsPill')
        meta_layout.addWidget(self.platform_badge)

        status = entry.get('status', 'unknown') or 'unknown'
        status_text = self.translator.translate(f'status_{status}', status.capitalize())
        self.status_badge = QLabel(status_text, self)
        self.status_badge.setObjectName(_status_badge_object_name(status))
        meta_layout.addWidget(self.status_badge)

        date_text = _format_entry_date(entry.get('date', ''))
        self.date_label = BodyLabel(date_text, self)
        self.date_label.setObjectName('HintLabel')
        meta_layout.addWidget(self.date_label)
        meta_layout.addStretch(1)

        info_layout.addLayout(meta_layout)
        layout.addLayout(info_layout, 1)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(4)

        self.btn_redownload = TransparentToolButton(FluentIcon.SYNC, self)
        self.btn_redownload.setFixedSize(32, 32)
        self.btn_redownload.setToolTip(
            self.translator.translate('history_redownload_tooltip', 'Скачать повторно')
        )
        self.btn_redownload.clicked.connect(lambda: self.redownload_requested.emit(self.entry))
        actions_layout.addWidget(self.btn_redownload)

        file_path = entry.get('file_path') or ''
        self.btn_open_file = TransparentToolButton(FluentIcon.FOLDER, self)
        self.btn_open_file.setFixedSize(32, 32)
        self.btn_open_file.setToolTip(
            self.translator.translate('history_open_file_tooltip', 'Открыть файл')
        )
        self.btn_open_file.setVisible(bool(file_path and os.path.exists(file_path)))
        self.btn_open_file.clicked.connect(lambda: self.open_file_requested.emit(self.entry))
        actions_layout.addWidget(self.btn_open_file)

        self.btn_copy = TransparentToolButton(FluentIcon.LINK, self)
        self.btn_copy.setFixedSize(32, 32)
        self.btn_copy.setToolTip(
            self.translator.translate('history_copy_link_tooltip', 'Копировать ссылку')
        )
        self.btn_copy.clicked.connect(lambda: self.copy_link_requested.emit(self.entry))
        actions_layout.addWidget(self.btn_copy)

        self.btn_remove = TransparentToolButton(FluentIcon.DELETE, self)
        self.btn_remove.setFixedSize(32, 32)
        self.btn_remove.setToolTip(
            self.translator.translate('history_remove_tooltip', 'Удалить из истории')
        )
        self.btn_remove.clicked.connect(lambda: self.remove_requested.emit(self.entry))
        actions_layout.addWidget(self.btn_remove)

        layout.addLayout(actions_layout)

    def set_selected(self, selected: bool):
        if self._is_selected != selected:
            self._is_selected = selected
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._is_selected:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#4cc2ff') if isDarkTheme() else QColor('#005fb8'))
        pill_h = min(42, max(20, self.height() - 36))
        pill_y = (self.height() - pill_h) / 2.0
        painter.drawRoundedRect(QRectF(4.0, pill_y, 3.0, float(pill_h)), 1.5, 1.5)

    def sizeHint(self):
        return QSize(560, 82)


class HistoryTab(QWidget):
    """Unified card-based History tab matching Downloads styling, filters, and empty states."""

    redownload_requested = pyqtSignal(str)
    redownload_timerange_requested = pyqtSignal(str)
    go_downloads_requested = pyqtSignal()

    def __init__(self, translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.parent_window = parent
        self.current_status_filter = 'all'

        from app.path_manager import get_data_dir

        data_dir = get_data_dir()
        self.history_manager = HistoryManager(data_dir)

        self.initUI()
        self.load_history()

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # Page header: title + stats pill + top actions
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self.header_label = SubtitleLabel(
            self.translator.translate('history_title', 'Download History'),
            self,
        )
        self.header_label.setObjectName('PageTitle')
        header_row.addWidget(self.header_label)

        self.stats_label = QLabel('', self)
        self.stats_label.setObjectName('StatsPill')
        header_row.addWidget(self.stats_label)

        header_row.addStretch(1)

        self.btn_refresh = PushButton(
            FluentIcon.SYNC,
            self.translator.translate('refresh', 'Refresh'),
            self,
        )
        self.btn_refresh.setFixedHeight(32)
        self.btn_refresh.clicked.connect(self.load_history)
        header_row.addWidget(self.btn_refresh)

        self.btn_clear_all = PushButton(
            FluentIcon.DELETE,
            self.translator.translate('clear_all_history', 'Clear All'),
            self,
        )
        self.btn_clear_all.setFixedHeight(32)
        self.btn_clear_all.clicked.connect(self.clear_history)
        header_row.addWidget(self.btn_clear_all)

        layout.addLayout(header_row)

        # Unified filter toolbar matching Downloads
        self.filter_toolbar = QFrame(self)
        self.filter_toolbar.setObjectName('FilterBarCard')
        ft_layout = QHBoxLayout(self.filter_toolbar)
        ft_layout.setContentsMargins(10, 8, 10, 8)
        ft_layout.setSpacing(6)

        self.btn_filter_all = PushButton(self.translator.translate('filter_all', 'Все'), self)
        self.btn_filter_completed = PushButton(
            self.translator.translate('filter_completed', 'Завершенные'),
            self,
        )
        self.btn_filter_errors = PushButton(
            self.translator.translate('filter_errors', 'Ошибки'),
            self,
        )
        self.btn_filter_stopped = PushButton(
            self.translator.translate('filter_stopped', 'Остановленные'),
            self,
        )

        self.filter_btn_group = QButtonGroup(self)
        filter_buttons = [
            (0, 'all', self.btn_filter_all),
            (1, 'completed', self.btn_filter_completed),
            (2, 'error', self.btn_filter_errors),
            (3, 'stopped', self.btn_filter_stopped),
        ]
        for btn_id, status_key, btn in filter_buttons:
            btn.setFixedHeight(30)
            btn.setCheckable(True)
            btn.setProperty('status_key', status_key)
            self.filter_btn_group.addButton(btn, btn_id)
            ft_layout.addWidget(btn)

        self.btn_filter_all.setChecked(True)
        self.filter_btn_group.idClicked.connect(self._on_status_filter_clicked)

        ft_layout.addStretch(1)

        self.platform_combo = ComboBox(self)
        self.platform_combo.setFixedHeight(30)
        self.platform_combo.setMinimumWidth(145)
        self.platform_combo.currentIndexChanged.connect(lambda _idx: self._apply_filters())
        ft_layout.addWidget(self.platform_combo)

        self.search_input = SearchLineEdit(self)
        self.search_input.setPlaceholderText(
            self.translator.translate('search_history', 'Search by title or URL...')
        )
        self.search_input.setMinimumWidth(180)
        self.search_input.setMaximumWidth(260)
        self.search_input.setFixedHeight(30)
        self.search_input.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.search_input.textChanged.connect(self.on_search)
        ft_layout.addWidget(self.search_input)

        layout.addWidget(self.filter_toolbar)

        # Stacked content: cards list vs empty / no-results state card
        self.content_stack = QStackedWidget(self)

        self.history_list = QListWidget(self)
        self.history_list.setObjectName('DownloadsList')
        self.history_list.setSpacing(6)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.show_context_menu)
        self.history_list.itemSelectionChanged.connect(self._sync_selection_states)
        self.content_stack.addWidget(self.history_list)

        self.empty_container = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_container)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_card = EmptyStateCard(
            icon=FluentIcon.HISTORY,
            title=self.translator.translate('history_empty_title', 'История загрузок пока пуста'),
            subtitle=self.translator.translate(
                'history_empty_subtitle',
                'Завершённые и остановленные загрузки появятся здесь для быстрого повтора и доступа к файлам.',
            ),
            action_text=self.translator.translate('history_go_downloads', 'Перейти к загрузкам'),
            action_callback=self.go_downloads_requested.emit,
            parent=self.empty_container,
        )
        self.empty_card.setMinimumWidth(420)
        self.empty_card.setMaximumWidth(560)
        empty_layout.addWidget(self.empty_card, 0, Qt.AlignmentFlag.AlignCenter)
        self.content_stack.addWidget(self.empty_container)

        layout.addWidget(self.content_stack, 1)

    def _on_status_filter_clicked(self, btn_id: int):
        mapping = {0: 'all', 1: 'completed', 2: 'error', 3: 'stopped'}
        self.current_status_filter = mapping.get(btn_id, 'all')
        self._apply_filters()

    def _populate_platforms(self, entries: list[dict]):
        current_platform = (
            self.platform_combo.currentData() if self.platform_combo.count() > 0 else 'all'
        )
        if not current_platform:
            current_platform = 'all'

        seen = []
        for entry in entries:
            p = (entry.get('platform') or '').strip()
            if p and p not in seen:
                seen.append(p)

        self.platform_combo.blockSignals(True)
        self.platform_combo.clear()
        self.platform_combo.addItem(
            self.translator.translate('all_platforms', 'Все платформы'),
            icon=FluentIcon.GLOBE,
            userData='all',
        )
        target_idx = 0
        for idx, plat in enumerate(sorted(seen, key=str.lower), start=1):
            self.platform_combo.addItem(plat, userData=plat)
            if plat == current_platform:
                target_idx = idx
        self.platform_combo.setCurrentIndex(target_idx)
        self.platform_combo.blockSignals(False)

    def load_history(self):
        """Load and display history."""
        entries = self.history_manager.get_all()
        self._populate_platforms(entries)
        self._update_stats(entries)
        self._apply_filters(entries)

    def _filter_entries(self, entries: list[dict]) -> list[dict]:
        query = self.search_input.text().strip().lower()
        selected_platform = (
            self.platform_combo.currentData() if self.platform_combo.count() > 0 else 'all'
        )
        if not selected_platform:
            selected_platform = 'all'

        filtered = []
        for entry in entries:
            if self.current_status_filter != 'all' and entry.get('status') != self.current_status_filter:
                continue
            if selected_platform != 'all' and (entry.get('platform') or '').strip() != selected_platform:
                continue
            if query:
                title = (entry.get('title') or '').lower()
                url = (entry.get('url') or '').lower()
                if query not in title and query not in url:
                    continue
            filtered.append(entry)
        return filtered

    def _apply_filters(self, all_entries: list[dict] | None = None):
        if all_entries is None:
            all_entries = self.history_manager.get_all()

        filtered = self._filter_entries(all_entries)
        self._populate_list(filtered)

        if not all_entries:
            self.empty_card.set_state(
                icon=FluentIcon.HISTORY,
                title=self.translator.translate('history_empty_title', 'История загрузок пока пуста'),
                subtitle=self.translator.translate(
                    'history_empty_subtitle',
                    'Завершённые и остановленные загрузки появятся здесь для быстрого повтора и доступа к файлам.',
                ),
                action_text=self.translator.translate('history_go_downloads', 'Перейти к загрузкам'),
                action_callback=self.go_downloads_requested.emit,
            )
            self.content_stack.setCurrentWidget(self.empty_container)
        elif not filtered:
            self.empty_card.set_state(
                icon=FluentIcon.SEARCH,
                title=self.translator.translate('history_no_results_title', 'В истории ничего не найдено'),
                subtitle=self.translator.translate(
                    'history_no_results_subtitle',
                    'Попробуйте изменить строку поиска, фильтр статуса или выбранную платформу.',
                ),
                action_text=self.translator.translate('filter_reset', 'Сбросить фильтры'),
                action_callback=self.reset_filters,
            )
            self.content_stack.setCurrentWidget(self.empty_container)
        else:
            self.content_stack.setCurrentWidget(self.history_list)

    def reset_filters(self):
        """Clear status, platform, and text filters."""
        self.current_status_filter = 'all'
        self.btn_filter_all.setChecked(True)
        self.platform_combo.blockSignals(True)
        if self.platform_combo.count() > 0:
            self.platform_combo.setCurrentIndex(0)
        self.platform_combo.blockSignals(False)
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self._apply_filters()

    def _populate_list(self, entries: list[dict]):
        self.history_list.setUpdatesEnabled(False)
        try:
            self.history_list.clear()
            for entry in entries:
                item = QListWidgetItem(self.history_list)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                card = HistoryItemWidget(entry, self.translator, parent=self.history_list)
                card.redownload_requested.connect(self.redownload)
                card.open_file_requested.connect(self.open_file)
                card.copy_link_requested.connect(self.copy_link)
                card.remove_requested.connect(self.remove_entry)
                item.setSizeHint(card.sizeHint())
                self.history_list.addItem(item)
                self.history_list.setItemWidget(item, card)
        finally:
            self.history_list.setUpdatesEnabled(True)
        self._sync_selection_states()

    def _sync_selection_states(self):
        for i in range(self.history_list.count()):
            item = self.history_list.item(i)
            widget = self.history_list.itemWidget(item)
            if isinstance(widget, HistoryItemWidget):
                widget.set_selected(item.isSelected())

    def _update_stats(self, entries):
        """Update statistics badge."""
        total = len(entries)
        completed = len([e for e in entries if e.get('status') == 'completed'])
        errors = len([e for e in entries if e.get('status') == 'error'])

        template = self.translator.translate(
            'history_stats',
            'Total: {total} | Completed: {completed} | Errors: {errors}',
        )
        if '{total}' in template:
            text = template.format(total=total, completed=completed, errors=errors)
        else:
            text = f'Total: {total} | Completed: {completed} | Errors: {errors}'
        self.stats_label.setText(text)

    def on_search(self, text):
        """Handle search input."""
        if self.search_input.text() != text:
            self.search_input.blockSignals(True)
            self.search_input.setText(text)
            self.search_input.blockSignals(False)
        self._apply_filters()

    def show_context_menu(self, position):
        """Show context menu for selected history card."""
        item = self.history_list.itemAt(position)
        if item is None:
            return

        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            return

        menu = QMenu(self)

        redownload_action = QAction(self.translator.translate('redownload', 'Re-download'), self)
        redownload_action.triggered.connect(lambda: self.redownload(entry))
        menu.addAction(redownload_action)

        redownload_tr_action = QAction(self.translator.translate('redownload_timerange', 'Скачать отрезок...'), self)
        redownload_tr_action.triggered.connect(lambda: self.redownload_timerange(entry))
        menu.addAction(redownload_tr_action)

        copy_action = QAction(self.translator.translate('copy_link', 'Copy link'), self)
        copy_action.triggered.connect(lambda: self.copy_link(entry))
        menu.addAction(copy_action)

        if entry.get('file_path') and os.path.exists(entry.get('file_path', '')):
            open_action = QAction(self.translator.translate('open_file', 'Open file'), self)
            open_action.triggered.connect(lambda: self.open_file(entry))
            menu.addAction(open_action)

        menu.addSeparator()

        remove_action = QAction(self.translator.translate('remove_from_history', 'Remove from history'), self)
        remove_action.triggered.connect(lambda: self.remove_entry(entry))
        menu.addAction(remove_action)

        menu.exec(self.history_list.viewport().mapToGlobal(position))

    def redownload(self, entry):
        """Re-download the entry."""
        url = entry.get('url')
        if url:
            self.redownload_requested.emit(url)

    def redownload_timerange(self, entry):
        """Re-download specific time range of the entry."""
        url = entry.get('url')
        if url:
            self.redownload_timerange_requested.emit(url)

    def copy_link(self, entry):
        """Copy link to clipboard."""
        url = entry.get('url', '')
        QApplication.clipboard().setText(url)

    def open_file(self, entry):
        """Open the downloaded file."""
        file_path = entry.get('file_path', '')
        if file_path and os.path.exists(file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

    def remove_entry(self, entry):
        """Remove entry from history."""
        entry_id = entry.get('id')
        if entry_id:
            self.history_manager.remove_entry(entry_id)
            self.load_history()

    def clear_history(self):
        """Clear all history."""
        reply = QMessageBox.question(
            self,
            self.translator.translate('confirm', 'Confirm'),
            self.translator.translate('clear_history_confirm', 'Are you sure you want to clear all history?'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.history_manager.clear()
            self.load_history()

    def add_to_history(self, url, title, platform, status, file_path=None):
        """Add new entry to history (called from download manager)."""
        self.history_manager.add_entry(url, title, platform, status, file_path)
        self.load_history()

    def update_translations(self):
        """Update UI translations."""
        self.header_label.setText(self.translator.translate('history_title', 'Download History'))
        self.search_input.setPlaceholderText(
            self.translator.translate('search_history', 'Search by title or URL...')
        )
        self.btn_refresh.setText(self.translator.translate('refresh', 'Refresh'))
        self.btn_clear_all.setText(self.translator.translate('clear_all_history', 'Clear All'))
        self.btn_filter_all.setText(self.translator.translate('filter_all', 'Все'))
        self.btn_filter_completed.setText(self.translator.translate('filter_completed', 'Завершенные'))
        self.btn_filter_errors.setText(self.translator.translate('filter_errors', 'Ошибки'))
        self.btn_filter_stopped.setText(self.translator.translate('filter_stopped', 'Остановленные'))

        self.load_history()
