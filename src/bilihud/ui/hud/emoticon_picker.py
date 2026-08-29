"""Live-emoticon picker and its image-loading presentation state."""

from __future__ import annotations

from html import escape
from typing import Protocol

from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bilihud.live.emoticons import LiveEmoticon, LiveEmoticonPackage
from bilihud.ui.hud.icons import smile_icon


class IconNetworkManager(Protocol):
    """Small network capability used to fetch one emoticon image."""

    def get(self, request: QNetworkRequest) -> QNetworkReply | None:
        """Start one image request and return its reply handle."""
        ...


class EmoticonPickerPopup(QDialog):
    """Render available live-room emoticons and emit the selected value."""

    emoticon_selected = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the popup and its owned Qt image-loading manager."""
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(360, 292)
        self._network_manager: IconNetworkManager = QNetworkAccessManager(self)
        self._image_cache: dict[str, QPixmap] = {}
        self._button_by_url: dict[str, list[QToolButton]] = {}
        self._tab_pages_by_url: dict[str, list[QWidget]] = {}
        self._requested_icon_urls: set[str] = set()
        self._emoticon_buttons: list[QToolButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(7, 7, 7, 7)
        self.container = QFrame(self)
        self.container.setObjectName("emoticon_surface")
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.container.setGraphicsEffect(shadow)
        self.container.setStyleSheet(
            """
            QFrame#emoticon_surface {
                background: rgba(20, 20, 30, 220);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 15px;
            }
            QTabWidget#emoticon_tabs {
                background: transparent;
            }
            QTabWidget#emoticon_tabs::pane {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                min-width: 34px;
                max-width: 34px;
                min-height: 34px;
                max-height: 34px;
                padding: 3px;
                margin: 0 7px 7px 0;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
            }
            QTabBar::tab:selected {
                background: rgba(79, 172, 254, 80);
                border-bottom: 2px solid #4facfe;
            }
            QTabBar::tab:hover:!selected {
                background: rgba(255, 255, 255, 35);
            }
            QLabel#status_label {
                color: rgba(255, 255, 255, 180);
                font-size: 12px;
                padding: 30px;
            }
            QToolTip {
                color: white;
                background: #2b2f38;
                border: 1px solid rgba(255, 255, 255, 70);
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QScrollArea#emoticon_scroll {
                background: transparent;
                border: none;
            }
            QWidget#emoticon_grid {
                background: transparent;
            }
            QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 10px;
                color: white;
                padding: 2px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 30);
            }
            QToolButton:pressed {
                background: rgba(79, 172, 254, 100);
            }
            QToolButton:focus {
                border-color: rgba(79, 172, 254, 180);
            }
            QToolButton:disabled {
                background: transparent;
                border-color: transparent;
                color: rgba(255, 255, 255, 140);
            }
            QScrollBar:vertical {
                width: 7px;
                margin: 2px 0;
                background: transparent;
                border: none;
            }
            QScrollBar::handle:vertical {
                min-height: 28px;
                background: rgba(255, 255, 255, 48);
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 92);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                height: 0;
                background: transparent;
            }
            QScrollBar:horizontal {
                height: 0;
                background: transparent;
                border: none;
            }
        """
        )
        outer.addWidget(self.container)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(0)
        self.tabs = QTabWidget(self.container)
        self.tabs.setObjectName("emoticon_tabs")
        tab_bar = self.tabs.tabBar()
        tab_bar.setIconSize(QSize(26, 26))
        tab_bar.setExpanding(False)
        tab_bar.setDrawBase(False)
        layout.addWidget(self.tabs)

    def set_loading(self) -> None:
        """Render the loading state while the HUD service fetches packages."""
        self._clear_tabs()
        label = QLabel("加载中...", self)
        label.setObjectName("status_label")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index = self.tabs.addTab(label, smile_icon(), "")
        self.tabs.setTabToolTip(index, "加载中...")

    def set_error(self, message: str) -> None:
        """Render one user-visible package-loading error."""
        self._clear_tabs()
        label = QLabel(message, self)
        label.setObjectName("status_label")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index = self.tabs.addTab(label, smile_icon(), "")
        self.tabs.setTabToolTip(index, "表情加载失败")

    def set_packages(self, packages: list[LiveEmoticonPackage]) -> None:
        """Replace the popup contents with normalized emoticon packages."""
        self._clear_tabs()
        if not packages:
            self.set_error("没有可显示的直播间表情")
            return

        for package in packages:
            page = QWidget(self)
            page.setObjectName("emoticon_page")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 2, 0, 0)
            page_layout.setSpacing(0)
            scroll = QScrollArea(page)
            scroll.setObjectName("emoticon_scroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.viewport().setStyleSheet("background: transparent;")
            grid_host = QWidget(scroll)
            grid_host.setObjectName("emoticon_grid")
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(4, 3, 4, 5)
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(4)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

            tab_index = self.tabs.addTab(page, smile_icon(), "")
            self.tabs.setTabToolTip(tab_index, package.name)
            self.tabs.setTabWhatsThis(tab_index, package.name)
            self._register_tab_icon(page, package.cover_url)

            for index, emoticon in enumerate(package.emoticons):
                button = self._create_emoticon_button(emoticon)
                row, col = divmod(index, 5)
                grid.addWidget(button, row, col)
                self._emoticon_buttons.append(button)

            scroll.setWidget(grid_host)
            page_layout.addWidget(scroll)

    def _clear_tabs(self) -> None:
        self._tab_pages_by_url.clear()
        self._emoticon_buttons.clear()
        self._button_by_url.clear()
        while self.tabs.count():
            page = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if page is not None:
                page.deleteLater()

    def _register_tab_icon(self, page: QWidget, url: str) -> None:
        """Bind one package tab to its representative image URL."""
        if not url:
            return
        cached = self._image_cache.get(url)
        if cached is not None:
            self._set_tab_icon(page, cached)
            return
        self._tab_pages_by_url.setdefault(url, []).append(page)
        self._request_icon(url)

    def _set_tab_icon(self, page: QWidget, pixmap: QPixmap) -> None:
        """Replace a package tab placeholder with its loaded representative image."""
        index = self.tabs.indexOf(page)
        if index >= 0:
            self.tabs.setTabIcon(index, self._tab_icon(pixmap))

    def _tab_icon(self, pixmap: QPixmap) -> QIcon:
        """Center any package cover inside the fixed square tab icon area."""
        icon_size = self.tabs.iconSize()
        if pixmap.isNull() or icon_size.isEmpty():
            return QIcon(pixmap)

        scaled = pixmap.scaled(
            icon_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(icon_size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(
            (canvas.width() - scaled.width()) // 2,
            (canvas.height() - scaled.height()) // 2,
            scaled,
        )
        painter.end()
        return QIcon(canvas)

    def _create_emoticon_button(self, emoticon: LiveEmoticon) -> QToolButton:
        button = QToolButton(self)
        button.setFixedSize(52, 52)
        button.setIconSize(QSize(42, 42))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        label = emoticon.unlock_label
        tooltip = emoticon.emoji if not label else f"{emoticon.emoji} - {label}"
        button.setToolTip(self._tooltip_markup(tooltip))
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
                        background: transparent;
                        border: 1px solid transparent;
                        color: {color};
                    }}
                    """
                )
        else:
            button.clicked.connect(lambda _checked=False, item=emoticon: self._select_emoticon(item))

        self._load_icon(button, emoticon.url)
        return button

    @staticmethod
    def _tooltip_markup(text: str) -> str:
        """Keep tooltip text readable when the desktop tooltip palette is dark."""
        return (
            '<div style="color:#ffffff; background-color:#2b2f38; '
            f'padding:4px 8px;">{escape(text)}</div>'
        )

    def _select_emoticon(self, emoticon: LiveEmoticon) -> None:
        self.emoticon_selected.emit(emoticon)
        self.hide()

    def _load_icon(self, button: QToolButton, url: str) -> None:
        if not url:
            return
        cached = self._image_cache.get(url)
        if cached is not None:
            button.setIcon(QIcon(cached))
            return

        self._button_by_url.setdefault(url, []).append(button)
        self._request_icon(url)

    def _request_icon(self, url: str) -> None:
        """Start one shared image request for tab and grid consumers."""
        if not url or url in self._image_cache or url in self._requested_icon_urls:
            return

        self._requested_icon_urls.add(url)
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Referer", b"https://live.bilibili.com/")
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 BiliHUD")
        reply = self._network_manager.get(request)
        if reply is None:
            self._requested_icon_urls.discard(url)
            return
        reply.finished.connect(lambda reply=reply, url=url: self._on_icon_loaded(reply, url))

    def _on_icon_loaded(self, reply: QNetworkReply, url: str) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(reply.readAll())
        reply.deleteLater()
        self._requested_icon_urls.discard(url)
        buttons = self._button_by_url.pop(url, [])
        pages = self._tab_pages_by_url.pop(url, [])
        if pixmap.isNull():
            return
        self._image_cache[url] = pixmap
        icon = QIcon(pixmap)
        for button in buttons:
            button.setIcon(icon)
        for page in pages:
            self._set_tab_icon(page, pixmap)


__all__ = ("EmoticonPickerPopup",)
