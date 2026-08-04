"""Live-emoticon picker and its image-loading presentation state."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bilihud.live.emoticons import LiveEmoticon, LiveEmoticonPackage


class EmoticonPickerPopup(QDialog):
    """Render available live-room emoticons and emit the selected value."""

    emoticon_selected = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the popup and its owned Qt image-loading manager."""
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(330, 260)
        self._network_manager = QNetworkAccessManager(self)
        self._image_cache: dict[str, QPixmap] = {}
        self._button_by_url: dict[str, list[QToolButton]] = {}
        self._emoticon_buttons: list[QToolButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.container = QFrame(self)
        self.container.setStyleSheet(
            """
            QFrame {
                background-color: rgba(22, 24, 28, 235);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 8px;
            }
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background: rgba(255, 255, 255, 24);
                color: white;
                padding: 5px 9px;
                margin-right: 4px;
                border-radius: 5px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: rgba(79, 172, 254, 150);
            }
            QToolButton {
                background: rgba(255, 255, 255, 18);
                border: 1px solid rgba(255, 255, 255, 22);
                border-radius: 6px;
                color: white;
                padding: 2px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 40);
            }
            QToolButton:disabled {
                background: rgba(255, 255, 255, 10);
                color: rgba(255, 255, 255, 110);
            }
        """
        )
        outer.addWidget(self.container)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(8, 8, 8, 8)
        self.tabs = QTabWidget(self.container)
        layout.addWidget(self.tabs)

    def set_loading(self) -> None:
        """Render the loading state while the HUD service fetches packages."""
        self._clear_tabs()
        label = QLabel("加载中...", self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: rgba(255, 255, 255, 180);")
        self.tabs.addTab(label, "表情")

    def set_error(self, message: str) -> None:
        """Render one user-visible package-loading error."""
        self._clear_tabs()
        label = QLabel(message, self)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: rgba(255, 255, 255, 180);")
        self.tabs.addTab(label, "表情")

    def set_packages(self, packages: list[LiveEmoticonPackage]) -> None:
        """Replace the popup contents with normalized emoticon packages."""
        self._clear_tabs()
        if not packages:
            self.set_error("没有可显示的直播间表情")
            return

        for package in packages:
            page = QWidget(self)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 4, 0, 0)
            scroll = QScrollArea(page)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            grid_host = QWidget(scroll)
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)

            for index, emoticon in enumerate(package.emoticons):
                button = self._create_emoticon_button(emoticon)
                row, col = divmod(index, 5)
                grid.addWidget(button, row, col)
                self._emoticon_buttons.append(button)

            scroll.setWidget(grid_host)
            page_layout.addWidget(scroll)
            self.tabs.addTab(page, package.name)

    def _clear_tabs(self) -> None:
        self._emoticon_buttons.clear()
        self._button_by_url.clear()
        while self.tabs.count():
            page = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if page is not None:
                page.deleteLater()

    def _create_emoticon_button(self, emoticon: LiveEmoticon) -> QToolButton:
        button = QToolButton(self)
        button.setFixedSize(52, 52)
        button.setIconSize(QSize(42, 42))
        label = emoticon.unlock_label
        button.setToolTip(emoticon.emoji if not label else f"{emoticon.emoji} - {label}")
        if not emoticon.is_available:
            button.setEnabled(False)
            if label:
                button.setText(label)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                color = (
                    emoticon.unlock_color
                    if emoticon.unlock_color.startswith("#")
                    else "rgba(255, 255, 255, 140)"
                )
                button.setStyleSheet(
                    f"""
                    QToolButton:disabled {{
                        background: rgba(255, 255, 255, 10);
                        color: {color};
                    }}
                    """
                )
        else:
            button.clicked.connect(lambda _checked=False, item=emoticon: self._select_emoticon(item))

        self._load_icon(button, emoticon.url)
        return button

    def _select_emoticon(self, emoticon: LiveEmoticon) -> None:
        self.emoticon_selected.emit(emoticon)
        self.hide()

    def _load_icon(self, button: QToolButton, url: str) -> None:
        cached = self._image_cache.get(url)
        if cached is not None:
            button.setIcon(QIcon(cached))
            return

        self._button_by_url.setdefault(url, []).append(button)
        if len(self._button_by_url[url]) > 1:
            return

        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Referer", b"https://live.bilibili.com/")
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 BiliHUD")
        reply = self._network_manager.get(request)
        if reply is None:
            self._button_by_url.pop(url, None)
            return
        reply.finished.connect(lambda reply=reply, url=url: self._on_icon_loaded(reply, url))

    def _on_icon_loaded(self, reply: QNetworkReply, url: str) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(reply.readAll())
        reply.deleteLater()
        buttons = self._button_by_url.pop(url, [])
        if pixmap.isNull():
            return
        self._image_cache[url] = pixmap
        icon = QIcon(pixmap)
        for button in buttons:
            button.setIcon(icon)


__all__ = ("EmoticonPickerPopup",)
