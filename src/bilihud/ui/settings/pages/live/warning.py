"""Custom warning dialog for partial live-control outcomes."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class LiveWarningDialog(QDialog):
    """Render a compact, non-blocking warning in the settings visual language."""

    def __init__(self, parent: QWidget, title: str, message: str, details: str) -> None:
        """Create a warning surface with one explicit acknowledgement action."""
        super().__init__(parent)
        self.setObjectName("live_warning_dialog")
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumWidth(460)
        self.resize(480, 252)
        self._build_ui(title, message, details)

    def _build_ui(self, title: str, message: str, details: str) -> None:
        """Build the warning hierarchy without introducing a second settings surface."""
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        surface = QFrame(self)
        surface.setObjectName("warning_surface")
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(22, 20, 22, 18)
        surface_layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)

        mark = QFrame(surface)
        mark.setObjectName("warning_mark")
        mark.setFixedSize(40, 40)
        mark_layout = QVBoxLayout(mark)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        mark_label = QLabel("!", mark)
        mark_label.setObjectName("warning_mark_label")
        mark_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_layout.addWidget(mark_label)
        header.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)

        heading = QVBoxLayout()
        heading.setSpacing(3)
        title_label = QLabel(title, surface)
        title_label.setObjectName("warning_title")
        title_label.setWordWrap(True)
        message_label = QLabel(message, surface)
        message_label.setObjectName("warning_message")
        message_label.setWordWrap(True)
        heading.addWidget(title_label)
        heading.addWidget(message_label)
        header.addLayout(heading, 1)
        surface_layout.addLayout(header)

        details_frame = QFrame(surface)
        details_frame.setObjectName("warning_details_frame")
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(12, 10, 12, 10)
        details_label = QLabel(details, details_frame)
        details_label.setObjectName("warning_details")
        details_label.setWordWrap(True)
        details_layout.addWidget(details_label)
        surface_layout.addWidget(details_frame)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        acknowledge = QPushButton("知道了", surface)
        acknowledge.setProperty("accent", True)
        acknowledge.clicked.connect(self.accept)
        actions.addWidget(acknowledge)
        surface_layout.addLayout(actions)

        root.addWidget(surface)

    def showEvent(self, a0: QShowEvent | None) -> None:
        """Center the transient warning over the owning settings window."""
        self.adjustSize()
        parent = self.parentWidget()
        window = parent.window() if parent is not None else None
        if window is not None:
            self.move(window.frameGeometry().center() - self.rect().center())
        super().showEvent(a0)


__all__ = ("LiveWarningDialog",)
