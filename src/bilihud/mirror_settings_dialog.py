from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QClipboard, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MirrorSettingsDialog(QDialog):
    mirror_enabled_requested = pyqtSignal(bool)

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("BiliHUD Mirror")
        self.setMinimumWidth(460)

        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.enabled_checkbox = QCheckBox("启用 BiliHUD Mirror")
        self.enabled_checkbox.toggled.connect(self._on_enabled_toggled)
        layout.addWidget(self.enabled_checkbox)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setReadOnly(True)
        self.url_input.setText(self.owner.mirror_url)
        self.url_input.setCursorPosition(0)
        url_row.addWidget(self.url_input, 1)

        self.copy_button = QPushButton("复制 URL")
        self.copy_button.clicked.connect(self.copy_url)
        url_row.addWidget(self.copy_button)
        layout.addLayout(url_row)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self.setStyleSheet(
            """
            QDialog {
                background: #2b2b2b;
                color: #eeeeee;
            }
            QLabel, QCheckBox {
                color: #eeeeee;
            }
            QLineEdit {
                color: #eeeeee;
                background: #1f1f1f;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 6px 8px;
            }
            QPushButton {
                color: #ffffff;
                background: #00a1d6;
                border: none;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QPushButton:hover {
                background: #00b5e5;
            }
            """
        )

    def set_mirror_state(self, enabled: bool, status: str, mirror_url: str) -> None:
        self.enabled_checkbox.blockSignals(True)
        self.enabled_checkbox.setChecked(enabled)
        self.enabled_checkbox.blockSignals(False)
        self.status_label.setText(status)
        self.url_input.setText(mirror_url)
        self.url_input.setCursorPosition(0)

    def refresh(self) -> None:
        enabled = self.owner.mirror_enabled
        status = self.owner.mirror_status_text()
        self.set_mirror_state(enabled, status, self.owner.mirror_url)

    def _on_enabled_toggled(self, checked: bool) -> None:
        """Forward a settings request to the lifecycle-owning widget."""
        self.mirror_enabled_requested.emit(checked)

    def copy_url(self) -> None:
        QGuiApplication.clipboard().setText(self.url_input.text(), mode=QClipboard.Mode.Clipboard)
