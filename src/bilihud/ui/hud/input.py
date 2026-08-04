"""HUD text-input widgets shared by the normal and gaming-mode surfaces."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)


class ModernInputWidget(QWidget):
    """Render a compact text input and emit normalized send requests."""

    send_requested = pyqtSignal(str)
    emoticon_requested = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        placeholder: str = "发送弹幕...",
        show_emoticon_button: bool = True,
    ) -> None:
        """Create an input row with optional live-emoticon access."""
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(placeholder)
        self.input_edit.setStyleSheet(
            """
            QLineEdit {
                background-color: rgba(255, 255, 255, 30);
                color: white;
                border: 1px solid rgba(255, 255, 255, 50);
                border-radius: 13px;
                padding: 4px 10px;
                font-family: 'Segoe UI', 'Microsoft YaHei';
                font-size: 12px;
                selection-background-color: rgba(255, 255, 255, 100);
            }
            QLineEdit:focus {
                background-color: rgba(255, 255, 255, 50);
                border: 1px solid rgba(255, 255, 255, 150);
            }
        """
        )
        self.input_edit.returnPressed.connect(self.on_send)

        self.emoticon_btn = QPushButton("☻")
        self.emoticon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.emoticon_btn.setFixedSize(28, 26)
        self.emoticon_btn.setToolTip("发送表情")
        self.emoticon_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 35);
                color: white;
                border: 1px solid rgba(255, 255, 255, 60);
                border-radius: 13px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 60);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 80);
            }
        """
        )
        self.emoticon_btn.clicked.connect(self.emoticon_requested.emit)
        self.emoticon_btn.setVisible(show_emoticon_button)

        self.send_btn = QPushButton("发送")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setFixedSize(46, 26)
        self.send_btn.setStyleSheet(
            """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4FacFe, stop:1 #00f2fe);
                color: white;
                border: none;
                border-radius: 13px;
                font-weight: bold;
                font-size: 11px;
                font-family: 'Segoe UI', 'Microsoft YaHei';
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #66b5ff, stop:1 #33f5ff);
            }
            QPushButton:pressed {
                background: #00bcd4;
            }
        """
        )
        self.send_btn.clicked.connect(self.on_send)

        self._layout.addWidget(self.input_edit)
        self._layout.addWidget(self.emoticon_btn)
        self._layout.addWidget(self.send_btn)

    def on_send(self) -> None:
        """Emit one non-empty trimmed message and clear the input."""
        text = self.input_edit.text().strip()
        if text:
            self.send_requested.emit(text)
            self.input_edit.clear()

    def setFocus(self, reason: Qt.FocusReason = Qt.FocusReason.OtherFocusReason) -> None:
        """Focus the editable field used by the input row."""
        self.input_edit.setFocus(reason)


class DanmakuInputDialog(QDialog):
    """Provide a temporary top-level input surface for gaming mode."""

    send_message = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the frameless input surface without starting external work."""
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(450, 60)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.container = QFrame(self)
        self.container.setStyleSheet(
            """
            QFrame {
                background-color: rgba(20, 20, 30, 220);
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
        """
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.container.setGraphicsEffect(shadow)

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(10, 8, 10, 8)
        self.input_widget = ModernInputWidget(
            self,
            placeholder="输入弹幕... [ESC关闭]",
            show_emoticon_button=False,
        )
        self.input_widget.send_requested.connect(self.on_send)
        container_layout.addWidget(self.input_widget)
        layout.addWidget(self.container)

    def on_send(self, text: str) -> None:
        """Emit the submitted message and hide the temporary surface."""
        self.send_message.emit(text)
        self.hide()

    def showEvent(self, a0: QShowEvent | None) -> None:
        """Focus and position the input near the bottom of the primary screen."""
        super().showEvent(a0)
        self.input_widget.setFocus()
        screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.geometry()
            self.move(geometry.width() // 2 - self.width() // 2, int(geometry.height() * 0.8))
        self.activateWindow()
        self.raise_()

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """Hide the surface on Escape while preserving normal key handling."""
        if a0 is not None and a0.key() == Qt.Key.Key_Escape:
            self.hide()
        super().keyPressEvent(a0)


__all__ = ("DanmakuInputDialog", "ModernInputWidget")
