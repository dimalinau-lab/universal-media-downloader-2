"""Shared Fluent UI building blocks for Downloads, History, and Settings tabs."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)


class EmptyStateCard(QFrame):
    """Reusable empty/no-results state card matching the Fluent surface style."""

    action_triggered = pyqtSignal()

    def __init__(
        self,
        icon: FluentIcon = FluentIcon.HISTORY,
        title: str = "",
        subtitle: str = "",
        action_text: str | None = None,
        action_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("EmptyCard")
        self._action_callback = action_callback

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.setSpacing(10)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_widget = IconWidget(icon, self)
        self.icon_widget.setFixedSize(36, 36)
        outer.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignCenter)

        self.title_label = SubtitleLabel(title, self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        outer.addWidget(self.title_label)

        self.subtitle_label = BodyLabel(subtitle, self)
        self.subtitle_label.setObjectName("HintLabel")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        outer.addWidget(self.subtitle_label)

        self.action_button = PushButton(action_text or "", self)
        self.action_button.setFixedHeight(32)
        self.action_button.setVisible(bool(action_text))
        self.action_button.clicked.connect(self._on_action_clicked)
        outer.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignCenter)

    def _on_action_clicked(self):
        self.action_triggered.emit()
        if callable(self._action_callback):
            self._action_callback()

    def set_state(
        self,
        title: str,
        subtitle: str = "",
        icon: FluentIcon | None = None,
        action_text: str | None = None,
        action_callback=None,
    ):
        """Update icon, text, and optional primary action in one call."""
        if icon is not None:
            self.icon_widget.setIcon(icon)
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        if action_callback is not None:
            self._action_callback = action_callback
        self.action_button.setText(action_text or "")
        self.action_button.setVisible(bool(action_text))


class _ClickableHeader(QFrame):
    """Keyboard- and mouse-accessible clickable header for accordion sections."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AccordionHeader")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class AccordionSectionCard(QFrame):
    """Collapsible Fluent settings card keeping child widget state intact when collapsed."""

    toggled = pyqtSignal(str, bool)

    def __init__(
        self,
        section_key: str,
        title: str = "",
        icon: FluentIcon = FluentIcon.SETTING,
        summary_text: str = "",
        expanded: bool = True,
        settings=None,
        parent=None,
    ):
        super().__init__(parent)
        self.section_key = section_key
        self._settings = settings
        self._expanded = bool(expanded)
        self.setObjectName("AccordionCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = _ClickableHeader(self)
        self.header.setMinimumHeight(48)
        self.header.clicked.connect(self.toggle)

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 10, 14, 10)
        header_layout.setSpacing(10)

        self.icon_widget = IconWidget(icon, self.header)
        self.icon_widget.setFixedSize(18, 18)
        header_layout.addWidget(self.icon_widget)

        self.title_label = StrongBodyLabel(title, self.header)
        self.title_label.setObjectName("AccordionTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(self.title_label)

        self.summary_label = CaptionLabel(summary_text, self.header)
        self.summary_label.setObjectName("AccordionSummary")
        self.summary_label.setVisible(bool(summary_text))
        header_layout.addWidget(self.summary_label)

        header_layout.addStretch(1)

        self.status_badge = QLabel("", self.header)
        self.status_badge.setObjectName("StatusBadgeMuted")
        self.status_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.status_badge.setVisible(False)
        header_layout.addWidget(self.status_badge)

        self.chevron_widget = IconWidget(FluentIcon.CHEVRON_DOWN_MED, self.header)
        self.chevron_widget.setFixedSize(12, 12)
        header_layout.addWidget(self.chevron_widget)

        root.addWidget(self.header)

        self.body_widget = QWidget(self)
        self.body_widget.setObjectName("AccordionBody")
        self._body_layout = QVBoxLayout(self.body_widget)
        self._body_layout.setContentsMargins(16, 12, 16, 16)
        self._body_layout.setSpacing(12)
        root.addWidget(self.body_widget)

        self.set_expanded(self._expanded, persist=False, emit_signal=False)

    def content_layout(self) -> QVBoxLayout:
        """Return the inner body layout where child setting rows are placed."""
        return self._body_layout

    def is_expanded(self) -> bool:
        return self._expanded

    def toggle(self):
        """Flip current expanded state."""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool, persist: bool = True, emit_signal: bool = True):
        """Show or hide body content without clearing child controls."""
        self._expanded = bool(expanded)
        self.header.setProperty("expanded", self._expanded)
        self.body_widget.setVisible(self._expanded)
        self.chevron_widget.setIcon(
            FluentIcon.CHEVRON_DOWN_MED if self._expanded else FluentIcon.CHEVRON_RIGHT_MED
        )
        # Re-polish header so :expanded border/separator rules update immediately on theme/state change.
        style = self.header.style()
        if style is not None:
            style.unpolish(self.header)
            style.polish(self.header)

        if persist and self._settings is not None:
            self._settings.setValue(f"settings_accordion/{self.section_key}", self._expanded)

        if emit_signal:
            self.toggled.emit(self.section_key, self._expanded)

    def set_title(self, title: str):
        self.title_label.setText(title)

    def set_summary(self, summary_text: str):
        self.summary_label.setText(summary_text)
        self.summary_label.setVisible(bool(summary_text))

    def set_status_badge(self, text: str = "", level: str = "muted"):
        """Set optional status pill inside the header ('success' | 'warning' | 'danger' | 'muted')."""
        object_names = {
            "success": "StatusBadgeSuccess",
            "warning": "StatusBadgeWarning",
            "danger": "StatusBadgeDanger",
            "muted": "StatusBadgeMuted",
        }
        self.status_badge.setObjectName(object_names.get(level, "StatusBadgeMuted"))
        self.status_badge.setText(text)
        self.status_badge.setVisible(bool(text))
        style = self.status_badge.style()
        if style is not None:
            style.unpolish(self.status_badge)
            style.polish(self.status_badge)
