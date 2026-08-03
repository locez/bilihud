"""Embedded stream-credential list used by the live settings page."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QClipboard, QGuiApplication
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .live.models import StreamCredential


class LiveCredentials(QWidget):
    """Render transient stream endpoints and expose copy requests to the page owner."""

    copy_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create an empty credential list that never persists private values."""
        super().__init__(parent)
        self._credentials: tuple[StreamCredential, ...] = ()
        self._init_ui()

    def _init_ui(self) -> None:
        """Build the bounded list container used inside the settings card."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._layout = layout
        self._render()

    def set_credentials(self, credentials: tuple[StreamCredential, ...]) -> None:
        """Replace the displayed credential snapshot after a live operation."""
        self._credentials = credentials
        self._render()

    def _render(self) -> None:
        """Render either the empty state or one copyable row per endpoint."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._credentials:
            empty = QLabel("开播成功后，推流地址和密钥会显示在这里。", self)
            empty.setObjectName("muted_label")
            self._layout.addWidget(empty)
            self._layout.addStretch(1)
            return
        for credential in self._credentials:
            self._layout.addWidget(self._credential_row(credential))
        self._layout.addStretch(1)

    def _credential_row(self, credential: StreamCredential) -> QWidget:
        """Build one copyable credential row for a service-provided endpoint."""
        row = QFrame(self)
        row.setObjectName("credential_row")
        layout = QGridLayout(row)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        title = QLabel(credential.label.upper(), row)
        title.setObjectName("card_title")
        layout.addWidget(title, 0, 0, 1, 3)
        address = QLineEdit(credential.address, row)
        address.setReadOnly(True)
        copy_address = QPushButton("复制地址", row)
        copy_address.clicked.connect(lambda _checked=False, value=credential.address: self._copy(value))
        layout.addWidget(QLabel("地址", row), 1, 0)
        layout.addWidget(address, 1, 1)
        layout.addWidget(copy_address, 1, 2)
        key = QLineEdit(credential.key, row)
        key.setReadOnly(True)
        key.setEchoMode(QLineEdit.EchoMode.Password)
        copy_key = QPushButton("复制密钥", row)
        copy_key.clicked.connect(lambda _checked=False, value=credential.key: self._copy(value))
        layout.addWidget(QLabel("密钥", row), 2, 0)
        layout.addWidget(key, 2, 1)
        layout.addWidget(copy_key, 2, 2)
        return row

    def _copy(self, value: str) -> None:
        """Copy one credential and notify the page owner without exposing it in logs."""
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(value, mode=QClipboard.Mode.Clipboard)
        self.copy_requested.emit()


__all__ = ("LiveCredentials",)
