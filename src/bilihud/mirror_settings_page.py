"""Embedded Mirror settings page used by the unified settings window."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QClipboard, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .app.mirror_coordinator import MirrorCoordinatorState


class MirrorSettingsPage(QWidget):
    """Present Mirror state and forward enable requests to its lifecycle owner."""

    enabled_requested = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the embedded Mirror form without owning the server lifecycle."""
        super().__init__(parent)
        self._state: MirrorCoordinatorState | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)

        card = QFrame(self)
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(14)

        title = QLabel("浏览器同步", card)
        title.setObjectName("card_title")
        card_layout.addWidget(title)

        self.enabled_checkbox = QCheckBox("启用 BiliHUD Mirror", card)
        self.enabled_checkbox.setObjectName("mirror_enabled")
        self.enabled_checkbox.toggled.connect(self.enabled_requested.emit)
        card_layout.addWidget(self.enabled_checkbox)

        self.status_label = QLabel("未启动", card)
        self.status_label.setObjectName("status_label")
        card_layout.addWidget(self.status_label)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.url_input = QLineEdit(card)
        self.url_input.setObjectName("mirror_url")
        self.url_input.setReadOnly(True)
        self.url_input.setCursorPosition(0)
        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.addWidget(self.url_input, 1)
        self.copy_button = QPushButton("复制 URL", card)
        self.copy_button.clicked.connect(self.copy_url)
        url_row.addWidget(self.copy_button)
        form.addRow("访问地址", url_row)
        card_layout.addLayout(form)

        hint = QLabel("在浏览器中打开这个地址，即可查看 HUD 的实时弹幕。", card)
        hint.setObjectName("muted_label")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        layout.addWidget(card)
        layout.addStretch(1)

    def set_state(self, state: MirrorCoordinatorState) -> None:
        """Render one coordinator-owned Mirror snapshot."""
        self._state = state
        self.enabled_checkbox.blockSignals(True)
        self.enabled_checkbox.setChecked(state.enabled)
        self.enabled_checkbox.blockSignals(False)
        self.status_label.setText(state.status_text)
        self.url_input.setText(state.url)
        self.url_input.setCursorPosition(0)

    def set_status_text(self, status: str) -> None:
        """Update only the status text while the owning coordinator state is unchanged."""
        self.status_label.setText(status)

    def copy_url(self) -> None:
        """Copy the currently rendered Mirror endpoint to the desktop clipboard."""
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.url_input.text(), mode=QClipboard.Mode.Clipboard)
            self.status_label.setText("URL 已复制")


__all__ = ("MirrorSettingsPage",)
